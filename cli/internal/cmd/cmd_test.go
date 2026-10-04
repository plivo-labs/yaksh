package cmd

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/plivo-labs/truman/cli/internal/config"
	"github.com/plivo-labs/truman/cli/skill"
)

const (
	agentID = "0b9e0c4a-0000-4000-8000-000000000001"
	runID   = "7c1e2a0b-0000-4000-8000-000000000002"
	convID  = "51aa09c3-0000-4000-8000-000000000003"
	scenA   = "3f2a0000-0000-4000-8000-00000000000a"
	scenB   = "9b1c0000-0000-4000-8000-00000000000b"
)

// request is what the fake API received.
type request struct {
	method, path, query string
	header              http.Header
	body                []byte
}

// fakeAPI serves routes such as "GET /api/v1/runs/{id}" and records every request.
type fakeAPI struct {
	*httptest.Server
	mu   sync.Mutex
	seen []request
}

func newFakeAPI(t *testing.T, routes map[string]http.HandlerFunc) *fakeAPI {
	t.Helper()
	mux := http.NewServeMux()
	for pattern, handler := range routes {
		mux.HandleFunc(pattern, handler)
	}
	f := &fakeAPI{}
	f.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		f.mu.Lock()
		f.seen = append(f.seen, request{r.Method, r.URL.Path, r.URL.RawQuery, r.Header.Clone(), body})
		f.mu.Unlock()
		r.Body = io.NopCloser(bytes.NewReader(body))
		mux.ServeHTTP(w, r)
	}))
	t.Cleanup(f.Close)
	return f
}

// requests returns the requests with this method and path, in order.
func (f *fakeAPI) requests(method, path string) []request {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []request
	for _, r := range f.seen {
		if r.method == method && r.path == path {
			out = append(out, r)
		}
	}
	return out
}

func reply(status int, body string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
		w.Write([]byte(body))
	}
}

// replies answers with each body in turn, then repeats the last one.
func replies(bodies ...string) http.HandlerFunc {
	var (
		mu sync.Mutex
		n  int
	)
	return func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		body := bodies[min(n, len(bodies)-1)]
		n++
		mu.Unlock()
		w.Write([]byte(body))
	}
}

func runJSON(status, counts string) string {
	return fmt.Sprintf(`{"id":"%s","status":"%s","counts":{%s}}`, runID, status, counts)
}

// run executes a command line with only the given environment, as the binary would.
func run(t *testing.T, ctx context.Context, vars map[string]string, stdin string, args ...string) (code int, stdout, stderr string) {
	t.Helper()
	if _, ok := vars["HOME"]; !ok {
		vars["HOME"] = t.TempDir()
	}
	a := &app{version: "0.1.0", getenv: func(k string) string { return vars[k] }, pollInterval: time.Millisecond}
	var out, errOut bytes.Buffer
	code = a.execute(ctx, args, strings.NewReader(stdin), &out, &errOut)
	return code, out.String(), errOut.String()
}

func against(f *fakeAPI) map[string]string {
	return map[string]string{"TRUMAN_URL": f.URL, "TRUMAN_API_TOKEN": "t0k"}
}

func TestAgentListPrintsTheServersJSON(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/agents": reply(200, `{"items":[{"id":"a1","name":"Support line"}],"total":1}`),
	})
	code, stdout, stderr := run(t, context.Background(), against(f), "", "agent", "list")

	want := "{\n  \"items\": [\n    {\n      \"id\": \"a1\",\n      \"name\": \"Support line\"\n    }\n  ],\n  \"total\": 1\n}\n"
	if code != 0 || stderr != "" || stdout != want {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
	}
	req := f.requests("GET", "/api/v1/agents")[0]
	if req.query != "" || req.header.Get("Authorization") != "Bearer t0k" {
		t.Fatalf("query = %q, Authorization = %q", req.query, req.header.Get("Authorization"))
	}
}

