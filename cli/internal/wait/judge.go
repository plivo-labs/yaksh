package wait

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/plivo-labs/yaksh/cli/internal/api"
)

// Verdicts is a run's metrics as the server last sent them.
type Verdicts struct {
	// Body is the server's JSON, to print as it is.
	Body    []byte
	Metrics api.RunMetrics
}

// RunVerdicts reads the run's metrics every Interval until no verdict is pending. The evaluator
// service judges each completed call after it ends; while it does not run, every call stays
// pending. It stops early the same way as Run.
func RunVerdicts(ctx context.Context, c *api.Client, id uuid.UUID, opts Options) (Verdicts, error) {
	read := func(ctx context.Context) (Verdicts, error) {
		body, err := api.Body(c.GetRunMetricsApiV1RunsRunIdMetricsGet(ctx, id))
		if err != nil {
			return Verdicts{}, err
		}
		var m api.RunMetrics
		if err := json.Unmarshal(body, &m); err != nil {
			return Verdicts{}, fmt.Errorf("read the metrics of run %s: %w", id, err)
		}
		return Verdicts{Body: body, Metrics: m}, nil
	}
	return poll(ctx, opts, read,
		func(v Verdicts) bool { return v.Metrics.Verdicts.Pending == 0 },
		func(v Verdicts) string { return fmt.Sprintf("judging: %d calls pending", v.Metrics.Verdicts.Pending) })
}

// verdicts lists the verdict of each judged call after people's labels: the scenario verdict of
// a call where the persona talked, and the verdict with agent rules of a call that only its
// voicemail or call screener answered.
func (v Verdicts) verdicts() []*api.Verdict {
	var found []*api.Verdict
	for _, scenario := range v.Metrics.Verdicts.Scenarios {
		for _, call := range scenario.Calls {
			found = append(found, call.Verdict)
		}
	}
	for _, call := range v.Metrics.Verdicts.Unplayed {
		found = append(found, call.Verdict)
	}
	return found
}

// Passed reports whether the judges passed every judged call. A call they did not score, or
// whose evaluation failed, proves nothing, so it does not pass. With the judges off, no call is
// judged.
func (v Verdicts) Passed() bool {
	for _, verdict := range v.verdicts() {
		if verdict == nil || *verdict != api.VerdictPass {
			return false
		}
	}
	return true
}

// Summary says how the judged calls came out, such as "judges: 3 pass, 1 fail", or that the
// judges are off. It is empty when no call was evaluated.
func (v Verdicts) Summary() string {
	counts := map[string]int{}
	for _, verdict := range v.verdicts() {
		counts[verdictName(verdict)]++
	}
	var parts []string
	for _, name := range []string{"pass", "fail", "not scored", "evaluation failed"} {
		if n := counts[name]; n > 0 {
			parts = append(parts, fmt.Sprintf("%d %s", n, name))
		}
	}
	if len(parts) == 0 {
		if n := v.Metrics.Verdicts.NotJudged; n > 0 {
			return fmt.Sprintf("judges: off, %d calls not judged", n)
		}
		return ""
	}
	return "judges: " + strings.Join(parts, ", ")
}

// verdictName names a judged call's verdict. A judged call without one is a call whose
// evaluation failed.
func verdictName(verdict *api.Verdict) string {
	if verdict == nil {
		return "evaluation failed"
	}
	return strings.ReplaceAll(string(*verdict), "_", " ")
}
