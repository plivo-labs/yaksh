package cmd

import (
	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksh/cli/internal/api"
)

func (a *app) scenarioCmd() *cobra.Command {
	scenario := &cobra.Command{
		Use:   "scenario",
		Short: "The test cases of an agent: caller instructions, facts and criteria",
	}
	scenario.AddCommand(a.scenarioListCmd(), a.scenarioViewCmd())
	return scenario
}

func (a *app) scenarioListCmd() *cobra.Command {
	var (
		agent, generation string
		page, pageSize    int
	)
	cmd := &cobra.Command{
		Use:   "list --agent <id>",
		Short: "List an agent's scenarios, newest first",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			agentID, err := parseID("agent", agent)
			if err != nil {
				return err
			}
			params := api.ListScenariosApiV1AgentsAgentIdScenariosGetParams{
				Page:     changed(cmd, "page", page),
				PageSize: changed(cmd, "page-size", pageSize),
			}
			if cmd.Flags().Changed("generation") {
				id, err := parseID("generation", generation)
				if err != nil {
					return err
				}
				params.GenerationId = &id
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.ListScenariosApiV1AgentsAgentIdScenariosGet(cmd.Context(), agentID, &params))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
	cmd.Flags().StringVar(&agent, "agent", "", "the agent's ID")
	cmd.Flags().StringVar(&generation, "generation", "", "only the scenarios of one generation")
	addPageFlags(cmd, &page, &pageSize)
	cmd.MarkFlagRequired("agent")
	return cmd
}

func (a *app) scenarioViewCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "view <id>",
		Short: "Show one scenario: its instructions, facts and criteria",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("scenario", args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.GetScenarioApiV1ScenariosScenarioIdGet(cmd.Context(), id))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
}
