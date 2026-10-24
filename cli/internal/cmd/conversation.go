package cmd

import (
	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksh/cli/internal/api"
)

func (a *app) conversationCmd() *cobra.Command {
	conversation := &cobra.Command{
		Use:   "conversation",
		Short: "Conversations: the calls of runs",
	}
	conversation.AddCommand(
		a.conversationViewCmd(),
		a.conversationEvaluationCmd(),
		a.conversationRecordCmd(),
		a.conversationListCmd(),
	)
	return conversation
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

func (a *app) conversationRecordCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "record <id>",
		Short: "Show the agent's own record of a call: the values it saved, what it heard and said, and its tool calls",
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
			body, err := api.Body(c.GetAgentRecordApiV1ConversationsConversationIdAgentRecordGet(cmd.Context(), id))
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
