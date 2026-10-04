// Package api is the client for Truman's HTTP API: the code generated from openapi.json, and the
// request setup and error handling that every command shares.
package api

//go:generate go tool oapi-codegen -config oapi-codegen.yaml ../../openapi.json

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// requestTimeout bounds a whole request, body included, so a server that stalls at any point
// fails the command instead of hanging it. A test makes it short.
var requestTimeout = 2 * time.Minute

// headerTimeout bounds the wait for an event stream's headers; the stream itself has no limit.
const headerTimeout = time.Minute

// New returns a client for server that sends token as a bearer token on every request, each
// within requestTimeout. Use it instead of the generated NewClient, and Stream for event streams.
func New(server, token, userAgent string) (*Client, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.ResponseHeaderTimeout = headerTimeout
	return NewClient(
		strings.TrimRight(server, "/"),
		WithHTTPClient(&http.Client{Transport: transport, Timeout: requestTimeout}),
		WithRequestEditorFn(func(_ context.Context, req *http.Request) error {
			req.Header.Set("Authorization", "Bearer "+token)
			req.Header.Set("User-Agent", userAgent)
			return nil
		}),
	)
}

// Stream returns a copy of c whose requests have no overall time limit, for an event stream
// that stays open as long as a call lasts. Its headers still must come within headerTimeout.
func Stream(c *Client) *Client {
	s := *c
	if hc, ok := c.Client.(*http.Client); ok {
		unbounded := *hc
		unbounded.Timeout = 0
		s.Client = &unbounded
	}
	return &s
}

// Error is a response with a status that is not 2xx.
type Error struct {
	Status int
	// Code is the server's error code, such as "not_found", or empty when the body had none.
	Code    string
	Message string
}

func (e *Error) Error() string {
	return fmt.Sprintf("%d %s: %s", e.Status, http.StatusText(e.Status), e.Message)
}

// Body reads the response of a generated client call. It returns the raw body for a 2xx status,
// and an *Error with the server's message for any other status. Pass a call straight in:
// Body(client.GetRunApiV1RunsRunIdGet(ctx, id)).
func Body(resp *http.Response, err error) ([]byte, error) {
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read the response: %w", err)
	}
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return body, nil
	}
	return nil, responseError(resp.StatusCode, body)
}

// responseError reads the server's error shape, {"error": {"code", "message"}}. A body without
// it, such as the plain-text 500 of an unhandled server error, becomes the message as it is.
func responseError(status int, body []byte) *Error {
	var shape struct {
		Error struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if json.Unmarshal(body, &shape) == nil && shape.Error.Message != "" {
		return &Error{Status: status, Code: shape.Error.Code, Message: shape.Error.Message}
	}
	message := strings.TrimSpace(string(body))
	if message == "" {
		message = "no details from the server"
	}
	return &Error{Status: status, Message: message}
}
