package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"slices"
	"strings"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"

	"github.com/plivo-labs/yaksh/cli/internal/api"
)

// placeholder is a secret in a settings document that names an environment variable; as on the
// server, only a whole value counts.
var placeholder = regexp.MustCompile(`^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$`)

func (a *app) settingsCmd() *cobra.Command {
	settings := &cobra.Command{
		Use:   "settings",
		Short: "Keys, models and limits: what the console's Settings page holds",
	}
	settings.AddCommand(a.settingsGetCmd(), a.settingsExportCmd(), a.settingsApplyCmd())
	return settings
}

func (a *app) settingsGetCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "get",
		Short: "Print the settings; a saved secret shows only its last 4 characters",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.GetSettingsApiV1SettingsGet(cmd.Context()))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
}

func (a *app) settingsExportCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "export",
		Short: "Print the settings as a YAML document for settings apply",
		Long: "Print the values that differ from the defaults, and each saved secret as ${NAME}. " +
			"The document holds no secret value, so it is safe to commit.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.ExportSettingsApiV1SettingsExportGet(cmd.Context()))
			if err != nil {
				return err
			}
			_, err = cmd.OutOrStdout().Write(body)
			return err
		},
	}
}

func (a *app) settingsApplyCmd() *cobra.Command {
	var file string
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "apply -f FILE",
		Short: "Apply a YAML settings document",
		Long: "Apply a YAML settings document, as settings export writes it. A secret given as " +
			"${NAME} takes the value of the environment variable NAME. The server checks every key " +
			"with its provider and saves the settings and the keys that pass. Each key that fails is " +
			"left out and listed under failed, and the command then exits with status 1.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			document, err := os.ReadFile(file)
			if err != nil {
				return fmt.Errorf("read the settings file: %w", err)
			}
			env, missing, err := a.placeholderValues(document)
			if err != nil {
				return fmt.Errorf("read %s: %w", file, err)
			}
			if len(missing) > 0 && !dryRun {
				return fmt.Errorf("set these environment variables, which %s names: %s",
					file, strings.Join(missing, ", "))
			}
			c, err := a.client()
			if err != nil {
				return err
			}
			request := api.SettingsImport{Document: string(document), Env: &env, DryRun: &dryRun}
			body, err := api.Body(c.ImportSettingsApiV1SettingsImportPost(cmd.Context(), request))
			if err != nil {
				return err
			}
			if err := printJSON(cmd.OutOrStdout(), body); err != nil {
				return err
			}
			var result api.ImportResult
			if err := json.Unmarshal(body, &result); err != nil {
				return fmt.Errorf("read the import result: %w", err)
			}
			if len(result.Failed) > 0 {
				return &nextStep{
					what: "these keys failed their check and were not saved; the rest was saved:\n  " +
						strings.Join(result.Failed, "\n  "),
					next: "fix the keys in " + file + " and run this command again",
				}
			}
			return nil
		},
	}
	cmd.Flags().StringVarP(&file, "file", "f", "", "the YAML settings document")
	cmd.Flags().BoolVar(&dryRun, "dry-run", false,
		"list the changes without saving or checking any key; a variable that is not set is listed as skipped")
	cmd.MarkFlagRequired("file")
	return cmd
}

// placeholderValues returns the value of every environment variable that a secret of the
// document names as ${NAME}, and the sorted names that are not set. Only the values under
// secrets and trigger_secrets are secrets; the server reads the document the same way.
func (a *app) placeholderValues(document []byte) (map[string]string, []string, error) {
	var sections map[string]any
	if err := yaml.Unmarshal(document, &sections); err != nil {
		return nil, nil, err
	}
	env := map[string]string{}
	var missing []string
	for _, section := range []string{"secrets", "trigger_secrets"} {
		values, _ := sections[section].(map[string]any)
		for _, value := range values {
			text, _ := value.(string)
			match := placeholder.FindStringSubmatch(text)
			if match == nil {
				continue
			}
			name := match[1]
			if _, seen := env[name]; seen || slices.Contains(missing, name) {
				continue
			}
			if found := a.getenv(name); found != "" {
				env[name] = found
			} else {
				missing = append(missing, name)
			}
		}
	}
	slices.Sort(missing)
	return env, missing, nil
}
