package cmd

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksha/cli/internal/api"
	"github.com/plivo-labs/yaksha/cli/internal/wait"
)

// cancelTimeout bounds the cancel request that follows Ctrl-C or SIGTERM.
const cancelTimeout = 30 * time.Second

// judgeTimeout bounds the wait for the judges when no --timeout is set. They normally answer
// within a minute of a call's end. A stopped evaluator never does, and a failing judge model
// retries for longer than this before its evaluation fails.
const judgeTimeout = 10 * time.Minute

// withTimeout ends ctx with wait.ErrTimeout after d. With no d, only the parent ends it.
func withTimeout(ctx context.Context, d time.Duration) (context.Context, context.CancelFunc) {
	if d <= 0 {
		return context.WithCancel(ctx)
	}
	return context.WithTimeoutCause(ctx, d, wait.ErrTimeout)
}

// maxPageSize is the largest page the API serves.
const maxPageSize = 100

func (a *app) runCmd() *cobra.Command {
	run := &cobra.Command{
		Use:   "run",
		Short: "Runs: test calls of an agent's scenarios, started together",
	}
	run.AddCommand(a.runStartCmd(), a.runWaitCmd(), a.runViewCmd(), a.runMetricsCmd(), a.runListCmd(), a.runCancelCmd())
	return run
}

type runStartFlags struct {
	agent                                                                    string
	scenarios                                                                []string
	all, wait                                                                bool
	repeats, maxDurationS, maxTurns, maxParallel, startIntervalS, maxRetries int
	name, idempotencyKey                                                     string
	timeout                                                                  time.Duration
}

func (a *app) runStartCmd() *cobra.Command {
	var f runStartFlags
	cmd := &cobra.Command{
		Use:   "start --agent <id> (--scenario <id>... | --all)",
		Short: "Start a run; with --wait, wait for it and its verdicts, and fail unless every call completed and the judges passed every call",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return a.startRun(cmd, f)
		},
	}
	fl := cmd.Flags()
	fl.StringVar(&f.agent, "agent", "", "the agent's ID")
	fl.StringSliceVar(&f.scenarios, "scenario", nil, "a scenario's ID; repeat the flag or separate IDs with commas")
	fl.BoolVar(&f.all, "all", false, "every scenario of the agent")
	fl.IntVar(&f.repeats, "repeats", 0, "how many times each scenario runs")
	fl.IntVar(&f.maxDurationS, "max-duration-s", 0, "the time limit of each call, in seconds")
	fl.IntVar(&f.maxTurns, "max-turns", 0, "how many agent turns the caller answers")
	fl.IntVar(&f.maxParallel, "max-parallel", 0, "how many calls of the run can be on the line at once")
	fl.IntVar(&f.startIntervalS, "start-interval-s", 0, "the least time between two call starts, in seconds")
	fl.IntVar(&f.maxRetries, "max-retries", 0, "extra tries for a call that fails on Yaksha's side or on the line")
	fl.StringVar(&f.name, "name", "", "a name for the run")
	fl.StringVar(&f.idempotencyKey, "idempotency-key", "", "the same key and body return the first run instead of a new one")
	fl.BoolVar(&f.wait, "wait", false, "wait for the run to end and for its verdicts; Ctrl-C or SIGTERM then cancels a run that is still going")
	fl.DurationVar(&f.timeout, "timeout", 0, "with --wait, stop waiting after this long, for example 30m")
	cmd.MarkFlagRequired("agent")
	cmd.MarkFlagsOneRequired("scenario", "all")
	cmd.MarkFlagsMutuallyExclusive("scenario", "all")
	return cmd
}

func (a *app) startRun(cmd *cobra.Command, f runStartFlags) error {
	ctx := cmd.Context()
	agentID, err := parseID("agent", f.agent)
	if err != nil {
		return err
	}
	var scenarioIDs []uuid.UUID
	for _, s := range f.scenarios {
		id, err := parseID("scenario", s)
		if err != nil {
			return err
		}
		scenarioIDs = append(scenarioIDs, id)
	}
	c, err := a.client()
	if err != nil {
		return err
	}
	if f.all {
		if scenarioIDs, err = allScenarios(ctx, c, agentID); err != nil {
			return err
		}
	}
	body := api.RunCreate{
		AgentId:        agentID,
		Scenarios:      ownPersonas(scenarioIDs),
		Repeats:        changed(cmd, "repeats", f.repeats),
		MaxDurationS:   changed(cmd, "max-duration-s", f.maxDurationS),
		MaxTurns:       changed(cmd, "max-turns", f.maxTurns),
		MaxParallel:    changed(cmd, "max-parallel", f.maxParallel),
		StartIntervalS: changed(cmd, "start-interval-s", f.startIntervalS),
		MaxRetries:     changed(cmd, "max-retries", f.maxRetries),
		Name:           changed(cmd, "name", f.name),
	}
	params := api.CreateRunApiV1RunsPostParams{
		IdempotencyKey: changed(cmd, "idempotency-key", f.idempotencyKey),
	}
	// A stop during the POST must not lose the run: the server may already have created it. So
	// the request ignores the stop, and waitForRun then sees the stop and cancels the run.
	created, err := api.Body(c.CreateRunApiV1RunsPost(context.WithoutCancel(ctx), &params, body))
	if err != nil {
		return err
	}
	id, err := idOf(created)
	if err != nil {
		return err
	}
	if !f.wait {
		// The ID goes out first, so a failed write to stdout cannot lose the run.
		fmt.Fprintf(cmd.ErrOrStderr(), "next: yaksha run wait %s\n", id)
		return printJSON(cmd.OutOrStdout(), created)
	}
	fmt.Fprintf(cmd.ErrOrStderr(), "run %s started\n", id)
	return a.waitForRun(cmd, c, id, f.timeout, true)
}

