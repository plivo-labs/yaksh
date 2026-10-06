package cmd

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"time"

	"github.com/google/uuid"
	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksha/cli/internal/api"
	"github.com/plivo-labs/yaksha/cli/internal/wait"
)

func (a *app) conversationCmd() *cobra.Command {
	conversation := &cobra.Command{
		Use:   "conversation",
		Short: "Conversations: single test calls, and the calls of runs",
	}
	conversation.AddCommand(a.conversationStartCmd(), a.conversationViewCmd(), a.conversationEvaluationCmd(), a.conversationListCmd())
	return conversation
}

func (a *app) conversationStartCmd() *cobra.Command {
	var (
		agent, scenario, persona, noiseSound, noiseLevel string
		maxDurationS, maxTurns                           int
		follow                                           bool
		timeout                                          time.Duration
	)
	cmd := &cobra.Command{
		Use:   "start --agent <id> --scenario <id>",
		Short: "Start one test call; with --wait, print each event as it happens",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			agentID, err := parseID("agent", agent)
			if err != nil {
				return err
			}
			scenarioID, err := parseID("scenario", scenario)
			if err != nil {
				return err
			}
			body := api.ConversationCreate{
				AgentId:         agentID,
				ScenarioId:      scenarioID,
				MaxDurationS:    changed(cmd, "max-duration-s", maxDurationS),
				MaxTurns:        changed(cmd, "max-turns", maxTurns),
				BackgroundNoise: noise(cmd, noiseSound, noiseLevel),
			}
			if cmd.Flags().Changed("persona") {
				id, err := parseID("persona", persona)
				if err != nil {
					return err
				}
				body.PersonaId = &id
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			// A stop during the POST must not lose the call: the server may already have started
			// it. So the request ignores the stop, and the ID is printed before anything else.
			created, err := api.Body(c.CreateConversationApiV1ConversationsPost(context.WithoutCancel(cmd.Context()), body))
			if err != nil {
				return err
			}
			id, err := idOf(created)
			if err != nil {
				return err
			}
			if !follow {
				// The ID goes out first, so a failed write to stdout cannot lose the call.
				fmt.Fprintf(cmd.ErrOrStderr(), "next: yaksha conversation view %s\n", id)
				return printJSON(cmd.OutOrStdout(), created)
			}
			fmt.Fprintf(cmd.ErrOrStderr(), "conversation %s started\n", id)
			return a.followConversation(cmd.Context(), c, id, timeout, cmd.OutOrStdout(), cmd.ErrOrStderr())
		},
	}
	fl := cmd.Flags()
	fl.StringVar(&agent, "agent", "", "the agent's ID")
	fl.StringVar(&scenario, "scenario", "", "the scenario's ID")
	fl.StringVar(&persona, "persona", "", "a persona to use instead of the scenario's own")
	fl.IntVar(&maxDurationS, "max-duration-s", 0, "the time limit of the call, in seconds")
	fl.IntVar(&maxTurns, "max-turns", 0, "how many agent turns the caller answers")
	fl.StringVar(&noiseSound, "noise-sound", "", "background noise, for example cafe; none turns it off")
	fl.StringVar(&noiseLevel, "noise-level", "", "the noise level: light, busy or loud")
	fl.BoolVar(&follow, "wait", false, "print each event as one JSON line as it happens, then the conversation, then the evaluation of a completed call")
	fl.DurationVar(&timeout, "timeout", 0, "with --wait, stop waiting after this long, for example 8m; the call goes on")
	cmd.MarkFlagRequired("agent")
	cmd.MarkFlagRequired("scenario")
	return cmd
}

