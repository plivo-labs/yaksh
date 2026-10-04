package cmd

import (
	"github.com/spf13/cobra"

	"github.com/plivo-labs/truman/cli/internal/api"
)

func (a *app) agentCmd() *cobra.Command {
	agent := &cobra.Command{
		Use:   "agent",
		Short: "The voice agents that Truman tests",
	}
	agent.AddCommand(a.agentListCmd(), a.agentViewCmd())
	return agent
}

func (a *app) agentListCmd() *cobra.Command {
	var (
		externalID, q, sort, direction string
		page, pageSize                 int
	)
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List agents, newest first",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := a.client()
			if err != nil {
				return err
			}
			params := api.ListAgentsApiV1AgentsGetParams{
				ExternalId: changed(cmd, "external-id", externalID),
				Direction:  changed(cmd, "direction", api.Direction(direction)),
				Q:          changed(cmd, "q", q),
				Sort:       changed(cmd, "sort", sort),
				Page:       changed(cmd, "page", page),
				PageSize:   changed(cmd, "page-size", pageSize),
			}
			body, err := api.Body(c.ListAgentsApiV1AgentsGet(cmd.Context(), &params))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
	f := cmd.Flags()
	f.StringVar(&externalID, "external-id", "", "only the agent with this external ID")
	f.StringVar(&direction, "direction", "", "only inbound or outbound agents")
	f.StringVar(&q, "q", "", "search the name, external ID, ID or number")
	f.StringVar(&sort, "sort", "", "name, language, created_at or updated_at; a leading - sorts descending")
	addPageFlags(cmd, &page, &pageSize)
	return cmd
}

func (a *app) agentViewCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "view <id>",
		Short: "Show one agent, with its configuration",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("agent", args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.GetAgentApiV1AgentsAgentIdGet(cmd.Context(), id))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
}
