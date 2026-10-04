// Package cmd holds the truman commands. A command reads its flags, makes one API call, and
// prints the server's JSON on stdout. Progress and errors go to stderr.
package cmd

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"

	"github.com/spf13/cobra"

	"github.com/plivo-labs/truman/cli/internal/api"
	"github.com/plivo-labs/truman/cli/internal/config"
)

var errNoServer = errors.New(`no Truman server: run "truman auth login" or set TRUMAN_URL`)

// app is what every command needs from outside the process. Tests pass their own.
type app struct {
	version string
	getenv  func(string) string
}

// Execute runs the command line in args and returns the exit code: 0 when the command worked,
// 1 otherwise. getenv is os.Getenv outside tests.
func Execute(
	ctx context.Context, version string, args []string, getenv func(string) string,
	stdout, stderr io.Writer,
) int {
	a := &app{version: version, getenv: getenv}
	root := a.rootCmd()
	root.SetArgs(args)
	root.SetOut(stdout)
	root.SetErr(stderr)
	if err := root.ExecuteContext(ctx); err != nil {
		fmt.Fprintln(stderr, "error:", describe(err))
		return 1
	}
	return 0
}

func (a *app) rootCmd() *cobra.Command {
	root := &cobra.Command{
		Use:           "truman",
		Short:         "Command-line client for a Truman server",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.AddCommand(a.versionCmd(), a.agentCmd())
	return root
}

// client returns an API client for the server in the settings.
func (a *app) client() (*api.Client, error) {
	s, err := config.Load(a.getenv)
	if err != nil {
		return nil, err
	}
	if s.Server == "" {
		return nil, errNoServer
	}
	return api.New(s.Server, s.Token, "truman-cli/"+a.version)
}

// describe turns an error into one line that says what happened and the next step.
func describe(err error) string {
	var apiErr *api.Error
	var urlErr *url.Error
	switch {
	case errors.As(err, &apiErr) && apiErr.Status == http.StatusUnauthorized:
		return `the token is wrong: run "truman auth login" or set TRUMAN_API_TOKEN`
	case errors.As(err, &urlErr):
		return fmt.Sprintf("cannot reach %s: is the server running? (%v)", urlErr.URL, urlErr.Err)
	}
	return err.Error()
}

// printJSON writes a response body to w, indented. An empty body, as in a 204, prints nothing.
func printJSON(w io.Writer, body []byte) error {
	if len(body) == 0 {
		return nil
	}
	var buf bytes.Buffer
	if err := json.Indent(&buf, body, "", "  "); err != nil {
		return fmt.Errorf("the server sent a body that is not JSON: %w", err)
	}
	buf.WriteByte('\n')
	_, err := w.Write(buf.Bytes())
	return err
}

// changed returns a pointer to v when the flag was set, and nil otherwise, so that the API's
// default applies to every flag that the user left out.
func changed[T any](cmd *cobra.Command, flag string, v T) *T {
	if !cmd.Flags().Changed(flag) {
		return nil
	}
	return &v
}
