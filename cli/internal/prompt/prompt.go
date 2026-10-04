// Package prompt reads a line of input that Ctrl-C can stop, including a secret typed at a
// terminal without showing it.
package prompt

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
)

// Line reads one line from r, without its line ending. It returns ctx's error as soon as ctx
// ends; a read that is still blocked then ends with the process, which exits right after.
func Line(ctx context.Context, r io.Reader) (string, error) {
	type result struct {
		line string
		err  error
	}
	done := make(chan result, 1)
	go func() {
		line, err := bufio.NewReader(r).ReadString('\n')
		if errors.Is(err, io.EOF) {
			err = nil
		}
		done <- result{strings.TrimRight(line, "\r\n"), err}
	}()
	select {
	case r := <-done:
		return r.line, r.err
	case <-ctx.Done():
		return "", ctx.Err()
	}
}

// Secret writes label to w, then reads one line from the terminal f without showing what is
// typed. Echo is off before the read starts and back on before Secret returns, also when ctx
// ends first.
func Secret(ctx context.Context, f *os.File, w io.Writer, label string) (string, error) {
	restore, err := hideInput(int(f.Fd()))
	if err != nil {
		return "", fmt.Errorf("hide the input: %w", err)
	}
	defer restore()
	defer fmt.Fprintln(w)
	fmt.Fprint(w, label)
	return Line(ctx, f)
}
