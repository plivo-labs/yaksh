package cmd

import (
	"encoding/json"

	"github.com/spf13/cobra"
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
			server, err := c.ServerVersion(cmd.Context())
			if err != nil {
				return err
			}
			out, err := json.Marshal(map[string]string{"cli": a.version, "server": server})
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), out)
		},
	}
}