func TestListsSendOnlyTheFlagsThatWereSet(t *testing.T) {
	tests := []struct {
		args       []string
		path, want string
	}{
		{[]string{"agent", "list", "--external-id", "support-line", "--page", "2"}, "/api/v1/agents", "external_id=support-line&page=2"},
		{[]string{"scenario", "list", "--agent", agentID, "--page-size", "5"}, "/api/v1/agents/" + agentID + "/scenarios", "page_size=5"},
		{[]string{"run", "list", "--agent", agentID}, "/api/v1/runs", "agent_id=" + agentID},
		{[]string{"conversation", "list", "--run", runID, "--latest-attempts", "--group", "error,did_not_connect"}, "/api/v1/conversations",
			"group=did_not_connect&group=error&latest_attempts=true&run_id=" + runID},
	}
	for _, tt := range tests {
		t.Run(strings.Join(tt.args[:2], " "), func(t *testing.T) {
			f := newFakeAPI(t, map[string]http.HandlerFunc{"GET " + tt.path: reply(200, `{"items":[]}`)})
			if code, _, stderr := run(t, context.Background(), against(f), "", tt.args...); code != 0 {
				t.Fatalf("code = %d, stderr = %q", code, stderr)
			}
			got := f.requests("GET", tt.path)[0].query
			if q := sortedQuery(t, got); q != tt.want {
				t.Fatalf("query = %q, want %q", q, tt.want)
			}
		})
	}
}

func sortedQuery(t *testing.T, raw string) string {
	t.Helper()
	parts := strings.Split(raw, "&")
	slices.Sort(parts)
	return strings.Join(parts, "&")
}

func TestErrorsSayTheNextStep(t *testing.T) {
	refuses := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/agents": reply(401, `{"error":{"code":"unauthorized","message":"missing or invalid bearer token"}}`),
	})
	missing := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/agents/{id}": reply(404, `{"error":{"code":"not_found","message":"agent not found"}}`),
	})
	stopped := httptest.NewServer(http.NotFoundHandler())
	stopped.Close()

	tests := []struct {
		name string
		vars map[string]string
		args []string
		want string
	}{
		{"no server", map[string]string{}, []string{"agent", "list"}, `no Truman server: run "truman auth login" or set TRUMAN_URL`},
		{"wrong token", against(refuses), []string{"agent", "list"}, `the token is wrong: run "truman auth login" or set TRUMAN_API_TOKEN`},
		{"server message", against(missing), []string{"agent", "view", agentID}, "404 Not Found: agent not found"},
		{"server down", map[string]string{"TRUMAN_URL": stopped.URL}, []string{"agent", "list"}, "cannot reach " + stopped.URL},
		{"bad agent ID", against(missing), []string{"agent", "view", "support-line"}, `"support-line" is not an agent ID: find it with "truman agent list"`},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			code, stdout, stderr := run(t, context.Background(), tt.vars, "", tt.args...)
			if code != 1 || stdout != "" || !strings.Contains(stderr, tt.want) {
				t.Fatalf("code = %d, stdout = %q, stderr = %q; want 1 and %q", code, stdout, stderr, tt.want)
			}
		})
	}
}

func TestRunStartSendsOnlyTheFieldsThatWereSet(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/runs": reply(202, runJSON("queued", `"waiting":4`)),
	})
	code, stdout, stderr := run(t, context.Background(), against(f), "",
		"run", "start", "--agent", agentID, "--scenario", scenA+","+scenB, "--repeats", "2",
		"--noise-sound", "cafe", "--idempotency-key", "ci-41")

	if code != 0 || !strings.Contains(stdout, `"status": "queued"`) || stderr != "next: truman run wait "+runID+"\n" {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
	}
	req := f.requests("POST", "/api/v1/runs")[0]
	var body map[string]any
	if err := json.Unmarshal(req.body, &body); err != nil {
		t.Fatal(err)
	}
	want := fmt.Sprintf(`{"agent_id":"%s","background_noise":{"sound":"cafe"},"repeats":2,"scenario_ids":["%s","%s"]}`, agentID, scenA, scenB)
	if got, _ := json.Marshal(body); string(got) != want {
		t.Fatalf("body = %s, want %s", got, want)
	}
	if key := req.header.Get("Idempotency-Key"); key != "ci-41" {
		t.Fatalf("Idempotency-Key = %q", key)
	}
}

