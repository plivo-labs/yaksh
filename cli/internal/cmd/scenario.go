package cmd

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksh/cli/internal/api"
	"github.com/plivo-labs/yaksh/cli/internal/sse"
)

func (a *app) scenarioCmd() *cobra.Command {
	scenario := &cobra.Command{
		Use:   "scenario",
		Short: "The test cases of an agent: caller instructions, facts and criteria",
	}
	scenario.AddCommand(
		a.scenarioListCmd(), a.scenarioViewCmd(),
		a.scenarioCreateCmd(), a.scenarioUpdateCmd(), a.scenarioGenerateCmd(),
	)
	return scenario
}

func (a *app) scenarioCreateCmd() *cobra.Command {
	var agent, file string
	cmd := &cobra.Command{
		Use:   "create --agent <id> -f <file>",
		Short: "Add a scenario to an agent from a YAML or JSON file",
		Long: `Add a scenario to an agent from a YAML or JSON file with the fields of a scenario: name,
persona_id, instructions, data_sets and criteria, and if you need them category, description,
unknown_facts, first_words, caller and interruptions. "yaksh scenario view" shows these fields.
Each value goes to the server as the file writes it, so a date or a number with a leading zero
keeps its form.`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			agentID, err := parseID("agent", agent)
			if err != nil {
				return err
			}
			body, err := readDocument(file)
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			created, err := api.Body(c.CreateScenarioApiV1AgentsAgentIdScenariosPostWithBody(
				cmd.Context(), agentID, "application/json", bytes.NewReader(body)))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), created)
		},
	}
	cmd.Flags().StringVar(&agent, "agent", "", "the agent's ID")
	cmd.Flags().StringVarP(&file, "file", "f", "", "the scenario, as a YAML or JSON file")
	cmd.MarkFlagRequired("agent")
	cmd.MarkFlagRequired("file")
	return cmd
}

