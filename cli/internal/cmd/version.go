package cmd

import (
	"encoding/json"
	"fmt"

	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksh/cli/internal/api"
)

func (a *app) versionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Print the CLI's version and the server's",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := a.client()
			if err != nil {
				return err
			}
			body, err := api.Body(c.HealthApiV1HealthGet(cmd.Context()))
			if err != nil {
				return err
			}
			var health api.HealthResponse
			if err := json.Unmarshal(body, &health); err != nil {
				return fmt.Errorf("read the server's version: %w", err)
			}
			out, err := json.Marshal(map[string]string{"cli": a.version, "server": health.Version})
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), out)
		},
	}
}
