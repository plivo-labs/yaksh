// Package wait waits for Yaksh's long work: a run until it ends, the judges' verdicts, and the
// event stream of a call.
package wait

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/plivo-labs/yaksh/cli/internal/api"
)

// ErrTimeout is the cause to give a context whose time limit ends a wait, so that the wait
// returns it.
var ErrTimeout = errors.New("the wait timed out")

// Options control a wait.
type Options struct {
	// Interval is the time between two reads.
	Interval time.Duration
	// Progress gets one line each time the counts change, or nothing when it is nil. With
	// Live, the line is rewritten in place, for a terminal.
	Progress io.Writer
	Live     bool
}

// Result is a run as the server last sent it.
type Result struct {
	// Body is the server's JSON, to print as it is.
	Body []byte
	Run  api.RunRead
}

// Ended reports whether the run is done or cancelled.
func (r Result) Ended() bool {
	return r.Run.Status == api.RunStatusDone || r.Run.Status == api.RunStatusCancelled
}

// Passed reports whether the run is done and every latest call completed. Completed means the
// call ran to its end, not that a judge passed it.
func (r Result) Passed() bool {
	total := r.total()
	return r.Run.Status == api.RunStatusDone && total > 0 && r.Run.Counts["completed"] == total
}

// Summary is one line about the run, for example
// "run 7c1e… done: 3 of 4 calls completed, 1 did not connect (2m41s)".
func (r Result) Summary() string {
	line := fmt.Sprintf("run %s %s: %d of %d calls completed", r.Run.Id, r.Run.Status,
		r.Run.Counts["completed"], r.total())
	if rest := groups(r.Run.Counts, "completed"); rest != "" {
		line += ", " + rest
	}
	if r.Run.StartedAt != nil && r.Run.EndedAt != nil {
		line += fmt.Sprintf(" (%s)", r.Run.EndedAt.Sub(*r.Run.StartedAt).Round(time.Second))
	}
	return line
}

// Progress is one line about a run that has not ended, for example
// "running: 1 completed, 2 waiting (max_parallel)".
func (r Result) Progress() string {
	line := fmt.Sprintf("%s: %s", r.Run.Status, groups(r.Run.Counts, ""))
	if r.Run.WaitingReason != nil {
		line += fmt.Sprintf(" (%s)", *r.Run.WaitingReason)
	}
	return line
}

func (r Result) total() int {
	total := 0
	for _, n := range r.Run.Counts {
		total += n
	}
	return total
}

// groupOrder is the order in which lines list the outcome groups; a group the server adds later
// comes after them, by name.
var groupOrder = []string{"completed", "did_not_connect", "error", "cancelled", "in_progress", "waiting"}

// groups lists the groups with calls in them as "1 did not connect, 2 waiting", leaving out skip.
func groups(counts map[string]int, skip string) string {
	names := make([]string, 0, len(counts))
	for name := range counts {
		names = append(names, name)
	}
	slices.SortFunc(names, func(a, b string) int {
		ia, ib := slices.Index(groupOrder, a), slices.Index(groupOrder, b)
		if ia == -1 {
			ia = len(groupOrder)
		}
		if ib == -1 {
			ib = len(groupOrder)
		}
		if ia != ib {
			return ia - ib
		}
		return strings.Compare(a, b)
	})
	var parts []string
	for _, name := range names {
		if n := counts[name]; n > 0 && name != skip {
			parts = append(parts, fmt.Sprintf("%d %s", n, strings.ReplaceAll(name, "_", " ")))
		}
	}
	return strings.Join(parts, ", ")
}

// Run reads the run every Interval until it ends or ctx is done. When it stops early it returns
// the last read with the cause of ctx. Stopping the wait never touches the run.
func Run(ctx context.Context, c *api.Client, id uuid.UUID, opts Options) (Result, error) {
	return poll(ctx, opts, func(ctx context.Context) (Result, error) { return read(ctx, c, id) },
		Result.Ended, Result.Progress)
}

// poll calls read every opts.Interval until done accepts its value or ctx is done. When it stops
// early it returns the last value with the cause of ctx. Progress gets line(value) each time the
// line changes.
func poll[T any](ctx context.Context, opts Options, read func(context.Context) (T, error),
	done func(T) bool, line func(T) string) (T, error) {
	p := &progress{w: opts.Progress, live: opts.Live}
	defer p.end()
	ticker := time.NewTicker(opts.Interval)
	defer ticker.Stop()
	var last T
	for {
		v, err := read(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return last, context.Cause(ctx)
			}
			return last, err
		}
		last = v
		if done(v) {
			return v, nil
		}
		p.show(line(v))
		select {
		case <-ctx.Done():
			return last, context.Cause(ctx)
		case <-ticker.C:
		}
	}
}

func read(ctx context.Context, c *api.Client, id uuid.UUID) (Result, error) {
	body, err := api.Body(c.GetRunApiV1RunsRunIdGet(ctx, id))
	if err != nil {
		return Result{}, err
	}
	var run api.RunRead
	if err := json.Unmarshal(body, &run); err != nil {
		return Result{}, fmt.Errorf("read run %s: %w", id, err)
	}
	return Result{Body: body, Run: run}, nil
}

// progress writes a line only when it changes. On a terminal it rewrites one line in place.
type progress struct {
	w    io.Writer
	live bool
	last string
}

func (p *progress) show(line string) {
	if p.w == nil || line == p.last {
		return
	}
	p.last = line
	if p.live {
		fmt.Fprintf(p.w, "\r%s\x1b[K", line)
		return
	}
	fmt.Fprintln(p.w, line)
}

// end moves past a line that was rewritten in place.
func (p *progress) end() {
	if p.w != nil && p.live && p.last != "" {
		fmt.Fprintln(p.w)
	}
}