func (a *app) scenarioUpdateCmd() *cobra.Command {
	var file string
	cmd := &cobra.Command{
		Use:   "update <id> -f <file>",
		Short: "Change a scenario from a YAML or JSON file; a change to what the caller or the judges read makes a new version",
		Long: `Change a scenario from a YAML or JSON file with the fields to change, as for "yaksh scenario
create". A field that the file leaves out keeps its value, and a list in the file replaces the
whole list. Keep the id of each data set that stays, as "yaksh scenario view" shows it: a data
set without an id is a new data set, and a run or a suite that names the old one cannot play it.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID("scenario", args[0])
			if err != nil {
				return err
			}
			body, err := readDocument(file)
			if err != nil {
				return err
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			updated, err := api.Body(c.UpdateScenarioApiV1ScenariosScenarioIdPatchWithBody(
				cmd.Context(), id, "application/json", bytes.NewReader(body)))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), updated)
		},
	}
	cmd.Flags().StringVarP(&file, "file", "f", "", "the fields to change, as a YAML or JSON file")
	cmd.MarkFlagRequired("file")
	return cmd
}

// The server pings every 15 seconds while a generation runs.
const streamIdle = time.Minute

func (a *app) scenarioGenerateCmd() *cobra.Command {
	var (
		agent, mode, instructions string
		count                     int
		personas, documents       []string
	)
	cmd := &cobra.Command{
		Use:   "generate --agent <id> --persona <id>...",
		Short: "Let a model write scenarios for an agent and save them; stopping the command stops the generation",
		Long: `Let the scenario writing model write scenarios for an agent. In the agent mode, the model
writes scenarios for the agent's tasks from its brief, configuration and documents. In the
knowledge_base mode, it writes questions that the documents of --document answer, and some
that they do not answer. The command shows each scenario when Yaksh saves it. At the end, it
prints the generation: its status, its counts and the saved scenarios. A generation takes
minutes. Stopping the command stops the generation, and the scenarios saved until then stay.`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			agentID, err := parseID("agent", agent)
			if err != nil {
				return err
			}
			personaIDs, err := parseIDs("persona", personas)
			if err != nil {
				return err
			}
			documentIDs, err := parseIDs("document", documents)
			if err != nil {
				return err
			}
			body := api.GenerateScenarios{
				PersonaIds:   personaIDs,
				Count:        changed(cmd, "count", count),
				Mode:         changed(cmd, "mode", api.GenerationMode(mode)),
				Instructions: changed(cmd, "instructions", instructions),
				DocumentIds:  changed(cmd, "document", documentIDs),
			}
			return a.generateScenarios(cmd, agentID, body)
		},
	}
	fl := cmd.Flags()
	fl.StringVar(&agent, "agent", "", "the agent's ID")
	fl.StringSliceVar(&personas, "persona", nil, "a persona for the new scenarios; repeat the flag or separate IDs with commas, and each task gets each persona in turn")
	fl.IntVar(&count, "count", 0, "how many scenarios to write, 1 to 20")
	fl.StringVar(&mode, "mode", "", "agent or knowledge_base")
	fl.StringSliceVar(&documents, "document", nil, "a knowledge base document to ask about, in the knowledge_base mode; repeat the flag or separate IDs with commas")
	fl.StringVar(&instructions, "instructions", "", `what the model must focus on, for example "focus on rescheduling"`)
	cmd.MarkFlagRequired("agent")
	cmd.MarkFlagRequired("persona")
	return cmd
}

var errFinished = errors.New("the generation finished")

// generation is what "scenario generate" prints. The started and finished events fill its
// fields.
type generation struct {
	ID        uuid.UUID         `json:"generation_id"`
	Status    string            `json:"status"`
	Saved     int               `json:"saved"`
	Dropped   int               `json:"dropped"`
	Error     *string           `json:"error"`
	Scenarios []json.RawMessage `json:"scenarios"`
}

func (a *app) generateScenarios(cmd *cobra.Command, agentID uuid.UUID, body api.GenerateScenarios) error {
	c, err := a.streamClient()
	if err != nil {
		return err
	}
	stream, err := api.Stream(c.GenerateScenariosApiV1AgentsAgentIdScenariosGeneratePost(cmd.Context(), agentID, body))
	if err != nil {
		return err
	}
	stderr := cmd.ErrOrStderr()
	g := generation{Scenarios: []json.RawMessage{}}
	err = sse.Read(stream, streamIdle, func(e sse.Event) error {
		switch e.Name {
		case "started":
			if err := decodeEvent(e, &g); err != nil {
				return err
			}
			fmt.Fprintf(stderr, "generation %s started\n", g.ID)
		case "scenario":
			var scenario struct {
				ID   string `json:"id"`
				Name string `json:"name"`
			}
			if err := decodeEvent(e, &scenario); err != nil {
				return err
			}
			g.Scenarios = append(g.Scenarios, e.Data)
			fmt.Fprintf(stderr, "saved scenario %s: %s\n", scenario.ID, scenario.Name)
		case "dropped":
			var dropped struct {
				Reason string `json:"reason"`
			}
			if err := decodeEvent(e, &dropped); err != nil {
				return err
			}
			fmt.Fprintf(stderr, "dropped a scenario: %s\n", dropped.Reason)
		case "finished":
			if err := decodeEvent(e, &g); err != nil {
				return err
			}
			return errFinished
		}
		return nil
	})
	saved := "yaksh scenario list --agent " + agentID.String()
	if g.ID != uuid.Nil {
		saved += " --generation " + g.ID.String()
	}
	switch {
	case errors.Is(err, errFinished):
	case cmd.Context().Err() != nil:
		return &nextStep{"stopped: the generation stops, and the scenarios that it saved stay", saved}
	case err != nil:
		return &nextStep{fmt.Sprintf("could not read the generation (%s); the scenarios that it saved stay", describe(err)), saved}
	default:
		return &nextStep{"the stream ended before the generation did; the scenarios that it saved stay", saved}
	}
	printed, err := json.Marshal(g)
	if err != nil {
		return err
	}
	if err := printJSON(cmd.OutOrStdout(), printed); err != nil {
		return err
	}
	summary := fmt.Sprintf("generation %s %s: %d saved, %d dropped", g.ID, g.Status, g.Saved, g.Dropped)
	if g.Status != string(api.GenerationStatusDone) {
		if g.Error != nil {
			summary += ": " + *g.Error
		}
		return errors.New(summary)
	}
	fmt.Fprintln(stderr, summary)
	return nil
}

func decodeEvent(e sse.Event, v any) error {
	if err := json.Unmarshal(e.Data, v); err != nil {
		return fmt.Errorf("read the %s event: %w", e.Name, err)
	}
	return nil
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
