package cmd

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/plivo-labs/yaksh/cli/internal/config"
	"github.com/plivo-labs/yaksh/cli/internal/update"
)

const (
	// updatedVar marks the process that an update started, so a release that still does not
	// match the server cannot start an update loop.
	updatedVar = "YAKSH_CLI_UPDATED"

	// offline marks a command that does not call the saved server, so it does not follow it.
	offline = "offline"

	patchCheckInterval = 24 * time.Hour
	healthTimeout      = 10 * time.Second
	updateTimeout      = 2 * time.Minute
)

// followServer runs before each command. It keeps the CLI on the server's minor version and,
// once a day, on the newest patch of that version. After an update it starts the command again
// with the new binary. Any problem is a warning: the command still runs.
func (a *app) followServer(cmd *cobra.Command, _ []string) error {
	cliLine := update.Line(a.version)
	if cliLine == "" || a.getenv(updatedVar) != "" || isOffline(cmd) || !validFlags(cmd) {
		return nil
	}
	server, ok := a.serverVersion(cmd.Context())
	line := update.Line(server)
	if !ok || line == "" {
		return nil
	}
	why := "to match the server " + server
	if line == cliLine {
		if !a.patchCheckDue() {
			return nil
		}
		why = "to its newest patch"
	}
	ctx, cancel := context.WithTimeout(cmd.Context(), updateTimeout)
	defer cancel()
	target, err := a.releases.Newest(ctx, line)
	stderr := cmd.ErrOrStderr()
	switch {
	case err != nil:
		fmt.Fprintf(stderr, "warning: cannot look for a CLI release: %v\n", err)
	case target == "" && line != cliLine:
		fmt.Fprintf(stderr, "warning: the CLI is %s and no CLI release matches the server %s\n", a.version, server)
	case target != "" && (line != cliLine || update.Newer(target, a.version)):
		return a.updateTo(ctx, stderr, target, why)
	}
	return nil
}

// serverVersion reads the version of the saved server. It reports false when there is no server
// or it does not answer: the command itself then reports the problem.
func (a *app) serverVersion(ctx context.Context) (string, bool) {
	c, err := a.client()
	if err != nil {
		return "", false
	}
	ctx, cancel := context.WithTimeout(ctx, healthTimeout)
	defer cancel()
	version, err := c.ServerVersion(ctx)
	return version, err == nil
}

// updateTo installs version over the running binary, then starts the command again with it. If
// the install fails, the command runs on the current binary.
func (a *app) updateTo(ctx context.Context, stderr io.Writer, version, why string) error {
	exe, err := a.executable()
	if err == nil {
		exe, err = filepath.EvalSymlinks(exe)
	}
	if err == nil {
		err = a.releases.Install(ctx, version, exe)
	}
	if err != nil {
		fmt.Fprintf(stderr, "warning: cannot update the CLI from %s to %s: %v\n", a.version, version, err)
		fmt.Fprintln(stderr, "next: install it again with curl -fsSL https://raw.githubusercontent.com/plivo-labs/yaksh/main/install.sh | bash")
		return nil
	}
	fmt.Fprintf(stderr, "updated the CLI from %s to %s, %s\n", a.version, version, why)
	if err := a.restart(exe); err != nil {
		return fmt.Errorf("start the updated CLI: %w", err)
	}
	return nil
}

// patchCheckDue reports whether the last look for a newer patch was a day ago or more, and
// records this look in the time of a file. A CLI that cannot record it looks again at the next
// command.
func (a *app) patchCheckDue() bool {
	path, err := config.Path(a.getenv)
	if err != nil {
		return false
	}
	path = filepath.Join(filepath.Dir(path), "update-check")
	if info, err := os.Stat(path); err == nil && time.Since(info.ModTime()) < patchCheckInterval {
		return false
	}
	// Opening with O_TRUNC sets the modification time, also of a file that is already empty.
	if os.MkdirAll(filepath.Dir(path), 0o700) == nil {
		_ = os.WriteFile(path, nil, 0o600)
	}
	return true
}

// validFlags reports whether cobra will accept the flags. Cobra checks them after this hook, and
// a command line that it refuses must not call the server.
func validFlags(cmd *cobra.Command) bool {
	return cmd.ValidateRequiredFlags() == nil && cmd.ValidateFlagGroups() == nil
}

func isOffline(cmd *cobra.Command) bool {
	for c := cmd; c != nil; c = c.Parent() {
		if c.Annotations[offline] != "" {
			return true
		}
	}
	return false
}

// restart replaces this process with the binary at exe and the same arguments.
func restart(exe string) error {
	return syscall.Exec(exe, os.Args, append(os.Environ(), updatedVar+"=1"))
}
