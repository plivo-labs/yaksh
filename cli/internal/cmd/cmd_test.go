package cmd

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/plivo-labs/yaksh/cli/internal/config"
	"github.com/plivo-labs/yaksh/cli/skill"
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
	a := testApp(t, "0.1.0", vars, newFakeReleases(t))
	return execute(a, ctx, stdin, args...)
}

// testApp is the app that the binary makes, with a fake GitHub and no restart.
func testApp(t *testing.T, version string, vars map[string]string, releases *fakeReleases) *app {
	t.Helper()
	exe := filepath.Join(t.TempDir(), "yaksh")
	if err := os.WriteFile(exe, []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	return &app{
		version: version, getenv: func(k string) string { return vars[k] }, pollInterval: time.Millisecond,
		releases:   releases.Releases,
		executable: func() (string, error) { return exe, nil },
		restart:    func(string) error { t.Fatal("the CLI restarted"); return nil },
	}
}

func execute(a *app, ctx context.Context, stdin string, args ...string) (code int, stdout, stderr string) {
	var out, errOut bytes.Buffer
	code = a.execute(ctx, args, strings.NewReader(stdin), &out, &errOut)
	return code, out.String(), errOut.String()
}

func against(f *fakeAPI) map[string]string {
	return map[string]string{"YAKSH_URL": f.URL, "YAKSH_API_TOKEN": "t0k"}
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

func TestAgentImportPrintsTheDraftOrAddsTheAgent(t *testing.T) {
	const draft = `{"provider":"plivo_cx","name":"Dental front desk","external_id":"flow-1","languages":["en-IN","hi"],"language_note":null,"config":"{}"}`
	file := filepath.Join(t.TempDir(), "front-desk-config.json")
	if err := os.WriteFile(file, []byte(`{"flowId":"flow-1"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/agents/import": reply(200, draft),
		"POST /api/v1/agents":        reply(201, `{"id":"`+agentID+`"}`),
	})

	printed, stdout, stderr := run(t, context.Background(), against(f), "", "agent", "import", file, "--name", "Front desk")
	if printed != 0 || stderr != "" || !strings.Contains(stdout, `"name": "Front desk"`) || len(f.requests("POST", "/api/v1/agents")) != 0 {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", printed, stdout, stderr)
	}
	added, stdout, stderr := run(t, context.Background(), against(f), "",
		"agent", "import", file, "--brief", "Books dental appointments for callers.", "--number", "+14155550100")
	if added != 0 || stderr != "" || !strings.Contains(stdout, agentID) {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", added, stdout, stderr)
	}

	if sent := string(f.requests("POST", "/api/v1/agents/import")[0].body); sent != `{"content":"{\"flowId\":\"flow-1\"}"}` {
		t.Fatalf("import body = %s", sent)
	}
	var body map[string]any
	if err := json.Unmarshal(f.requests("POST", "/api/v1/agents")[0].body, &body); err != nil {
		t.Fatal(err)
	}
	want := `{"agent_number":"+14155550100","brief":"Books dental appointments for callers.","config":"{}","external_id":"flow-1","languages":["en-IN","hi"],"name":"Dental front desk"}`
	if got, _ := json.Marshal(body); string(got) != want {
		t.Fatalf("create body = %s, want %s", got, want)
	}
}

func TestAgentImportNeedsBothTheBriefAndTheNumber(t *testing.T) {
	f := newFakeAPI(t, nil)
	code, _, stderr := run(t, context.Background(), against(f), "", "agent", "import", "x.json", "--brief", "Books dental appointments.")

	if code == 0 || !strings.Contains(stderr, "number") || len(f.seen) != 0 {
		t.Fatalf("code = %d, stderr = %q, requests = %d", code, stderr, len(f.seen))
	}
}

func TestAgentImportAddsNoAgentWithoutALanguageYakshKnows(t *testing.T) {
	const draft = `{"provider":"plivo_cx","name":"Front desk","external_id":"flow-1","languages":[],"language_note":"Yaksh does not know the language multi. Choose the agent's languages","config":"{}"}`
	file := filepath.Join(t.TempDir(), "front-desk-config.json")
	if err := os.WriteFile(file, []byte(`{"flowId":"flow-1"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	f := newFakeAPI(t, map[string]http.HandlerFunc{"POST /api/v1/agents/import": reply(200, draft)})

	code, _, stderr := run(t, context.Background(), against(f), "",
		"agent", "import", file, "--brief", "Books dental appointments for callers.", "--number", "+14155550100")

	if code == 0 || !strings.Contains(stderr, "no language that Yaksh knows") || len(f.requests("POST", "/api/v1/agents")) != 0 {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
}

func TestListsSendOnlyTheFlagsThatWereSet(t *testing.T) {
	tests := []struct {
		args       []string
		path, want string
	}{
		{[]string{"agent", "list", "--external-id", "support-line", "--page", "2"}, "/api/v1/agents", "external_id=support-line&page=2"},
		{[]string{"scenario", "list", "--agent", agentID, "--page-size", "5"}, "/api/v1/agents/" + agentID + "/scenarios", "page_size=5"},
		{[]string{"run", "list", "--agent", agentID, "--status", "running"}, "/api/v1/runs", "agent_id=" + agentID + "&status=running"},
		{[]string{"run", "list", "--from", "2026-10-01", "--before", "2026-10-02T05:30:00+05:30"}, "/api/v1/runs",
			"created_before=2026-10-02T05%3A30%3A00%2B05%3A30&created_from=" +
				url.QueryEscape(time.Date(2026, 10, 1, 0, 0, 0, 0, time.Local).Format(time.RFC3339))},
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
		{"no server", map[string]string{}, []string{"agent", "list"}, `no Yaksh server: run "yaksh auth login" or set YAKSH_URL`},
		{"wrong token", against(refuses), []string{"agent", "list"}, `the token is wrong: run "yaksh auth login" or set YAKSH_API_TOKEN`},
		{"server message", against(missing), []string{"agent", "view", agentID}, "404 Not Found: agent not found"},
		{"server down", map[string]string{"YAKSH_URL": stopped.URL}, []string{"agent", "list"}, "cannot reach " + stopped.URL},
		{"bad agent ID", against(missing), []string{"agent", "view", "support-line"}, `"support-line" is not an agent ID: find it with "yaksh agent list"`},
		{"bad answer", against(missing), []string{"run", "start", "--agent", agentID, "--all", "--answer", "machine"}, `"machine" is not an answer: use caller, voicemail or screener`},
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
		"--transport", "phone", "--answer", "caller,voicemail", "--idempotency-key", "ci-41")

	if code != 0 || !strings.Contains(stdout, `"status": "queued"`) || stderr != "next: yaksh run wait "+runID+"\n" {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
	}
	req := f.requests("POST", "/api/v1/runs")[0]
	var body map[string]any
	if err := json.Unmarshal(req.body, &body); err != nil {
		t.Fatal(err)
	}
	want := fmt.Sprintf(`{"agent_id":"%s","repeats":2,"scenarios":[{"answered_by":["caller","voicemail"],"scenario_id":"%s"},{"answered_by":["caller","voicemail"],"scenario_id":"%s"}],"transport":"phone"}`, agentID, scenA, scenB)
	if got, _ := json.Marshal(body); string(got) != want {
		t.Fatalf("body = %s, want %s", got, want)
	}
	if key := req.header.Get("Idempotency-Key"); key != "ci-41" {
		t.Fatalf("Idempotency-Key = %q", key)
	}
}

type closedPipe struct{}

func (closedPipe) Write([]byte) (int, error) { return 0, io.ErrClosedPipe }

func TestRunStartKeepsTheIDWhenStdoutFails(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/runs": reply(202, runJSON("queued", `"waiting":1`)),
	})
	vars := against(f)
	a := &app{version: "0.1.0", getenv: func(k string) string { return vars[k] }}
	var stderr bytes.Buffer
	args := []string{"run", "start", "--agent", agentID, "--scenario", scenA}
	code := a.execute(context.Background(), args, strings.NewReader(""), closedPipe{}, &stderr)
	if code != 1 || !strings.Contains(stderr.String(), runID) {
		t.Fatalf("code = %d, stderr = %q; want 1 and the run ID", code, stderr.String())
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
		Scenarios []struct {
			ScenarioID string `json:"scenario_id"`
		} `json:"scenarios"`
	}
	json.Unmarshal(f.requests("POST", "/api/v1/runs")[0].body, &body)
	if len(body.Scenarios) != 101 {
		t.Fatalf("scenarios has %d items, want 101 from two pages", len(body.Scenarios))
	}
}

// metricsJSON is a run's metrics with pending calls and one scenario whose calls got verdicts.
// Each verdict is JSON; null is a failed evaluation.
func metricsJSON(pending int, verdicts ...string) string {
	calls := make([]string, len(verdicts))
	for i, verdict := range verdicts {
		calls[i] = fmt.Sprintf(`{"conversation_id":"%s","repeat":%d,"verdict":%s}`, convID, i+1, verdict)
	}
	return fmt.Sprintf(`{"verdicts":{"pending":%d,"errors":0,"scenarios":[{"scenario_id":"%s","calls":[%s]}]}}`,
		pending, scenA, strings.Join(calls, ","))
}

func TestRunStartWaitPassesWhenEveryCallCompleted(t *testing.T) {
	judged := fmt.Sprintf(`{"id":"%s","status":"done","counts":{"completed":2},"response_p90_ms":1200}`, runID)
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/runs":             reply(202, runJSON("queued", `"waiting":2`)),
		"GET /api/v1/runs/{id}":         replies(runJSON("running", `"in_progress":2`), runJSON("done", `"completed":2`), judged),
		"GET /api/v1/runs/{id}/metrics": reply(200, metricsJSON(0, `"pass"`, `"pass"`)),
	})
	code, stdout, stderr := run(t, context.Background(), against(f), "", "run", "start", "--agent", agentID, "--scenario", scenA, "--wait")

	// The run is printed as it is after the judges, with the response times that they compute.
	if code != 0 || !strings.Contains(stdout, `"response_p90_ms": 1200`) || !strings.HasSuffix(stderr, "done: 2 of 2 calls completed; judges: 2 pass\n") {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
	}
}

func TestRunWaitWaitsForTheJudgesAndFailsUnlessTheyPassEveryCall(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/runs/{id}":         reply(200, runJSON("done", `"completed":3`)),
		"GET /api/v1/runs/{id}/metrics": replies(metricsJSON(3), metricsJSON(0, `"pass"`, `"not_scored"`, `null`)),
	})
	code, _, stderr := run(t, context.Background(), against(f), "", "run", "wait", runID)

	want := "failed: run " + runID + " done: 3 of 3 calls completed; judges: 1 pass, 1 not scored, 1 evaluation failed\n" +
		"next: yaksh run metrics " + runID + "\n"
	if code != 1 || !strings.HasSuffix(stderr, want) || len(f.requests("GET", "/api/v1/runs/"+runID+"/metrics")) != 2 {
		t.Fatalf("code = %d, stderr = %q; want 1, two reads of the metrics and %q", code, stderr, want)
	}
}

