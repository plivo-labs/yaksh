package cmd

import (
	"github.com/spf13/cobra"

	"github.com/plivo-labs/truman/cli/internal/api"
)

func (a *app) personaCmd() *cobra.Command {
	persona := &cobra.Command{
		Use:   "persona",
		Short: "The callers Truman plays: a prompt, a voice and background noise",
	}
	persona.AddCommand(a.personaListCmd())
	return persona
}

func (a *app) personaListCmd() *cobra.Command {
	var page, pageSize int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List personas, newest first",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := a.client()
			if err != nil {
				return err
			}
			params := api.ListPersonasApiV1PersonasGetParams{
				Page:     changed(cmd, "page", page),
				PageSize: changed(cmd, "page-size", pageSize),
			}
			body, err := api.Body(c.ListPersonasApiV1PersonasGet(cmd.Context(), &params))
			if err != nil {
				return err
			}
			return printJSON(cmd.OutOrStdout(), body)
		},
	}
	addPageFlags(cmd, &page, &pageSize)
	return cmd
}
