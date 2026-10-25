package cmd

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksh/cli/internal/api"
	"github.com/plivo-labs/yaksh/cli/internal/wait"
)

func (a *app) suiteCmd() *cobra.Command {
	suite := &cobra.Command{
		Use:   "suite",
		Short: "Suites: saved lists of runs that start together and get one result, for CI",
	}
	suite.AddCommand(a.suiteListCmd(), a.suiteRunCmd(), a.suiteWaitCmd())
	return suite
}

func (a *app) suiteListCmd() *cobra.Command {
	var page, pageSize int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List suites by name, each with its last suite run",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := a.client()
			if err != nil {
				return err
			}
			params := api.ListSuitesApiV1SuitesGetParams{
				Page:     changed(cmd, "page", page),
				PageSize: changed(cmd, "page-size", pageSize),
			}
			body, err := api.Body(c.ListSuitesApiV1SuitesGet(cmd.Context(), &params))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
	addPageFlags(cmd, &page, &pageSize)
	return cmd
}

func (a *app) suiteRunCmd() *cobra.Command {
	var (
		waitFlag       bool
		idempotencyKey string
		timeout        time.Duration
	)
	cmd := &cobra.Command{
		Use:   "run <suite-id>",
		Short: "Start one run for each agent of a suite; with --wait, wait for the result and fail unless the suite run passed",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			suiteID, err := parseID("suite", args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			params := api.StartSuiteApiV1SuitesSuiteIdRunsPostParams{
				IdempotencyKey: changed(cmd, "idempotency-key", idempotencyKey),
			}
			// As for a run: a stop during the POST must not lose the suite run.
			started, err := api.Body(c.StartSuiteApiV1SuitesSuiteIdRunsPost(context.WithoutCancel(cmd.Context()), suiteID, &params))
			if err != nil {
				return err
			}
			id, err := idOf(started)
			if err != nil {
				return err
			}
			if !waitFlag {
				fmt.Fprintf(cmd.ErrOrStderr(), "next: yaksh suite wait %s\n", id)
				return printJSON(cmd.OutOrStdout(), started)
			}
			fmt.Fprintf(cmd.ErrOrStderr(), "suite run %s started\n", id)
			return a.waitForSuite(cmd, c, id, timeout, true)
		},
	}
	fl := cmd.Flags()
	fl.BoolVar(&waitFlag, "wait", false, "wait for every run to end and for its verdicts; Ctrl-C or SIGTERM then cancels a suite run that is still going")
	fl.StringVar(&idempotencyKey, "idempotency-key", "", "the same key for the same suite returns the first suite run instead of a new one")
	fl.DurationVar(&timeout, "timeout", 0, "with --wait, stop waiting after this long, for example 1h")
	return cmd
}

func (a *app) suiteWaitCmd() *cobra.Command {
	var timeout time.Duration
	cmd := &cobra.Command{
		Use:   "wait <suite-run-id>",
		Short: "Wait for a suite run's result; fail unless it passed. Stopping it leaves the suite run alone",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("suite run", args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			return a.waitForSuite(cmd, c, id, timeout, false)
		},
	}
	cmd.Flags().DurationVar(&timeout, "timeout", 0, "stop waiting after this long, for example 1h; the suite run goes on")
	return cmd
}

// waitForSuite waits until every run of the suite run has ended and its judges are done, prints
// the suite run as it is then, and fails unless it passed. One timeout covers both waits;
// without one, the judges get judgeTimeout. With cancelOnStop, Ctrl-C or SIGTERM cancels a suite
// run whose calls are still going.
func (a *app) waitForSuite(cmd *cobra.Command, c *api.Client, id uuid.UUID, timeout time.Duration, cancelOnStop bool) error {
	ctx, cancel := withTimeout(cmd.Context(), timeout)
	defer cancel()
	stderr := cmd.ErrOrStderr()
	opts := wait.Options{Interval: a.pollInterval, Progress: stderr, Live: isTerminal(stderr)}
	again := "yaksh suite wait " + id.String()
	r, err := wait.Suite(ctx, c, id, opts, wait.SuiteResult.Stopped)
	switch {
	case errors.Is(err, wait.ErrTimeout):
		what := fmt.Sprintf("suite run %s did not end within %s", id, timeout)
		if r.SuiteRun.Result != "" {
			what += "; it is " + r.Progress()
		}
		return &nextStep{what, again}
	case errors.Is(err, context.Canceled) && cancelOnStop:
		return cancelSuiteAfterStop(cmd.Context(), c, id)
	case errors.Is(err, context.Canceled):
		return &nextStep{"stopped waiting; the suite run goes on", again}
	case err != nil:
		return &nextStep{fmt.Sprintf("could not read suite run %s (%s); it goes on", id, describe(err)), again}
	}
	if !r.Final() {
		limit := timeout
		if limit <= 0 {
			limit = judgeTimeout
		}
		judging, stop := withTimeout(ctx, limit)
		defer stop()
		judged, err := wait.Suite(judging, c, id, opts, wait.SuiteResult.Final)
		if judged.Body != nil {
			r = judged
		}
		if err != nil {
			// As for a run: the results so far still reach stdout.
			if err := printJSON(cmd.OutOrStdout(), r.Body); err != nil {
				return err
			}
		}
		switch {
		case errors.Is(err, wait.ErrTimeout):
			return &nextStep{fmt.Sprintf("suite run %s ended, but the judges were not done before the %s time limit", id, limit), again}
		case errors.Is(err, context.Canceled):
			return &nextStep{"stopped waiting for the judges; every run has ended", again}
		case err != nil:
			return &nextStep{fmt.Sprintf("could not read suite run %s (%s)", id, describe(err)), again}
		}
	}
	if err := printJSON(cmd.OutOrStdout(), r.Body); err != nil {
		return err
	}
	if !r.Passed() {
		return &failure{nextStep{r.Summary(), suiteNext(r.SuiteRun, again)}}
	}
	fmt.Fprintln(stderr, r.Summary())
	return nil
}

// suiteNext names what shows why a suite run did not pass, for the first run whose result is
// the suite run's: its calls that did not complete when it has any, else its verdicts.
func suiteNext(s api.SuiteRunRead, again string) string {
	for _, part := range s.Runs {
		if part.Result != s.Result {
			continue
		}
		id := part.Run.Id.String()
		if part.Run.Counts["did_not_connect"]+part.Run.Counts["error"] > 0 {
			return notCompleted(id)
		}
		return "yaksh run metrics " + id
	}
	return again
}

// cancelSuiteAfterStop cancels a suite run whose wait Ctrl-C or SIGTERM stopped, so that no paid
// calls go on.
func cancelSuiteAfterStop(ctx context.Context, c *api.Client, id uuid.UUID) error {
	ctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), cancelTimeout)
	defer cancel()
	if _, err := api.Body(c.CancelSuiteRunApiV1SuiteRunsSuiteRunIdCancelPost(ctx, id)); err != nil {
		return &nextStep{fmt.Sprintf("stopped, but could not cancel suite run %s: %v", id, err),
			"cancel it on its page in the console"}
	}
	return &nextStep{fmt.Sprintf("stopped: suite run %s is cancelled, and its calls on the line are ending", id),
		"yaksh suite wait " + id.String()}
}
