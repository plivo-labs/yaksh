package cmd

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksh/cli/internal/api"
)

func (a *app) agentCmd() *cobra.Command {
	agent := &cobra.Command{
		Use:   "agent",
		Short: "The voice agents that Yaksh tests",
	}
	agent.AddCommand(a.agentListCmd(), a.agentViewCmd(), a.agentImportCmd(), a.agentUpdateCmd())
	return agent
}

func (a *app) agentUpdateCmd() *cobra.Command {
	var configFile, rulesFile string
	cmd := &cobra.Command{
		Use:   "update <id> (--config-file <path> | --rules-file <path>)",
		Short: "Change an agent's configuration or rules in Yaksh, which the judges read; a change makes a new agent version",
		Long: `Change what the judges read about an agent. --config-file sets the agent's configuration:
its prompt, flow or export, as text. --rules-file sets the agent's rules from a YAML or JSON
list, and replaces all of them: "yaksh agent view" shows the rules that the agent has.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("agent", args[0])
			if err != nil {
				return err
			}
			change := map[string]any{}
			if cmd.Flags().Changed("config-file") {
				config, err := os.ReadFile(configFile)
				if err != nil {
					return err
				}
				change["config"] = string(config)
			}
			if cmd.Flags().Changed("rules-file") {
				rules, err := readDocument(rulesFile)
				if err != nil {
					return err
				}
				change["rules"] = json.RawMessage(rules)
			}
			sent, err := json.Marshal(change)
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.UpdateAgentApiV1AgentsAgentIdPatchWithBody(
				cmd.Context(), id, "application/json", bytes.NewReader(sent)))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
	cmd.Flags().StringVar(&configFile, "config-file", "",
		"a file with the agent's full configuration as text: a prompt, a flow or an export")
	cmd.Flags().StringVar(&rulesFile, "rules-file", "",
		"a YAML or JSON file with the list of the agent's rules, which replaces all of its rules")
	cmd.MarkFlagsOneRequired("config-file", "rules-file")
	return cmd
}

func (a *app) agentImportCmd() *cobra.Command {
	var name, brief, number string
	cmd := &cobra.Command{
		Use:   "import <file> [--brief <text> --number <E.164>]",
		Short: "Read a Plivo CX agent download into a draft; with --brief and --number, add the agent",
		Long: `Read a Plivo CX agent download (the console's {name}-config.json) into a draft: the name,
the agent ID, the languages and the whole file as the config. Without flags, print the draft.
With --brief and --number, add the agent, which Yaksh then calls on that number.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			content, err := os.ReadFile(args[0])
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.ImportAgentFileApiV1AgentsImportPost(cmd.Context(), api.AgentFile{Content: string(content)}))
			if err != nil {
				return err
			}
			var draft api.AgentDraft
			if err := json.Unmarshal(body, &draft); err != nil {
				return fmt.Errorf("read the draft: %w", err)
			}
			if cmd.Flags().Changed("name") {
				draft.Name = &name
			}
			if !cmd.Flags().Changed("brief") {
				shown, err := json.Marshal(draft)
				if err != nil {
					return err
				}
				return printJSON(cmd.OutOrStdout(), shown)
			}
			if draft.Name == nil {
				return errors.New("the file has no agent name; set one with --name")
			}
			if len(draft.Languages) == 0 {
				return errors.New("the file has no language that Yaksh knows; see language_note in the draft")
			}
			created, err := api.Body(c.CreateAgentApiV1AgentsPost(cmd.Context(), api.AgentCreate{
				Name:        *draft.Name,
				ExternalId:  draft.ExternalId,
				Languages:   &draft.Languages,
				Config:      &draft.Config,
				Brief:       brief,
				AgentNumber: &number,
			}))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), created)
		},
	}
	f := cmd.Flags()
	f.StringVar(&brief, "brief", "", "what the agent does, in at least 20 characters")
	f.StringVar(&number, "number", "", "the agent's phone number, such as +14155550100")
	f.StringVar(&name, "name", "", "the agent's name, in place of the name in the file")
	cmd.MarkFlagsRequiredTogether("brief", "number")
	return cmd
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
	f.StringVar(&sort, "sort", "", "name, languages, created_at or updated_at; a leading - sorts descending")
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
