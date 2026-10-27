package sse

import (
	"errors"
	"io"
	"slices"
	"strings"
	"testing"
	"time"
)

func TestReadGivesEachEventInOrderAndSkipsComments(t *testing.T) {
	stream := ": ping\n\n" +
		"event: started\ndata: {\"id\":1}\n\n" +
		"event: note\r\ndata: first line\r\ndata: second line\r\n\r\n" +
		"event: finished\ndata: {}"
	var got []string
	err := Read(io.NopCloser(strings.NewReader(stream)), time.Minute, func(e Event) error {
		got = append(got, e.Name+" "+string(e.Data))
		return nil
	})

	want := []string{`started {"id":1}`, "note first line\nsecond line"}
	if err != nil || !slices.Equal(got, want) {
		t.Fatalf("err = %v, events = %q, want %q", err, got, want)
	}
}

func TestReadEndsAStreamThatGoesQuiet(t *testing.T) {
	r, w := io.Pipe()
	go w.Write([]byte("event: started\ndata: {}\n\n"))
	var names []string
	err := Read(r, 20*time.Millisecond, func(e Event) error {
		names = append(names, e.Name)
		return nil
	})

	if !errors.Is(err, errQuiet) || !slices.Equal(names, []string{"started"}) {
		t.Fatalf("err = %v, events = %q", err, names)
	}
}
