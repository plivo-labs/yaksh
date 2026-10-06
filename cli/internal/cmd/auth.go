package cmd

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"

	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksha/cli/internal/api"
	"github.com/plivo-labs/yaksha/cli/internal/config"
	"github.com/plivo-labs/yaksha/cli/internal/prompt"
)

func (a *app) authCmd() *cobra.Command {
	auth := &cobra.Command{
		Use:   "auth",
		Short: "Save, check and remove the server and token",
		Long: "Save, check and remove the server and token. The environment variables YAKSHA_URL and " +
			"YAKSHA_API_TOKEN win over the saved file.",
	}
	auth.AddCommand(a.authLoginCmd(), a.authStatusCmd(), a.authLogoutCmd())
	return auth
}

func (a *app) authLoginCmd() *cobra.Command {
	var (
		server    string
		withToken bool
	)
	cmd := &cobra.Command{
		Use:   "login --server <url> [--with-token]",
		Short: "Check a server and its API token, then save both",
		Example: `  yaksha auth login --server https://yaksha.example.com
  echo "$TOKEN" | yaksha auth login --server https://yaksha.example.com --with-token`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			in, stderr := cmd.InOrStdin(), cmd.ErrOrStderr()
			if server == "" {
				server = a.getenv("YAKSHA_URL")
			}
			if server == "" {
				return errors.New("auth login needs --server <url>")
			}
			warning, err := checkServer(server)
			if err != nil {
				return err
			}
			if warning != "" {
				fmt.Fprintln(stderr, "warning:", warning)
			}
			token, err := readToken(cmd.Context(), in, stderr, withToken)
			if errors.Is(err, context.Canceled) {
				return errors.New("stopped; nothing was saved")
			}
			if err != nil {
				return err
			}
			_, err = a.check(cmd.Context(), config.Settings{Server: server, Token: token})
			var apiErr *api.Error
			if errors.As(err, &apiErr) && apiErr.Status == http.StatusUnauthorized {
				return errors.New("the server refused the token; nothing was saved")
			}
			if err != nil {
				return err
			}
			if err := config.Save(a.getenv, config.Settings{Server: server, Token: token}); err != nil {
				return err
			}
			path, _ := config.Path(a.getenv)
			fmt.Fprintf(stderr, "logged in to %s; saved in %s\n", server, path)
			if a.getenv("YAKSHA_URL") != "" || a.getenv("YAKSHA_API_TOKEN") != "" {
				fmt.Fprintln(stderr, "note: YAKSHA_URL or YAKSHA_API_TOKEN is set, and it wins over the saved file")
			}
			return nil
		},
	}
	cmd.Flags().StringVar(&server, "server", "", "the Yaksha server, for example https://yaksha.example.com")
	cmd.Flags().BoolVar(&withToken, "with-token", false, "read the token from stdin")
	return cmd
}

// checkServer refuses a URL that is not http or https. Plain http to a host that is not local
// gets a warning, because the token would then travel in clear text.
func checkServer(server string) (warning string, err error) {
	u, err := url.Parse(server)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return "", fmt.Errorf("%q is not a server URL: use one like https://yaksha.example.com", server)
	}
	if u.Scheme == "http" && !isLocal(u.Hostname()) {
		return fmt.Sprintf("%s uses plain http, so the token travels in clear text", server), nil
	}
	return "", nil
}

func isLocal(host string) bool {
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// readToken reads the token from stdin with --with-token, or from a hidden prompt on a terminal.
// Ctrl-C stops it with ctx's error.
func readToken(ctx context.Context, in io.Reader, stderr io.Writer, withToken bool) (string, error) {
	var (
		token string
		err   error
	)
	switch {
	case withToken:
		token, err = prompt.Line(ctx, in)
	case isTerminal(in):
		token, err = prompt.Secret(ctx, in.(*os.File), stderr, "API token: ")
	default:
		return "", errors.New("auth login needs the token: pass --with-token and send it on stdin")
	}
	if err != nil {
		return "", err
	}
	if token = strings.TrimSpace(token); token == "" {
		return "", errors.New("the token is empty")
	}
	return token, nil
}

func (a *app) authStatusCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "status",
		Short: "Show the server, where each setting comes from, and whether the token works",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			loaded, err := config.Load(a.getenv)
			if err != nil {
				return err
			}
			status := struct {
				Server        string        `json:"server"`
				ServerFrom    config.Origin `json:"server_from"`
				TokenFrom     config.Origin `json:"token_from"`
				CLIVersion    string        `json:"cli_version"`
				ServerVersion string        `json:"server_version,omitempty"`
			}{loaded.Server, loaded.ServerFrom, loaded.TokenFrom, a.version, ""}
			var checkErr error
			if loaded.Server == "" {
				checkErr = errNoServer
			} else {
				status.ServerVersion, checkErr = a.check(cmd.Context(), loaded.Settings)
			}
			out, err := json.Marshal(status)
			if err != nil {
				return err
			}
			if err := printJSON(cmd.OutOrStdout(), out); err != nil {
				return err
			}
			return checkErr
		},
	}
}

// check returns the server's version. It fails unless the server answers as Yaksha and takes
// the token.
func (a *app) check(ctx context.Context, s config.Settings) (string, error) {
	c, err := api.New(s.Server, s.Token, a.userAgent())
	if err != nil {
		return "", err
	}
	body, err := api.Body(c.HealthApiV1HealthGet(ctx))
	if err != nil {
		return "", err
	}
	var health api.HealthResponse
	if err := json.Unmarshal(body, &health); err != nil {
		return "", fmt.Errorf("read the server's version: %w", err)
	}
	one := 1
	_, err = api.Body(c.ListAgentsApiV1AgentsGet(ctx, &api.ListAgentsApiV1AgentsGetParams{PageSize: &one}))
	return health.Version, err
}

func (a *app) authLogoutCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "logout",
		Short: "Delete the saved server and token",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			removed, err := config.Remove(a.getenv)
			if err != nil {
				return err
			}
			stderr := cmd.ErrOrStderr()
			path, _ := config.Path(a.getenv)
			if removed {
				fmt.Fprintf(stderr, "deleted %s\n", path)
			} else {
				fmt.Fprintf(stderr, "nothing to delete: %s does not exist\n", path)
			}
			if a.getenv("YAKSHA_URL") != "" || a.getenv("YAKSHA_API_TOKEN") != "" {
				fmt.Fprintln(stderr, "note: YAKSHA_URL or YAKSHA_API_TOKEN is still set in the environment")
			}
			return nil
		},
	}
}
