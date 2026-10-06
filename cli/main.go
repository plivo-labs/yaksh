// Command yaksha is the command-line client for a Yaksha server.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/plivo-labs/yaksha/cli/internal/cmd"
)

// version is set at build time with -ldflags "-X main.version=0.4.2". A build without it is dev.
var version = "dev"

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	// The first Ctrl-C or SIGTERM ends ctx and lets the command clean up. Restoring the default
	// handling then means a second one ends the process at once.
	go func() {
		<-ctx.Done()
		stop()
	}()
	code := cmd.Execute(ctx, version, os.Args[1:], os.Getenv, os.Stdin, os.Stdout, os.Stderr)
	stop()
	os.Exit(code)
}
