// Package sse reads a stream of server-sent events.
package sse

import (
	"bufio"
	"bytes"
	"errors"
	"io"
	"sync/atomic"
	"time"
)

var errQuiet = errors.New("the server sent nothing for too long")

type Event struct {
	Name string
	Data []byte
}

// Read gives each event of body to handle until the stream ends, handle returns an error, or
// body sends nothing for idle. It closes body.
func Read(body io.ReadCloser, idle time.Duration, handle func(Event) error) error {
	var quiet atomic.Bool
	timer := time.AfterFunc(idle, func() {
		quiet.Store(true)
		body.Close()
	})
	defer timer.Stop()
	defer body.Close()
	lines := bufio.NewReader(watched{body, timer, idle})
	var name string
	var data []byte
	for {
		line, err := lines.ReadBytes('\n')
		switch {
		case err == nil:
		case quiet.Load():
			return errQuiet
		case errors.Is(err, io.EOF):
			// The standard drops an event that has no blank line after it.
			return nil
		default:
			return err
		}
		line = bytes.TrimSuffix(bytes.TrimSuffix(line, []byte("\n")), []byte("\r"))
		if len(line) == 0 {
			if data != nil {
				if err := handle(Event{Name: name, Data: bytes.TrimSuffix(data, []byte("\n"))}); err != nil {
					return err
				}
			}
			name, data = "", nil
			continue
		}
		field, value, _ := bytes.Cut(line, []byte(":"))
		value = bytes.TrimPrefix(value, []byte(" "))
		switch string(field) {
		case "event":
			name = string(value)
		case "data":
			data = append(append(data, value...), '\n')
		}
	}
}

type watched struct {
	r     io.Reader
	timer *time.Timer
	idle  time.Duration
}

func (w watched) Read(p []byte) (int, error) {
	n, err := w.r.Read(p)
	if n > 0 {
		w.timer.Reset(w.idle)
	}
	return n, err
}
