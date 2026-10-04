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

func TestBody(t *testing.T) {
	tests := []struct {
		name    string
		status  int
		body    string
		want    string
		wantErr *Error
	}{
		{name: "ok", status: 200, body: `{"id":"a"}`, want: `{"id":"a"}`},
		{name: "accepted", status: 202, body: `{"id":"r"}`, want: `{"id":"r"}`},
		{name: "no content", status: 204, body: "", want: ""},
		{
			name: "server error shape", status: 404,
			body:    `{"error":{"code":"not_found","message":"agent 1 not found"}}`,
			wantErr: &Error{Status: 404, Code: "not_found", Message: "agent 1 not found"},
		},
		{
			name: "plain text 500", status: 500, body: "Internal Server Error\n",
			wantErr: &Error{Status: 500, Message: "Internal Server Error"},
		},
		{
			name: "empty error body", status: 502, body: "",
			wantErr: &Error{Status: 502, Message: "no details from the server"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := Body(respond(tt.status, tt.body), nil)
			if tt.wantErr != nil {
				var apiErr *Error
				if !errors.As(err, &apiErr) || *apiErr != *tt.wantErr {
					t.Fatalf("error = %#v, want %#v", err, tt.wantErr)
				}
				return
			}
			if err != nil || string(got) != tt.want {
				t.Fatalf("Body = %q, %v; want %q", got, err, tt.want)
			}
		})
	}
}

func TestBodyPassesCallErrors(t *testing.T) {
	callErr := errors.New("dial tcp: connection refused")
	if _, err := Body(nil, callErr); !errors.Is(err, callErr) {
		t.Fatalf("error = %v, want %v", err, callErr)
	}
}

// slowBody sends its headers at once and its body only after delay.
func slowBody(t *testing.T, delay time.Duration) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.(http.Flusher).Flush()
		select {
		case <-time.After(delay):
			w.Write([]byte(`{"status":"ok","version":"0.1.0"}`))
		case <-r.Context().Done():
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestABodyThatStallsFailsTheRequestButNotAStream(t *testing.T) {
	old := requestTimeout
	requestTimeout = 50 * time.Millisecond
	t.Cleanup(func() { requestTimeout = old })
	srv := slowBody(t, 200*time.Millisecond)
	c, err := New(srv.URL, "t", "test")
	if err != nil {
		t.Fatal(err)
	}

	if _, err := Body(c.HealthApiV1HealthGet(context.Background())); err == nil {
		t.Fatal("a body that stalled past the request timeout did not fail")
	}
	if body, err := Body(Stream(c).HealthApiV1HealthGet(context.Background())); err != nil || len(body) == 0 {
		t.Fatalf("Stream = %q, %v; want the body after the delay", body, err)
	}
}

func TestNewSendsTokenAndUserAgent(t *testing.T) {
	var auth, agent string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth, agent = r.Header.Get("Authorization"), r.Header.Get("User-Agent")
		w.Write([]byte(`{"status":"ok","version":"0.1.0"}`))
	}))
	defer srv.Close()

	c, err := New(srv.URL+"/", "secret", "truman-cli/test")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Body(c.HealthApiV1HealthGet(context.Background())); err != nil {
		t.Fatal(err)
	}
	if auth != "Bearer secret" || agent != "truman-cli/test" {
		t.Fatalf("Authorization = %q, User-Agent = %q", auth, agent)
	}
}