// allScenarios lists every scenario of the agent, page by page.
func allScenarios(ctx context.Context, c *api.Client, agentID uuid.UUID) ([]uuid.UUID, error) {
	var ids []uuid.UUID
	seen := map[uuid.UUID]bool{}
	for page := 1; ; page++ {
		size := maxPageSize
		params := api.ListScenariosApiV1AgentsAgentIdScenariosGetParams{Page: &page, PageSize: &size}
		body, err := api.Body(c.ListScenariosApiV1AgentsAgentIdScenariosGet(ctx, agentID, &params))
		if err != nil {
			return nil, err
		}
		var list struct {
			Items []struct {
				ID uuid.UUID `json:"id"`
			} `json:"items"`
			Total int `json:"total"`
		}
		if err := json.Unmarshal(body, &list); err != nil {
			return nil, fmt.Errorf("read the agent's scenarios: %w", err)
		}
		for _, s := range list.Items {
			if !seen[s.ID] {
				seen[s.ID] = true
				ids = append(ids, s.ID)
			}
		}
		if len(list.Items) == 0 || page*maxPageSize >= list.Total {
			break
		}
	}
	if len(ids) == 0 {
		return nil, &nextStep{"agent " + agentID.String() + " has no scenarios", "add scenarios in the console"}
	}
	return ids, nil
}

// waitForRun waits for the run to end and for the judges' verdicts, prints the run as it is then,
// and fails unless every call completed and the judges passed every call. When the wait for the
// judges ends early, it prints the ended run before the error. One timeout covers both waits;
// without one, the judges get judgeTimeout. With cancelOnStop, Ctrl-C or SIGTERM cancels a run
// that is still going.
func (a *app) waitForRun(cmd *cobra.Command, c *api.Client, id uuid.UUID, timeout time.Duration, cancelOnStop bool) error {
	ctx, cancel := withTimeout(cmd.Context(), timeout)
	defer cancel()
	stderr := cmd.ErrOrStderr()
	opts := wait.Options{Interval: a.pollInterval, Progress: stderr, Live: isTerminal(stderr)}
	again := "yaksha run wait " + id.String()
	r, err := wait.Run(ctx, c, id, opts)
	switch {
	case errors.Is(err, wait.ErrTimeout):
		what := fmt.Sprintf("run %s did not end within %s", id, timeout)
		if r.Run.Status != "" {
			what += "; it is " + r.Progress()
		}
		return &nextStep{what, again}
	case errors.Is(err, context.Canceled) && cancelOnStop:
		return cancelAfterStop(cmd.Context(), c, id)
	case errors.Is(err, context.Canceled):
		return &nextStep{"stopped waiting; the run goes on", again}
	case err != nil:
		return &nextStep{fmt.Sprintf("could not read run %s (%s); the run goes on", id, describe(err)), again}
	}
	var v wait.Verdicts
	if r.Passed() {
		limit := timeout
		if limit <= 0 {
			limit = judgeTimeout
		}
		judging, stop := withTimeout(ctx, limit)
		defer stop()
		v, err = wait.RunVerdicts(judging, c, id, opts)
		if err == nil {
			// The evaluator computes the run's response times with the verdicts.
			var judged wait.Result
			if judged, err = wait.Run(judging, c, id, opts); err == nil {
				r = judged
			}
		}
		if err != nil {
			if err := printJSON(cmd.OutOrStdout(), r.Body); err != nil {
				return err
			}
		}
		switch {
		case errors.Is(err, wait.ErrTimeout):
			return &nextStep{fmt.Sprintf("run %s ended, but the judges were not done before the %s time limit", id, limit), again}
		case errors.Is(err, context.Canceled):
			return &nextStep{"stopped waiting for the judges; the run has ended", again}
		case err != nil:
			return &nextStep{fmt.Sprintf("could not read run %s or its verdicts (%s)", id, describe(err)), again}
		}
	}
	if err := printJSON(cmd.OutOrStdout(), r.Body); err != nil {
		return err
	}
	summary := r.Summary()
	if s := v.Summary(); s != "" {
		summary += "; " + s
	}
	switch {
	case !r.Passed():
		return &failure{nextStep{summary, fmt.Sprintf(
			"yaksha conversation list --run %s --latest-attempts --group error,did_not_connect", id)}}
	case !v.Passed():
		return &failure{nextStep{summary, "yaksha run metrics " + id.String()}}
	}
	fmt.Fprintln(stderr, summary)
	return nil
}

