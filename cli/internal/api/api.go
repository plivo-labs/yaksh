// Package api is the client for Yaksh's HTTP API: the code generated from openapi.json, and the
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

// New returns a client for server that sends token as a bearer token on every request, each
// within requestTimeout. Use it instead of the generated NewClient.
func New(server, token, userAgent string) (*Client, error) {
	return newClient(server, token, userAgent, &http.Client{Timeout: requestTimeout})
}

// NewStream is New with no time limit on the body, for a response that streams.
func NewStream(server, token, userAgent string) (*Client, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.ResponseHeaderTimeout = requestTimeout
	return newClient(server, token, userAgent, &http.Client{Transport: transport})
}

func newClient(server, token, userAgent string, httpClient *http.Client) (*Client, error) {
	return NewClient(
		strings.TrimRight(server, "/"),
		WithHTTPClient(httpClient),
		WithRequestEditorFn(func(_ context.Context, req *http.Request) error {
			req.Header.Set("Authorization", "Bearer "+token)
			req.Header.Set("User-Agent", userAgent)
			return nil
		}),
	)
}

// ServerVersion reads the server's version from its health route.
func (c *Client) ServerVersion(ctx context.Context) (string, error) {
	body, err := Body(c.HealthApiV1HealthGet(ctx))
	if err != nil {
		return "", err
	}
	var health HealthResponse
	if err := json.Unmarshal(body, &health); err != nil {
		return "", fmt.Errorf("read the server's version: %w", err)
	}
	return health.Version, nil
}

// Error is a response with a status that is not 2xx.
type Error struct {
	Status  int
	Message string
}

func (e *Error) Error() string {
	return fmt.Sprintf("%d %s: %s", e.Status, http.StatusText(e.Status), e.Message)
}

// Body reads the response of a generated client call. It returns the raw body for a 2xx status,
// and an *Error with the server's message for any other status. Pass a call straight in:
// Body(client.GetRunApiV1RunsRunIdGet(ctx, id)).
func Body(resp *http.Response, err error) ([]byte, error) {
	stream, err := Stream(resp, err)
	if err != nil {
		return nil, err
	}
	defer stream.Close()
	body, err := io.ReadAll(stream)
	if err != nil {
		return nil, fmt.Errorf("read the response: %w", err)
	}
	return body, nil
}

// Stream is Body for a response that streams: for a 2xx status, it returns the open body.
func Stream(resp *http.Response, err error) (io.ReadCloser, error) {
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return resp.Body, nil
	}
	defer resp.Body.Close()
	// A stream client sets no limit on the body.
	stop := time.AfterFunc(requestTimeout, func() { resp.Body.Close() })
	defer stop.Stop()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read the response: %w", err)
	}
	return nil, responseError(resp.StatusCode, body)
}

// responseError reads the message from the server's error shape, {"error": {"code", "message"}}.
// A body without it, such as the plain-text 500 of an unhandled server error, becomes the
// message as it is.
func responseError(status int, body []byte) *Error {
	var shape struct {
		Error struct {
			Message string `json:"message"`
		} `json:"error"`
	}
	if json.Unmarshal(body, &shape) == nil && shape.Error.Message != "" {
		return &Error{Status: status, Message: shape.Error.Message}
	}
	message := strings.TrimSpace(string(body))
	if message == "" {
		message = "no details from the server"
	}
	return &Error{Status: status, Message: message}
}
