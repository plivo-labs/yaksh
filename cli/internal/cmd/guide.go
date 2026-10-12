package cmd

import (
	"io"

	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksh/cli/skill"
)

func (a *app) guideCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "guide",
		Short: "Print how a coding agent tests a voice agent with this CLI",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			_, err := io.WriteString(cmd.OutOrStdout(), skill.Text)
			return err
		},
	}
}
