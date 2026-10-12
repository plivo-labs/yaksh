package wait

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/plivo-labs/yaksh/cli/internal/api"
)

var runID = uuid.MustParse("7c1e2a0b-0000-4000-8000-000000000001")

func runJSON(status, counts string) string {
	return fmt.Sprintf(`{"id":"%s","status":"%s","counts":{%s},"waiting_reason":null}`, runID, status, counts)
}

// runs answers GET /api/v1/runs/{id} with each body in turn, then repeats the last one.
func runs(t *testing.T, bodies ...string) *api.Client {
	t.Helper()
	var (
		mu sync.Mutex
		n  int
	)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		body := bodies[min(n, len(bodies)-1)]
		n++
		mu.Unlock()
		w.Write([]byte(body))
	}))
	t.Cleanup(srv.Close)
	c, err := api.New(srv.URL, "t", "test")
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestRunWaitsUntilTheRunEnds(t *testing.T) {
	c := runs(t,
		runJSON("queued", `"waiting":2`),
		runJSON("running", `"completed":1,"waiting":1`),
		runJSON("running", `"completed":1,"waiting":1`),
		runJSON("done", `"completed":2`),
	)
	var progress bytes.Buffer

	r, err := Run(context.Background(), c, runID, Options{Interval: time.Millisecond, Progress: &progress})

	if err != nil || !r.Passed() || !strings.Contains(string(r.Body), `"status":"done"`) {
		t.Fatalf("Run = %+v, %v", r.Run, err)
	}
	want := "queued: 2 waiting\nrunning: 1 completed, 1 waiting\n"
	if progress.String() != want {
		t.Fatalf("progress = %q, want %q (one line per change)", progress.String(), want)
	}
}

func TestRunStopsAtTheTimeoutWithTheLastRead(t *testing.T) {
	c := runs(t, runJSON("running", `"in_progress":1`))

	ctx, cancel := context.WithTimeoutCause(context.Background(), 20*time.Millisecond, ErrTimeout)
	defer cancel()
	r, err := Run(ctx, c, runID, Options{Interval: time.Millisecond})

	if !errors.Is(err, ErrTimeout) || r.Run.Status != api.RunStatusRunning {
		t.Fatalf("Run = %+v, %v; want the running run and ErrTimeout", r.Run, err)
	}
}

func TestResultPassedAndSummary(t *testing.T) {
	start := time.Date(2026, 10, 4, 9, 0, 0, 0, time.UTC)
	end := start.Add(2*time.Minute + 41*time.Second)
	tests := []struct {
		name    string
		run     api.RunRead
		passed  bool
		summary string
	}{
		{
			name:    "every call completed",
			run:     api.RunRead{Id: runID, Status: api.RunStatusDone, Counts: map[string]int{"completed": 4, "error": 0}, StartedAt: &start, EndedAt: &end},
			passed:  true,
			summary: "run " + runID.String() + " done: 4 of 4 calls completed (2m41s)",
		},
		{
			name:    "cancelled",
			run:     api.RunRead{Id: runID, Status: api.RunStatusCancelled, Counts: map[string]int{"completed": 1, "cancelled": 1}},
			summary: "run " + runID.String() + " cancelled: 1 of 2 calls completed, 1 cancelled",
		},
		{
			name:    "no calls",
			run:     api.RunRead{Id: runID, Status: api.RunStatusDone, Counts: map[string]int{}},
			summary: "run " + runID.String() + " done: 0 of 0 calls completed",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := Result{Run: tt.run}
			if r.Passed() != tt.passed || r.Summary() != tt.summary {
				t.Fatalf("Passed = %v, Summary = %q; want %v, %q", r.Passed(), r.Summary(), tt.passed, tt.summary)
			}
		})
	}
}
