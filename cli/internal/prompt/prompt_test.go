package prompt

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"
	"time"
)

func TestLineReadsOneLine(t *testing.T) {
	for _, input := range []string{"s3cret\nnext line\n", "s3cret\r\n", "s3cret"} {
		if got, err := Line(context.Background(), strings.NewReader(input)); err != nil || got != "s3cret" {
			t.Fatalf("Line(%q) = %q, %v; want the first line", input, got, err)
		}
	}
}

func TestLineStopsWhenTheContextEnds(t *testing.T) {
	blocked, _ := io.Pipe()
	ctx, cancel := context.WithCancel(context.Background())
	time.AfterFunc(10*time.Millisecond, cancel)

	if _, err := Line(ctx, blocked); !errors.Is(err, context.Canceled) {
		t.Fatalf("Line error = %v, want context.Canceled while the input is still open", err)
	}
}