type closedPipe struct{}

func (closedPipe) Write([]byte) (int, error) { return 0, io.ErrClosedPipe }

func TestStartKeepsTheIDWhenStdoutFails(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/runs":          reply(202, runJSON("queued", `"waiting":1`)),
		"POST /api/v1/conversations": reply(202, fmt.Sprintf(`{"id":"%s","status":"queued"}`, convID)),
	})
	vars := against(f)
	tests := []struct {
		args []string
		id   string
	}{
		{[]string{"run", "start", "--agent", agentID, "--scenario", scenA}, runID},
		{[]string{"conversation", "start", "--agent", agentID, "--scenario", scenA}, convID},
	}
	for _, tt := range tests {
		t.Run(tt.args[0], func(t *testing.T) {
			a := &app{version: "0.1.0", getenv: func(k string) string { return vars[k] }}
			var stderr bytes.Buffer
			code := a.execute(context.Background(), tt.args, strings.NewReader(""), closedPipe{}, &stderr)
			if code != 1 || !strings.Contains(stderr.String(), tt.id) {
				t.Fatalf("code = %d, stderr = %q; want 1 and the ID", code, stderr.String())
			}
		})
	}
}

func TestRunStartAllTakesEveryPageOfScenarios(t *testing.T) {
	page := func(first, n, total int) string {
		items := make([]string, n)
		for i := range items {
			items[i] = fmt.Sprintf(`{"id":"00000000-0000-4000-8000-%012d"}`, first+i)
		}
		return fmt.Sprintf(`{"items":[%s],"total":%d}`, strings.Join(items, ","), total)
	}
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/agents/{id}/scenarios": replies(page(0, 100, 101), page(100, 1, 101)),
		"POST /api/v1/runs":                 reply(202, runJSON("queued", `"waiting":101`)),
	})
	if code, _, stderr := run(t, context.Background(), against(f), "", "run", "start", "--agent", agentID, "--all"); code != 0 {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	var body struct {
		ScenarioIDs []string `json:"scenario_ids"`
	}
	json.Unmarshal(f.requests("POST", "/api/v1/runs")[0].body, &body)
	if len(body.ScenarioIDs) != 101 {
		t.Fatalf("scenario_ids has %d IDs, want 101 from two pages", len(body.ScenarioIDs))
	}
}

func TestRunStartWaitPassesWhenEveryCallCompleted(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/runs":     reply(202, runJSON("queued", `"waiting":2`)),
		"GET /api/v1/runs/{id}": replies(runJSON("running", `"in_progress":2`), runJSON("done", `"completed":2`)),
	})
	code, stdout, stderr := run(t, context.Background(), against(f), "", "run", "start", "--agent", agentID, "--scenario", scenA, "--wait")

	if code != 0 || !strings.Contains(stdout, `"status": "done"`) || !strings.HasSuffix(stderr, "done: 2 of 2 calls completed\n") {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
	}
}

func TestRunWaitFailsAndSaysWhatToRunNext(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/runs/{id}": reply(200, runJSON("done", `"completed":3,"did_not_connect":1`)),
	})
	code, stdout, stderr := run(t, context.Background(), against(f), "", "run", "wait", runID)

	want := "error: run " + runID + " done: 3 of 4 calls completed, 1 did not connect\n" +
		"next: truman conversation list --run " + runID + " --latest-attempts --group error,did_not_connect\n"
	if code != 1 || !strings.Contains(stdout, `"status": "done"`) || stderr != want {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
	}
}

// stopOnFirstRead returns a context that ends when the fake API first serves the run.
func stopOnFirstRead() (context.Context, http.HandlerFunc) {
	ctx, cancel := context.WithCancel(context.Background())
	return ctx, func(w http.ResponseWriter, r *http.Request) {
		cancel()
		w.Write([]byte(runJSON("running", `"in_progress":1`)))
	}
}

