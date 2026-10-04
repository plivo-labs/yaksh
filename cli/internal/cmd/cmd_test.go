package cmd

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// run executes a command line with only the given environment, as the binary would.
func run(t *testing.T, vars map[string]string, args ...string) (code int, stdout, stderr string) {
	t.Helper()
	if _, ok := vars["HOME"]; !ok {
		vars["HOME"] = t.TempDir()
	}
	var out, errOut bytes.Buffer
	code = Execute(context.Background(), "0.1.0", args, func(k string) string { return vars[k] }, &out, &errOut)
	return code, out.String(), errOut.String()
}

// server answers every request with status and body. The returned func gives the last request.
func server(t *testing.T, status int, body string) (*httptest.Server, func() *http.Request) {
	t.Helper()
	var (
		mu   sync.Mutex
		last *http.Request
	)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		last = r.Clone(context.Background())
		mu.Unlock()
		w.WriteHeader(status)
		w.Write([]byte(body))
	}))
	t.Cleanup(srv.Close)
	return srv, func() *http.Request {
		mu.Lock()
		defer mu.Unlock()
		return last
	}
}

func TestAgentListPrintsTheServersJSON(t *testing.T) {
	srv, lastRequest := server(t, 200, `{"items":[{"id":"a1","name":"Support line"}],"total":1,"page":1,"page_size":20}`)
	code, stdout, stderr := run(t, map[string]string{"TRUMAN_URL": srv.URL, "TRUMAN_API_TOKEN": "t0k"},
		"agent", "list")

	if code != 0 || stderr != "" {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	want := "{\n  \"items\": [\n    {\n      \"id\": \"a1\",\n      \"name\": \"Support line\"\n    }\n  ],\n" +
		"  \"total\": 1,\n  \"page\": 1,\n  \"page_size\": 20\n}\n"
	if stdout != want {
		t.Fatalf("stdout = %q, want %q", stdout, want)
	}
	req := lastRequest()
	if req.URL.Path != "/api/v1/agents" || req.URL.RawQuery != "" {
		t.Fatalf("request = %s?%s, want /api/v1/agents with no query", req.URL.Path, req.URL.RawQuery)
	}
	if got := req.Header.Get("Authorization"); got != "Bearer t0k" {
		t.Fatalf("Authorization = %q", got)
	}
}

func TestAgentListSendsOnlyTheFlagsThatWereSet(t *testing.T) {
	srv, lastRequest := server(t, 200, `{"items":[],"total":0,"page":2,"page_size":5}`)
	code, _, stderr := run(t, map[string]string{"TRUMAN_URL": srv.URL},
		"agent", "list", "--external-id", "support-line", "--page", "2", "--page-size", "5")

	if code != 0 {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	if got := lastRequest().URL.Query().Encode(); got != "external_id=support-line&page=2&page_size=5" {
		t.Fatalf("query = %q", got)
	}
}

func TestErrorsSayTheNextStep(t *testing.T) {
	unauthorized, _ := server(t, 401, `{"error":{"code":"unauthorized","message":"missing or invalid bearer token"}}`)
	notFound, _ := server(t, 404, `{"error":{"code":"not_found","message":"agent 6f1c not found"}}`)
	stopped := httptest.NewServer(http.NotFoundHandler())
	stopped.Close()

	tests := []struct {
		name string
		vars map[string]string
		args []string
		want string
	}{
		{"no server", map[string]string{}, []string{"agent", "list"}, `no Truman server: run "truman auth login" or set TRUMAN_URL`},
		{"wrong token", map[string]string{"TRUMAN_URL": unauthorized.URL}, []string{"agent", "list"}, `the token is wrong: run "truman auth login" or set TRUMAN_API_TOKEN`},
		{"server message", map[string]string{"TRUMAN_URL": notFound.URL}, []string{"agent", "view", "6f1c2f1e-0000-4000-8000-000000000000"}, "404 Not Found: agent 6f1c not found"},
		{"server down", map[string]string{"TRUMAN_URL": stopped.URL}, []string{"agent", "list"}, "cannot reach " + stopped.URL},
		{"bad agent ID", map[string]string{"TRUMAN_URL": notFound.URL}, []string{"agent", "view", "support-line"}, `"support-line" is not an agent ID: find it with "truman agent list"`},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			code, stdout, stderr := run(t, tt.vars, tt.args...)
			if code != 1 || stdout != "" || !strings.Contains(stderr, tt.want) {
				t.Fatalf("code = %d, stdout = %q, stderr = %q; want 1 and %q", code, stdout, stderr, tt.want)
			}
		})
	}
}

func TestVersionShowsBothVersions(t *testing.T) {
	srv, lastRequest := server(t, 200, `{"status":"ok","version":"0.4.2"}`)
	code, stdout, _ := run(t, map[string]string{"TRUMAN_URL": srv.URL}, "version")

	if code != 0 || stdout != "{\n  \"cli\": \"0.1.0\",\n  \"server\": \"0.4.2\"\n}\n" {
		t.Fatalf("code = %d, stdout = %q", code, stdout)
	}
	if path := lastRequest().URL.Path; path != "/api/v1/health" {
		t.Fatalf("request path = %s", path)
	}
}
