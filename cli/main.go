// Command truman is the command-line client for a Truman server.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/plivo-labs/truman/cli/internal/cmd"
)

// version is set at build time with -ldflags "-X main.version=0.4.2". A build without it is dev.
var version = "dev"

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	code := cmd.Execute(ctx, version, os.Args[1:], os.Getenv, os.Stdout, os.Stderr)
	stop()
	os.Exit(code)
}
