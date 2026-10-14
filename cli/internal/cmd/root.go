// Package cmd holds the yaksh commands. A command reads its flags, makes one API call, and
// prints the server's JSON on stdout. Progress, hints and errors go to stderr.
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
	"os"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/spf13/cobra"
	"golang.org/x/term"

	"github.com/plivo-labs/yaksh/cli/internal/api"
	"github.com/plivo-labs/yaksh/cli/internal/config"
)

var errNoServer = errors.New(`no Yaksh server: run "yaksh auth login" or set YAKSH_URL`)

// pollInterval is the time between two reads of a run.
const pollInterval = 5 * time.Second

// app is what every command needs from outside the process. Tests pass their own.
type app struct {
	version      string
	getenv       func(string) string
	pollInterval time.Duration
}

// Execute runs the command line in args and returns the exit code: 0 when the command worked,
// 1 otherwise. getenv is os.Getenv outside tests.
func Execute(
	ctx context.Context, version string, args []string, getenv func(string) string,
	stdin io.Reader, stdout, stderr io.Writer,
) int {
	a := &app{version: version, getenv: getenv, pollInterval: pollInterval}
	return a.execute(ctx, args, stdin, stdout, stderr)
}

func (a *app) execute(ctx context.Context, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	root := &cobra.Command{
		Use:           "yaksh",
		Short:         "Command-line client for a Yaksh server",
		Long:          "Command-line client for a Yaksh server. Coding agents: run \"yaksh guide\" first.",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.AddCommand(
		a.authCmd(), a.versionCmd(), a.guideCmd(),
		a.agentCmd(), a.scenarioCmd(), a.personaCmd(), a.runCmd(), a.conversationCmd(),
		a.settingsCmd(), a.numbersCmd(),
	)
	root.SetArgs(args)
	root.SetIn(stdin)
	root.SetOut(stdout)
	root.SetErr(stderr)
	if err := root.ExecuteContext(ctx); err != nil {
		var f *failure
		if errors.As(err, &f) {
			fmt.Fprintln(stderr, "failed:", f.Error())
		} else {
			fmt.Fprintln(stderr, "error:", describe(err))
		}
		return 1
	}
	return 0
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
	return api.New(s.Server, s.Token, a.userAgent())
}

func (a *app) userAgent() string {
	return "yaksh-cli/" + a.version
}

// nextStep is an error whose message ends with the command to run next.
type nextStep struct {
	what, next string
}

func (e *nextStep) Error() string {
	return e.what + "\nnext: " + e.next
}

// failure is a test that ran and did not pass: a call that did not complete, or a verdict. It
// prints as "failed:", so that it does not read as a command that went wrong.
type failure struct{ nextStep }

// describe turns an error into a message that says what happened and the next step.
func describe(err error) string {
	var apiErr *api.Error
	var urlErr *url.Error
	switch {
	case errors.As(err, &apiErr) && apiErr.Status == http.StatusUnauthorized:
		return `the token is wrong: run "yaksh auth login" or set YAKSH_API_TOKEN`
	case errors.As(err, &urlErr) && !errors.Is(err, context.Canceled):
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

// timeFlag reads an RFC 3339 time, or a date that means midnight in the local time zone.
type timeFlag struct{ t *time.Time }

func (f timeFlag) Set(value string) error {
	t, err := time.Parse(time.RFC3339, value)
	if err != nil {
		t, err = time.ParseInLocation(time.DateOnly, value, time.Local)
	}
	if err != nil {
		return fmt.Errorf("%q is not a date such as 2026-10-01 or a time such as 2026-10-01T09:00:00+05:30", value)
	}
	*f.t = t
	return nil
}

func (f timeFlag) String() string {
	if f.t == nil || f.t.IsZero() {
		return ""
	}
	return f.t.Format(time.RFC3339)
}

func (timeFlag) Type() string { return "time" }

// parseID reads the ID of a kind of record, such as "agent", from an argument or a flag.
func parseID(kind, value string) (uuid.UUID, error) {
	id, err := uuid.Parse(value)
	if err != nil {
		return uuid.Nil, fmt.Errorf(`%q is not a%s %s ID: find it with "yaksh %s list"`,
			value, article(kind), kind, kind)
	}
	return id, nil
}

func article(kind string) string {
	if kind != "" && strings.ContainsRune("aeiou", rune(kind[0])) {
		return "n"
	}
	return ""
}

// idOf reads the "id" field of a JSON record.
func idOf(body []byte) (uuid.UUID, error) {
	var record struct {
		ID uuid.UUID `json:"id"`
	}
	if err := json.Unmarshal(body, &record); err != nil {
		return uuid.Nil, fmt.Errorf("read the record's id: %w", err)
	}
	return record.ID, nil
}

// isTerminal reports whether v is a terminal, which decides prompts and in-place progress.
func isTerminal(v any) bool {
	f, ok := v.(*os.File)
	return ok && term.IsTerminal(int(f.Fd()))
}

// addPageFlags adds the API's page and page_size parameters to a list command.
func addPageFlags(cmd *cobra.Command, page, pageSize *int) {
	cmd.Flags().IntVar(page, "page", 0, "page number, from 1")
	cmd.Flags().IntVar(pageSize, "page-size", 0, "items per page, up to 100")
}