func TestRunStartWaitCancelsTheRunWhenStopped(t *testing.T) {
	ctx, firstRead := stopOnFirstRead()
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/runs":             reply(202, runJSON("queued", `"waiting":1`)),
		"GET /api/v1/runs/{id}":         firstRead,
		"POST /api/v1/runs/{id}/cancel": reply(202, runJSON("cancelling", `"in_progress":1`)),
	})
	code, _, stderr := run(t, ctx, against(f), "", "run", "start", "--agent", agentID, "--scenario", scenA, "--wait")

	if code != 1 || len(f.requests("POST", "/api/v1/runs/"+runID+"/cancel")) != 1 || !strings.Contains(stderr, "is cancelled") {
		t.Fatalf("code = %d, stderr = %q, cancels = %d", code, stderr, len(f.requests("POST", "/api/v1/runs/"+runID+"/cancel")))
	}
}

func TestRunStartWaitCancelsARunCreatedWhileStopping(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/runs": func(w http.ResponseWriter, r *http.Request) {
			cancel()
			w.WriteHeader(http.StatusAccepted)
			w.Write([]byte(runJSON("queued", `"waiting":1`)))
		},
		"GET /api/v1/runs/{id}":         reply(200, runJSON("queued", `"waiting":1`)),
		"POST /api/v1/runs/{id}/cancel": reply(202, runJSON("cancelling", `"waiting":1`)),
	})
	code, _, stderr := run(t, ctx, against(f), "", "run", "start", "--agent", agentID, "--scenario", scenA, "--wait")

	if code != 1 || len(f.requests("POST", "/api/v1/runs/"+runID+"/cancel")) != 1 || !strings.Contains(stderr, "is cancelled") {
		t.Fatalf("code = %d, stderr = %q; want the new run cancelled", code, stderr)
	}
}

func TestRunStartWaitKeepsTheRunWhenReadingItFails(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/runs":     reply(202, runJSON("queued", `"waiting":1`)),
		"GET /api/v1/runs/{id}": reply(503, `{"error":{"code":"unavailable","message":"database is down"}}`),
	})
	code, _, stderr := run(t, context.Background(), against(f), "", "run", "start", "--agent", agentID, "--scenario", scenA, "--wait")

	for _, want := range []string{"run " + runID + " started", "could not read run " + runID, "next: truman run wait " + runID} {
		if code != 1 || !strings.Contains(stderr, want) {
			t.Fatalf("code = %d, stderr = %q; want %q", code, stderr, want)
		}
	}
}

func TestRunWaitLeavesTheRunAloneWhenStopped(t *testing.T) {
	ctx, firstRead := stopOnFirstRead()
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/runs/{id}":         firstRead,
		"POST /api/v1/runs/{id}/cancel": reply(202, "{}"),
	})
	code, _, stderr := run(t, ctx, against(f), "", "run", "wait", runID)

	if code != 1 || len(f.requests("POST", "/api/v1/runs/"+runID+"/cancel")) != 0 || !strings.Contains(stderr, "the run goes on") {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
}

func TestRunCancelWaitsUntilTheRunIsCancelled(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/runs/{id}/cancel": reply(202, runJSON("cancelling", `"in_progress":1`)),
		"GET /api/v1/runs/{id}":         replies(runJSON("cancelling", `"in_progress":1`), runJSON("cancelled", `"cancelled":1`)),
	})
	code, stdout, stderr := run(t, context.Background(), against(f), "", "run", "cancel", runID)

	if code != 0 || !strings.Contains(stdout, `"status": "cancelled"`) {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
	}
}

