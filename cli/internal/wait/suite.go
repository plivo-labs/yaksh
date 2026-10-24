package wait

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/plivo-labs/yaksh/cli/internal/api"
)

// SuiteResult is a suite run as the server last sent it. The server computes its result, so the
// CLI only reads it.
type SuiteResult struct {
	// Body is the server's JSON, to print as it is.
	Body     []byte
	SuiteRun api.SuiteRunRead
}

// Final reports whether the result can no longer change: every run has ended and the judges
// are done.
func (r SuiteResult) Final() bool {
	return r.SuiteRun.Result != api.RunResultRunning && r.SuiteRun.Result != api.RunResultJudging
}

// Stopped reports whether every run has ended; the judges can still be at work.
func (r SuiteResult) Stopped() bool {
	return r.SuiteRun.Result != api.RunResultRunning
}

// Passed reports whether the suite run passed.
func (r SuiteResult) Passed() bool {
	return r.SuiteRun.Result == api.RunResultPassed
}

// Summary is one line about the suite run, for example
// "suite run 7c1e… of Release check failed: 3 of 5 runs passed (36m2s)".
func (r SuiteResult) Summary() string {
	s := r.SuiteRun
	line := fmt.Sprintf("suite run %s of %s %s: %d of %d runs passed", s.Id, s.SuiteName,
		strings.ReplaceAll(string(s.Result), "_", " "), s.PassedRunCount, s.RunCount)
	if s.EndedAt != nil {
		line += fmt.Sprintf(" (%s)", s.EndedAt.Sub(s.CreatedAt).Round(time.Second))
	}
	return line
}

// Progress is one line about a suite run that is not final, for example
// "running: 2 passed, 1 judging, 2 running".
func (r SuiteResult) Progress() string {
	counts := map[string]int{}
	for _, part := range r.SuiteRun.Runs {
		counts[string(part.Result)]++
	}
	var parts []string
	for _, result := range []api.RunResult{api.RunResultPassed, api.RunResultFailed,
		api.RunResultNotDecided, api.RunResultCancelled, api.RunResultJudging, api.RunResultRunning} {
		if n := counts[string(result)]; n > 0 {
			parts = append(parts, fmt.Sprintf("%d %s", n, strings.ReplaceAll(string(result), "_", " ")))
		}
	}
	return fmt.Sprintf("%s: %s", r.SuiteRun.Result, strings.Join(parts, ", "))
}

// Suite reads the suite run every Interval until done accepts it or ctx is done. When it stops
// early it returns the last read with the cause of ctx. Stopping the wait never touches the
// suite run.
func Suite(ctx context.Context, c *api.Client, id uuid.UUID, opts Options,
	done func(SuiteResult) bool) (SuiteResult, error) {
	return poll(ctx, opts, func(ctx context.Context) (SuiteResult, error) {
		body, err := api.Body(c.GetSuiteRunApiV1SuiteRunsSuiteRunIdGet(ctx, id))
		if err != nil {
			return SuiteResult{}, err
		}
		var suiteRun api.SuiteRunRead
		if err := json.Unmarshal(body, &suiteRun); err != nil {
			return SuiteResult{}, fmt.Errorf("read suite run %s: %w", id, err)
		}
		return SuiteResult{Body: body, SuiteRun: suiteRun}, nil
	}, done, SuiteResult.Progress)
}