// cancelAfterStop cancels a run whose wait Ctrl-C or SIGTERM stopped, so that no paid calls go
// on. ctx is done by then, so the request gets its own time limit.
func cancelAfterStop(ctx context.Context, c *api.Client, id uuid.UUID) error {
	ctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), cancelTimeout)
	defer cancel()
	if _, err := api.Body(c.CancelRunApiV1RunsRunIdCancelPost(ctx, id)); err != nil {
		return &nextStep{fmt.Sprintf("stopped, but could not cancel run %s: %v", id, err),
			"yaksha run cancel " + id.String()}
	}
	return &nextStep{fmt.Sprintf("stopped: run %s is cancelled, and its calls on the line are ending", id),
		"yaksha run view " + id.String()}
}

func (a *app) runWaitCmd() *cobra.Command {
	var timeout time.Duration
	cmd := &cobra.Command{
		Use:   "wait <id>",
		Short: "Wait for a run to end and for its verdicts; fail unless every call completed and the judges passed every call. Stopping it leaves the run alone",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("run", args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			return a.waitForRun(cmd, c, id, timeout, false)
		},
	}
	cmd.Flags().DurationVar(&timeout, "timeout", 0, "stop waiting after this long, for example 8m; the run goes on")
	return cmd
}

func (a *app) runViewCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "view <id>",
		Short: "Show a run: its status, counts and settings",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("run", args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.GetRunApiV1RunsRunIdGet(cmd.Context(), id))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
}

func (a *app) runMetricsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "metrics <id>",
		Short: "Show a run's verdicts and metrics: pass rate, coverage, pass^2, each scenario's calls, and each criterion's counts",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("run", args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.GetRunMetricsApiV1RunsRunIdMetricsGet(cmd.Context(), id))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
}

func (a *app) runListCmd() *cobra.Command {
	var (
		agent, status  string
		from, before   time.Time
		page, pageSize int
	)
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List runs, newest first",
		Example: `  yaksha run list --from 2026-10-01 --before 2026-10-02
  yaksha run list --from 2026-10-01T09:00:00+05:30`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			params := api.ListRunsApiV1RunsGetParams{
				Status:        changed(cmd, "status", api.RunStatus(status)),
				CreatedFrom:   changed(cmd, "from", from),
				CreatedBefore: changed(cmd, "before", before),
				Page:          changed(cmd, "page", page),
				PageSize:      changed(cmd, "page-size", pageSize),
			}
			if cmd.Flags().Changed("agent") {
				id, err := parseID("agent", agent)
				if err != nil {
					return err
				}
				params.AgentId = &id
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.ListRunsApiV1RunsGet(cmd.Context(), &params))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
	cmd.Flags().StringVar(&agent, "agent", "", "only the runs of this agent")
	cmd.Flags().StringVar(&status, "status", "", "only the runs with this status: queued, running, cancelling, done or cancelled")
	cmd.Flags().Var(timeFlag{&from}, "from", "only the runs created at or after this time; a date alone is local midnight")
	cmd.Flags().Var(timeFlag{&before}, "before", "only the runs created before this time; a date alone is local midnight")
	addPageFlags(cmd, &page, &pageSize)
	return cmd
}

func (a *app) runCancelCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "cancel <id>",
		Short: "Cancel a run and wait until its calls on the line have ended",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("run", args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			if _, err := api.Body(c.CancelRunApiV1RunsRunIdCancelPost(cmd.Context(), id)); err != nil {
				return err
			}
			stderr := cmd.ErrOrStderr()
			r, err := wait.Run(cmd.Context(), c, id, wait.Options{
				Interval: a.pollInterval, Progress: stderr, Live: isTerminal(stderr),
			})
			switch {
			case errors.Is(err, context.Canceled):
				return &nextStep{"stopped waiting; the cancel was sent", "yaksha run cancel " + id.String()}
			case err != nil:
				return &nextStep{fmt.Sprintf("could not read run %s (%s); the cancel was sent", id, describe(err)),
					"yaksha run cancel " + id.String()}
			}
			if err := printJSON(cmd.OutOrStdout(), r.Body); err != nil {
				return err
			}
			fmt.Fprintln(stderr, r.Summary())
			return nil
		},
	}
}

// ownPersonas runs each scenario with its own persona.
func ownPersonas(ids []uuid.UUID) []api.RunScenario {
	scenarios := make([]api.RunScenario, len(ids))
	for i, id := range ids {
		scenarios[i] = api.RunScenario{ScenarioId: id}
	}
	return scenarios
}