func TestConversationStartWaitPrintsEachEventThenTheConversation(t *testing.T) {
	events := "event: turn\ndata: {\"role\":\"agent\",\"text\":\"Hello\"}\n\n: ping\n\nevent: status\ndata: {\"status\":\"completed\"}\n\n"
	for _, tt := range []struct {
		status, endReason string
		code              int
	}{
		{"completed", "caller_hangup", 0},
		{"failed", "no_answer", 1},
	} {
		t.Run(tt.status, func(t *testing.T) {
			conversation := fmt.Sprintf(`{"id":"%s","status":"%s","end_reason":"%s"}`, convID, tt.status, tt.endReason)
			f := newFakeAPI(t, map[string]http.HandlerFunc{
				"POST /api/v1/conversations":            reply(202, fmt.Sprintf(`{"id":"%s","status":"queued"}`, convID)),
				"GET /api/v1/conversations/{id}/events": reply(200, events),
				"GET /api/v1/conversations/{id}":        reply(200, conversation),
			})
			code, stdout, stderr := run(t, context.Background(), against(f), "",
				"conversation", "start", "--agent", agentID, "--scenario", scenA, "--wait")

			want := `{"event":"turn","data":{"role":"agent","text":"Hello"}}` + "\n" +
				`{"event":"status","data":{"status":"completed"}}` + "\n" +
				`{"event":"conversation","data":` + conversation + "}\n"
			if code != tt.code || stdout != want {
				t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
			}
			if tt.code == 1 && !strings.Contains(stderr, "next: truman conversation view "+convID) {
				t.Fatalf("stderr = %q, want the next command", stderr)
			}
		})
	}
}

func TestConversationStartWaitSaysWhenTheStreamEndsBeforeTheCall(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/conversations":            reply(202, fmt.Sprintf(`{"id":"%s","status":"queued"}`, convID)),
		"GET /api/v1/conversations/{id}/events": reply(200, "event: status\ndata: {\"status\":\"running\"}\n\n"),
		"GET /api/v1/conversations/{id}":        reply(200, fmt.Sprintf(`{"id":"%s","status":"running"}`, convID)),
	})
	code, _, stderr := run(t, context.Background(), against(f), "", "conversation", "start", "--agent", agentID, "--scenario", scenA, "--wait")

	if code != 1 || !strings.Contains(stderr, "the event stream ended before the call; the call is running") {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
}

func TestConversationStartWaitKeepsACallStartedWhileStopping(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/conversations": func(w http.ResponseWriter, r *http.Request) {
			cancel()
			w.WriteHeader(http.StatusAccepted)
			w.Write([]byte(fmt.Sprintf(`{"id":"%s","status":"queued"}`, convID)))
		},
		"GET /api/v1/conversations/{id}/events": reply(200, ""),
	})
	code, _, stderr := run(t, ctx, against(f), "", "conversation", "start", "--agent", agentID, "--scenario", scenA, "--wait")

	for _, want := range []string{"conversation " + convID + " started", "the call goes on", "next: truman conversation view " + convID} {
		if code != 1 || !strings.Contains(stderr, want) {
			t.Fatalf("code = %d, stderr = %q; want %q", code, stderr, want)
		}
	}
}

func TestConversationStartWaitKeepsTheIDWhenTheLastReadFails(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/conversations":            reply(202, fmt.Sprintf(`{"id":"%s","status":"queued"}`, convID)),
		"GET /api/v1/conversations/{id}/events": reply(200, "event: status\ndata: {\"status\":\"completed\"}\n\n"),
		"GET /api/v1/conversations/{id}":        reply(503, `{"error":{"code":"unavailable","message":"database is down"}}`),
	})
	code, _, stderr := run(t, context.Background(), against(f), "", "conversation", "start", "--agent", agentID, "--scenario", scenA, "--wait")

	if code != 1 || !strings.Contains(stderr, "could not read conversation "+convID) || !strings.Contains(stderr, "next: truman conversation view "+convID) {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
}

func TestAuthLoginChecksThenSaves(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/health": reply(200, `{"status":"ok","version":"0.1.0"}`),
		"GET /api/v1/agents": reply(200, `{"items":[]}`),
	})
	vars := map[string]string{"HOME": t.TempDir()}
	code, _, stderr := run(t, context.Background(), vars, "s3cret\n", "auth", "login", "--server", f.URL, "--with-token")

	if code != 0 || !strings.Contains(stderr, "logged in to "+f.URL) {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	if auth := f.requests("GET", "/api/v1/agents")[0].header.Get("Authorization"); auth != "Bearer s3cret" {
		t.Fatalf("Authorization = %q", auth)
	}
	saved, err := config.Load(func(k string) string { return vars[k] })
	if err != nil || saved.Settings != (config.Settings{Server: f.URL, Token: "s3cret"}) {
		t.Fatalf("saved = %+v, %v", saved, err)
	}
}

