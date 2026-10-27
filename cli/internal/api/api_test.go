package api

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func respond(status int, body string) *http.Response {
	rec := httptest.NewRecorder()
	rec.WriteHeader(status)
	rec.WriteString(body)
	return rec.Result()
}

func TestBodyReportsAnErrorBodyWithoutTheErrorShape(t *testing.T) {
	tests := []struct {
		name   string
		status int
		body   string
		want   Error
	}{
		{name: "plain text", status: 500, body: "Internal Server Error\n", want: Error{Status: 500, Message: "Internal Server Error"}},
		{name: "empty", status: 502, body: "", want: Error{Status: 502, Message: "no details from the server"}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := Body(respond(tt.status, tt.body), nil)
			var apiErr *Error
			if !errors.As(err, &apiErr) || *apiErr != tt.want {
				t.Fatalf("error = %#v, want %#v", err, tt.want)
			}
		})
	}
}

// slowBody sends its headers with status at once, and its body only after a minute.
func slowBody(t *testing.T, status int) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
		w.(http.Flusher).Flush()
		select {
		case <-time.After(time.Minute):
			w.Write([]byte(`{"status":"ok","version":"0.1.0"}`))
		case <-r.Context().Done():
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestABodyThatStallsFailsTheRequest(t *testing.T) {
	old := requestTimeout
	requestTimeout = 50 * time.Millisecond
	t.Cleanup(func() { requestTimeout = old })
	tests := []struct {
		name      string
		newClient func(server, token, userAgent string) (*Client, error)
		status    int
	}{
		{"a response", New, http.StatusOK},
		{"the error of a stream", NewStream, http.StatusServiceUnavailable},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, err := tt.newClient(slowBody(t, tt.status).URL, "t", "test")
			if err != nil {
				t.Fatal(err)
			}

			start := time.Now()
			_, err = Body(c.HealthApiV1HealthGet(context.Background()))

			if err == nil || time.Since(start) > 5*time.Second {
				t.Fatalf("err = %v after %s; want an error before the body came", err, time.Since(start))
			}
		})
	}
}

func TestNewSendsTokenAndUserAgent(t *testing.T) {
	var auth, agent string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth, agent = r.Header.Get("Authorization"), r.Header.Get("User-Agent")
		w.Write([]byte(`{"status":"ok","version":"0.1.0"}`))
	}))
	defer srv.Close()

	c, err := New(srv.URL+"/", "secret", "yaksh-cli/test")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Body(c.HealthApiV1HealthGet(context.Background())); err != nil {
		t.Fatal(err)
	}
	if auth != "Bearer secret" || agent != "yaksh-cli/test" {
		t.Fatalf("Authorization = %q, User-Agent = %q", auth, agent)
	}
}
