package wait

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/plivo-labs/truman/cli/internal/api"
)

// maxEventSize bounds one line of the stream. A turn's text is far smaller.
const maxEventSize = 1 << 20

// errorBodyTimeout bounds reading the body of an error response to the stream request. A test
// makes it short.
var errorBodyTimeout = 30 * time.Second

// Event is one event of a call's stream: "turn", "wire_event" or "status", with its JSON data.
type Event struct {
	Name string          `json:"event"`
	Data json.RawMessage `json:"data"`
}

// Conversation follows the call's event stream and passes each event to emit, in order. The
// stream first replays what already happened, and the server ends it once the call has ended.
// If the stream breaks, it returns an error, and if ctx is done, the cause of ctx. The call goes
// on either way.
func Conversation(ctx context.Context, c *api.Client, id uuid.UUID, emit func(Event) error) error {
	err := follow(ctx, c, id, emit)
	if err != nil && ctx.Err() != nil {
		return context.Cause(ctx)
	}
	return err
}

func follow(ctx context.Context, c *api.Client, id uuid.UUID, emit func(Event) error) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	resp, err := api.Stream(c).StreamEventsApiV1ConversationsConversationIdEventsGet(ctx, id)
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusOK {
		// Only a stream may stay open; an error body that stalls ends the request.
		stall := time.AfterFunc(errorBodyTimeout, cancel)
		_, err := api.Body(resp, nil)
		if !stall.Stop() {
			return fmt.Errorf("the server answered the event stream with %d and then stalled", resp.StatusCode)
		}
		return err
	}
	defer resp.Body.Close()
	return readEvents(resp.Body, emit)
}

// readEvents parses server-sent events: "event:" and "data:" lines, ended by a blank line.
// Lines that start with ":" are keep-alive comments.
func readEvents(r io.Reader, emit func(Event) error) error {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 0, 64<<10), maxEventSize)
	var (
		name string
		data []byte
	)
	for sc.Scan() {
		line := sc.Text()
		switch {
		case line == "":
			if name == "" && data == nil {
				continue
			}
			if err := emit(Event{Name: name, Data: data}); err != nil {
				return err
			}
			name, data = "", nil
		case strings.HasPrefix(line, ":"):
		case strings.HasPrefix(line, "event:"):
			name = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
		case strings.HasPrefix(line, "data:"):
			if data != nil {
				data = append(data, '\n')
			}
			data = append(data, strings.TrimPrefix(strings.TrimPrefix(line, "data:"), " ")...)
		}
	}
	return sc.Err()
}