func TestRunWaitFailsWhenTheRulesFailACallThatNoCallerTalkedOn(t *testing.T) {
	voicemail := fmt.Sprintf(`{"verdicts":{"pending":0,"errors":0,"scenarios":[{"scenario_id":"%s","calls":[{"conversation_id":"%s","repeat":1,"verdict":"pass"}]}],"unplayed":[{"conversation_id":"%s","scenario_id":"%s","repeat":1,"answered_by":"voicemail","verdict":"fail"}]}}`,
		scenA, convID, convID, scenA)
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/runs/{id}":         reply(200, runJSON("done", `"completed":2`)),
		"GET /api/v1/runs/{id}/metrics": reply(200, voicemail),
	})
	code, _, stderr := run(t, context.Background(), against(f), "", "run", "wait", runID)

	want := "failed: run " + runID + " done: 2 of 2 calls completed; judges: 1 pass, 1 fail\n"
	if code != 1 || !strings.Contains(stderr, want) {
		t.Fatalf("code = %d, stderr = %q; want 1 and %q", code, stderr, want)
	}
}

func TestRunWaitFailsAndSaysWhatToRunNext(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/runs/{id}": reply(200, runJSON("done", `"completed":3,"did_not_connect":1`)),
	})
	code, stdout, stderr := run(t, context.Background(), against(f), "", "run", "wait", runID)

	want := "failed: run " + runID + " done: 3 of 4 calls completed, 1 did not connect\n" +
		"next: yaksh conversation list --run " + runID + " --latest-attempts --group error,did_not_connect\n"
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

	for _, want := range []string{"run " + runID + " started", "could not read run " + runID, "next: yaksh run wait " + runID} {
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

func TestRunCancelSaysWhatToRunNextWhenTheWaitEnds(t *testing.T) {
	stopped, firstRead := stopOnFirstRead()
	tests := []struct {
		name string
		ctx  context.Context
		read http.HandlerFunc
		want string
	}{
		{"read fails", context.Background(), reply(503, `{"error":{"code":"unavailable","message":"database is down"}}`), "could not read run " + runID},
		{"stopped", stopped, firstRead, "stopped waiting"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			f := newFakeAPI(t, map[string]http.HandlerFunc{
				"POST /api/v1/runs/{id}/cancel": reply(202, runJSON("cancelling", `"in_progress":1`)),
				"GET /api/v1/runs/{id}":         tt.read,
			})
			code, _, stderr := run(t, tt.ctx, against(f), "", "run", "cancel", runID)

			for _, want := range []string{tt.want, "the cancel was sent", "next: yaksh run cancel " + runID} {
				if code != 1 || !strings.Contains(stderr, want) {
					t.Fatalf("code = %d, stderr = %q; want %q", code, stderr, want)
				}
			}
		})
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
	if _, err := os.Stat(home + "/.config/yaksh/config.json"); !os.IsNotExist(err) {
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
	if code != 1 || !strings.Contains(stderr, "no Yaksh server") {
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
		{"https://yaksh.example.com", false, false},
		{"http://localhost:8000", false, false},
		{"http://127.0.0.1:8000", false, false},
		{"http://yaksh.example.com", true, false},
		{"yaksh.example.com", false, true},
		{"ftp://yaksh.example.com", false, true},
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

func TestSettingsApplySendsTheValuesOfTheVariablesTheFileNames(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/settings/import": reply(200, `{"changes":["llm_api_key: added"],"skipped":[]}`),
	})
	file := filepath.Join(t.TempDir(), "settings.yaml")
	document := "# A secret is ${NAME}.\ncaller:\n  model: gpt-6-luna\nsecrets:\n  llm_api_key: ${LLM_API_KEY}\n"
	if err := os.WriteFile(file, []byte(document), 0o600); err != nil {
		t.Fatal(err)
	}
	vars := against(f)
	vars["LLM_API_KEY"] = "sk-test"

	code, _, stderr := run(t, context.Background(), vars, "", "settings", "apply", "-f", file)

	if code != 0 || stderr != "" {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	var sent struct {
		Document string            `json:"document"`
		Env      map[string]string `json:"env"`
		DryRun   bool              `json:"dry_run"`
	}
	if err := json.Unmarshal(f.requests("POST", "/api/v1/settings/import")[0].body, &sent); err != nil {
		t.Fatal(err)
	}
	if sent.Document != document || sent.Env["LLM_API_KEY"] != "sk-test" || len(sent.Env) != 1 || sent.DryRun {
		t.Fatalf("sent = %+v", sent)
	}
}

func TestSettingsApplyExitsWithStatus1AndNamesTheKeysThatFailed(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/settings/import": reply(200, `{"changes":["caller.model: a -> b"],"skipped":[],`+
			`"failed":["deepgram_api_key: Deepgram did not answer: TimeoutError"]}`),
	})
	file := filepath.Join(t.TempDir(), "settings.yaml")
	if err := os.WriteFile(file, []byte("secrets:\n  deepgram_api_key: dg-key\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	code, stdout, stderr := run(t, context.Background(), against(f), "", "settings", "apply", "-f", file)

	if code != 1 || !strings.Contains(stdout, `"caller.model: a -> b"`) {
		t.Fatalf("code = %d, stdout = %q", code, stdout)
	}
	if !strings.Contains(stderr, "deepgram_api_key: Deepgram did not answer: TimeoutError") {
		t.Fatalf("stderr = %q", stderr)
	}
}

func TestSettingsApplyStopsBeforeTheServerWhenAVariableIsNotSet(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/settings/import": reply(200, `{}`),
	})
	file := filepath.Join(t.TempDir(), "settings.yaml")
	document := "secrets:\n  llm_api_key: ${LLM_API_KEY}\n  deepgram_api_key: ${DEEPGRAM_API_KEY}\n"
	if err := os.WriteFile(file, []byte(document), 0o600); err != nil {
		t.Fatal(err)
	}

	code, _, stderr := run(t, context.Background(), against(f), "", "settings", "apply", "-f", file)

	if code != 1 || !strings.Contains(stderr, "DEEPGRAM_API_KEY, LLM_API_KEY") {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	if n := len(f.requests("POST", "/api/v1/settings/import")); n != 0 {
		t.Fatalf("the server got %d requests", n)
	}
}

func TestSettingsApplyDryRunSendsTheFileWhenAVariableIsNotSet(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/settings/import": reply(200, `{"changes":[],"skipped":["llm_api_key (${LLM_API_KEY})"]}`),
	})
	file := filepath.Join(t.TempDir(), "settings.yaml")
	if err := os.WriteFile(file, []byte("secrets:\n  llm_api_key: ${LLM_API_KEY}\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	code, _, stderr := run(t, context.Background(), against(f), "", "settings", "apply", "-f", file, "--dry-run")

	if code != 0 || stderr != "" || len(f.requests("POST", "/api/v1/settings/import")) != 1 {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
}

const phoneListing = `{"items":[` +
	`{"number":"+14155550100","owner":"test","state":"ready"},` +
	`{"number":"+14155550101","owner":"free","state":null},` +
	`{"number":"+14155550102","owner":"cx_agent","state":null}],` +
	`"application_id":"7001","problem":null,"rest_s":300}`

func TestNumbersListOwnerKeepsOnlyThatOwnersNumbers(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{"GET /api/v1/phone-numbers": reply(200, phoneListing)})
	code, stdout, stderr := run(t, context.Background(), against(f), "", "numbers", "list", "--owner", "free")
	if code != 0 || stderr != "" {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	var got struct {
		Items []struct {
			Number string `json:"number"`
		} `json:"items"`
		ApplicationID string `json:"application_id"`
		RestS         int    `json:"rest_s"`
	}
	if err := json.Unmarshal([]byte(stdout), &got); err != nil {
		t.Fatalf("stdout is not JSON: %v\n%s", err, stdout)
	}
	if len(got.Items) != 1 || got.Items[0].Number != "+14155550101" || got.ApplicationID != "7001" || got.RestS != 300 {
		t.Fatalf("stdout = %s", stdout)
	}
}

func TestNumbersListRefusesAnUnknownOwnerBeforeTheServer(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{"GET /api/v1/phone-numbers": reply(200, phoneListing)})
	code, stdout, stderr := run(t, context.Background(), against(f), "", "numbers", "list", "--owner", "mine")
	if code != 1 || stdout != "" || !strings.Contains(stderr, `"mine" is not an owner`) {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
	}
	if n := len(f.requests("GET", "/api/v1/phone-numbers")); n != 0 {
		t.Fatalf("requests = %d, want 0", n)
	}
}

func TestNumbersChangesPostToTheNumberAndPrintTheListing(t *testing.T) {
	tests := []struct {
		args []string
		path string
	}{
		{[]string{"numbers", "use", "+14155550101"}, "/api/v1/phone-numbers/+14155550101/use"},
		{[]string{"numbers", "stop", "+14155550100"}, "/api/v1/phone-numbers/+14155550100/stop"},
		{[]string{"numbers", "refresh"}, "/api/v1/phone-numbers/refresh"},
	}
	for _, tt := range tests {
		t.Run(tt.args[1], func(t *testing.T) {
			f := newFakeAPI(t, map[string]http.HandlerFunc{"POST " + tt.path: reply(200, phoneListing)})
			code, stdout, stderr := run(t, context.Background(), against(f), "", tt.args...)
			if code != 0 || stderr != "" || !strings.Contains(stdout, `"application_id": "7001"`) {
				t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
			}
			if n := len(f.requests("POST", tt.path)); n != 1 {
				t.Fatalf("POST %s requests = %d, want 1", tt.path, n)
			}
		})
	}
}

func TestNumbersStopShowsWhyTheServerRefused(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/phone-numbers/{number}/stop": reply(409, `{"error":{"code":"conflict","message":"+14155550100 is in a test"}}`),
	})
	code, stdout, stderr := run(t, context.Background(), against(f), "", "numbers", "stop", "+14155550100")
	if code != 1 || stdout != "" || !strings.Contains(stderr, "409 Conflict: +14155550100 is in a test") {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
	}
}