// followConversation prints the call's events as JSON lines until the call ends, then the
// conversation itself, then its evaluation once the judges are done. It fails unless the call
// completed and the judges passed it or are off. One timeout covers both waits; without one, the
// judges get judgeTimeout. Stopping it leaves the call alone.
func (a *app) followConversation(ctx context.Context, c *api.Client, id uuid.UUID, timeout time.Duration, stdout, stderr io.Writer) error {
	ctx, cancel := withTimeout(ctx, timeout)
	defer cancel()
	view := "yaksha conversation view " + id.String()
	err := wait.Conversation(ctx, c, id, func(e wait.Event) error {
		return writeLine(stdout, e)
	})
	switch {
	case errors.Is(err, wait.ErrTimeout):
		return &nextStep{fmt.Sprintf("the call did not end within %s; it goes on", timeout), view}
	case errors.Is(err, context.Canceled):
		return &nextStep{"stopped following; the call goes on", view}
	case err != nil:
		return &nextStep{fmt.Sprintf("the event stream broke (%v); the call goes on", describe(err)), view}
	}
	body, err := api.Body(c.GetConversationApiV1ConversationsConversationIdGet(ctx, id))
	if err != nil {
		return &nextStep{fmt.Sprintf("could not read conversation %s (%s)", id, describe(err)), view}
	}
	if err := writeLine(stdout, wait.Event{Name: "conversation", Data: body}); err != nil {
		return err
	}
	var outcome struct {
		Status    api.ConversationStatus `json:"status"`
		EndReason *api.EndReason         `json:"end_reason"`
	}
	if err := json.Unmarshal(body, &outcome); err != nil {
		return fmt.Errorf("read the conversation's outcome: %w", err)
	}
	switch outcome.Status {
	case api.ConversationStatusQueued, api.ConversationStatusRunning, api.ConversationStatusEnding:
		return &nextStep{fmt.Sprintf("the event stream ended before the call; the call is %s", outcome.Status), view}
	}
	what := fmt.Sprintf("conversation %s %s", id, outcome.Status)
	stopped := outcome.EndReason != nil && *outcome.EndReason == api.EndReasonUserRequest
	if outcome.EndReason != nil {
		what += ", " + string(*outcome.EndReason)
	}
	// The judges skip a call that someone stopped, and a run counts it as cancelled.
	if outcome.Status != api.ConversationStatusCompleted || stopped {
		return &failure{nextStep{what, view}}
	}
	evaluation := "yaksha conversation evaluation " + id.String()
	limit := timeout
	if limit <= 0 {
		limit = judgeTimeout
	}
	judging, stop := withTimeout(ctx, limit)
	defer stop()
	e, err := wait.CallEvaluation(judging, c, id, wait.Options{
		Interval: a.pollInterval, Progress: stderr, Live: isTerminal(stderr),
	})
	switch {
	case errors.Is(err, wait.ErrTimeout):
		return &nextStep{fmt.Sprintf("%s; the judges were not done before the %s time limit", what, limit), evaluation}
	case errors.Is(err, context.Canceled):
		return &nextStep{what + "; stopped waiting for the judges", evaluation}
	case err != nil:
		return &nextStep{fmt.Sprintf("%s; could not read the evaluation (%s)", what, describe(err)), evaluation}
	}
	if e.Result.Evaluation != nil {
		if err := writeLine(stdout, wait.Event{Name: "evaluation", Data: e.Body}); err != nil {
			return err
		}
	}
	if s := e.Summary(); s != "" {
		what += "; " + s
	}
	if !e.Passed() {
		return &failure{nextStep{what, evaluation}}
	}
	fmt.Fprintln(stderr, what)
	return nil
}

// writeLine writes v as one line of JSON.
func writeLine(w io.Writer, v any) error {
	line, err := json.Marshal(v)
	if err != nil {
		return err
	}
	_, err = w.Write(append(line, '\n'))
	return err
}

func (a *app) conversationViewCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "view <id>",
		Short: "Show a conversation: its outcome, transcript and wire events",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("conversation", args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.GetConversationApiV1ConversationsConversationIdGet(cmd.Context(), id))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
}

func (a *app) conversationEvaluationCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "evaluation <id>",
		Short: "Show what the judges decided about a call: its verdicts, and each criterion and rule with its quotes and reasoning",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("conversation", args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.GetEvaluationApiV1ConversationsConversationIdEvaluationGet(cmd.Context(), id))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
}

func (a *app) conversationListCmd() *cobra.Command {
	var (
		agent, run, status, q, sort string
		groups                      []string
		latestAttempts              bool
		page, pageSize              int
	)
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List conversations, newest first",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			params := api.ListConversationsApiV1ConversationsGetParams{
				Status:         changed(cmd, "status", api.ConversationStatus(status)),
				LatestAttempts: changed(cmd, "latest-attempts", latestAttempts),
				Q:              changed(cmd, "q", q),
				Sort:           changed(cmd, "sort", sort),
				Page:           changed(cmd, "page", page),
				PageSize:       changed(cmd, "page-size", pageSize),
			}
			if cmd.Flags().Changed("agent") {
				id, err := parseID("agent", agent)
				if err != nil {
					return err
				}
				params.AgentId = &id
			}
			if cmd.Flags().Changed("run") {
				id, err := parseID("run", run)
				if err != nil {
					return err
				}
				params.RunId = &id
			}
			if len(groups) > 0 {
				outcomes := make([]api.OutcomeGroup, len(groups))
				for i, g := range groups {
					outcomes[i] = api.OutcomeGroup(g)
				}
				params.Group = &outcomes
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.ListConversationsApiV1ConversationsGet(cmd.Context(), &params))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
	fl := cmd.Flags()
	fl.StringVar(&agent, "agent", "", "only this agent's conversations")
	fl.StringVar(&run, "run", "", "only this run's conversations")
	fl.StringVar(&status, "status", "", "only conversations with this status")
	fl.StringSliceVar(&groups, "group", nil, "only these outcome groups, for example error,did_not_connect")
	fl.BoolVar(&latestAttempts, "latest-attempts", false, "leave out the attempts that a retry replaced")
	fl.StringVar(&q, "q", "", "search the agent, scenario or persona name, or the ID")
	fl.StringVar(&sort, "sort", "", "created_at, talk_ms or response_p90_ms; a leading - sorts descending")
	addPageFlags(cmd, &page, &pageSize)
	return cmd
}