func TestAuthLoginSavesNothingWhenTheServerRefusesTheToken(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/health": reply(200, `{"status":"ok","version":"0.1.0"}`),
		"GET /api/v1/agents": reply(401, `{"error":{"code":"unauthorized","message":"no"}}`),
	})
	home := t.TempDir()
	code, _, stderr := run(t, context.Background(), map[string]string{"HOME": home}, "wrong\n",
		"auth", "login", "--server", f.URL, "--with-token")

	if code != 1 || !strings.Contains(stderr, "nothing was saved") {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	if _, err := os.Stat(home + "/.config/truman/config.json"); !os.IsNotExist(err) {
		t.Fatalf("a config file exists: %v", err)
	}
}

func TestAuthStatusThenLogout(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/health": reply(200, `{"status":"ok","version":"0.4.2"}`),
		"GET /api/v1/agents": reply(200, `{"items":[]}`),
	})
	vars := map[string]string{"HOME": t.TempDir()}
	getenv := func(k string) string { return vars[k] }
	if err := config.Save(getenv, config.Settings{Server: f.URL, Token: "t0k"}); err != nil {
		t.Fatal(err)
	}

	code, stdout, _ := run(t, context.Background(), vars, "", "auth", "status")
	want := fmt.Sprintf(`{"server":"%s","server_from":"file","token_from":"file","cli_version":"0.1.0","server_version":"0.4.2"}`, f.URL)
	if code != 0 || compact(t, stdout) != want {
		t.Fatalf("code = %d, stdout = %s; want %s", code, stdout, want)
	}

	code, _, stderr := run(t, context.Background(), vars, "", "auth", "logout")
	if code != 0 || !strings.HasPrefix(stderr, "deleted ") {
		t.Fatalf("logout: code = %d, stderr = %q", code, stderr)
	}
	code, _, stderr = run(t, context.Background(), vars, "", "auth", "status")
	if code != 1 || !strings.Contains(stderr, "no Truman server") {
		t.Fatalf("status after logout: code = %d, stderr = %q", code, stderr)
	}
}

func compact(t *testing.T, s string) string {
	t.Helper()
	var buf bytes.Buffer
	if err := json.Compact(&buf, []byte(s)); err != nil {
		t.Fatalf("not JSON: %q", s)
	}
	return buf.String()
}

func TestCheckServer(t *testing.T) {
	tests := []struct {
		server  string
		warns   bool
		refused bool
	}{
		{"https://truman.example.com", false, false},
		{"http://localhost:8000", false, false},
		{"http://127.0.0.1:8000", false, false},
		{"http://truman.example.com", true, false},
		{"truman.example.com", false, true},
		{"ftp://truman.example.com", false, true},
	}
	for _, tt := range tests {
		warning, err := checkServer(tt.server)
		if (warning != "") != tt.warns || (err != nil) != tt.refused {
			t.Errorf("checkServer(%q) = %q, %v", tt.server, warning, err)
		}
	}
}

func TestGuidePrintsTheSkillWithoutAServer(t *testing.T) {
	code, stdout, stderr := run(t, context.Background(), map[string]string{}, "", "guide")
	if code != 0 || stderr != "" || stdout != skill.Text {
		t.Fatalf("code = %d, stderr = %q, stdout starts %q", code, stderr, stdout[:min(len(stdout), 40)])
	}
}

func TestVersionShowsBothVersions(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/health": reply(200, `{"status":"ok","version":"0.4.2"}`),
	})
	code, stdout, _ := run(t, context.Background(), against(f), "", "version")

	if code != 0 || stdout != "{\n  \"cli\": \"0.1.0\",\n  \"server\": \"0.4.2\"\n}\n" {
		t.Fatalf("code = %d, stdout = %q", code, stdout)
	}
}
