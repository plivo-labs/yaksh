package cmd

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/plivo-labs/yaksh/cli/internal/update"
)

// fakeReleases serves GitHub's list of releases, two to a page, and the files of each release.
// Each release holds a binary whose content is "yaksh <version>".
type fakeReleases struct {
	update.Releases
	lists   atomic.Int32
	corrupt atomic.Bool
}

func newFakeReleases(t *testing.T, tags ...string) *fakeReleases {
	t.Helper()
	f := &fakeReleases{}
	archive := fmt.Sprintf("yaksh_%s_%s.tar.gz", runtime.GOOS, runtime.GOARCH)
	mux := http.NewServeMux()
	mux.HandleFunc("GET /releases", func(w http.ResponseWriter, r *http.Request) {
		f.lists.Add(1)
		page, _ := strconv.Atoi(r.URL.Query().Get("page"))
		start := min(max(page-1, 0)*2, len(tags))
		end := min(start+2, len(tags))
		if end < len(tags) {
			w.Header().Set("Link", fmt.Sprintf(`<http://%s/releases?page=%d>; rel="next"`, r.Host, max(page, 1)+1))
		}
		list := []map[string]any{}
		for _, tag := range tags[start:end] {
			list = append(list, map[string]any{"tag_name": tag, "prerelease": strings.Contains(tag, "-")})
		}
		json.NewEncoder(w).Encode(list)
	})
	mux.HandleFunc("GET /download/{tag}/{file}", func(w http.ResponseWriter, r *http.Request) {
		data := tarGz(t, "yaksh", "yaksh "+strings.TrimPrefix(r.PathValue("tag"), "v"))
		switch r.PathValue("file") {
		case "checksums.txt":
			sum := sha256.Sum256(data)
			fmt.Fprintf(w, "%s  %s\n", hex.EncodeToString(sum[:]), archive)
		case archive:
			if f.corrupt.Load() {
				data = append(data, 0)
			}
			w.Write(data)
		default:
			http.NotFound(w, r)
		}
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	f.Releases = update.Releases{List: srv.URL + "/releases", Download: srv.URL + "/download", Client: srv.Client()}
	return f
}

func tarGz(t *testing.T, name, content string) []byte {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	if err := tw.WriteHeader(&tar.Header{Name: name, Mode: 0o755, Size: int64(len(content)), Typeflag: tar.TypeReg}); err != nil {
		t.Fatal(err)
	}
	tw.Write([]byte(content))
	tw.Close()
	gz.Close()
	return buf.Bytes()
}

func serverAt(t *testing.T, version string) *fakeAPI {
	return newFakeAPI(t, map[string]http.HandlerFunc{
		"GET /api/v1/health": reply(200, `{"status":"ok","version":"`+version+`"}`),
		"GET /api/v1/agents": reply(200, `{"items":[]}`),
	})
}

// errRestarted stands in for the exec that ends the process in the binary.
var errRestarted = errors.New("restarted")

// recordRestart makes a restart record what is in the binary it would start.
func recordRestart(t *testing.T, a *app) *string {
	var started string
	a.restart = func(exe string) error {
		data, err := os.ReadFile(exe)
		if err != nil {
			t.Fatal(err)
		}
		started = string(data)
		return errRestarted
	}
	return &started
}

func TestTheCLIUpdatesToTheServersMinorVersionAndStartsAgain(t *testing.T) {
	for name, tt := range map[string]struct{ cli, server, want string }{
		"server is newer": {"0.1.4", "0.3.1", "yaksh 0.3.2"},
		"server is older": {"0.4.0", "0.3.0", "yaksh 0.3.2"},
	} {
		t.Run(name, func(t *testing.T) {
			f := serverAt(t, tt.server)
			a := testApp(t, tt.cli, against(f), newFakeReleases(t, "v0.1.4", "v0.3.0", "v0.3.2", "v0.3.3-rc.1", "v0.4.0"))
			started := recordRestart(t, a)

			code, _, stderr := execute(a, context.Background(), "", "agent", "list")

			if code != 1 || *started != tt.want || !strings.Contains(stderr, "to match the server "+tt.server) {
				t.Fatalf("code = %d, started %q, stderr = %q", code, *started, stderr)
			}
			if n := len(f.requests("GET", "/api/v1/agents")); n != 0 {
				t.Fatalf("the old binary sent the command: %d requests", n)
			}
		})
	}
}

func TestTheCLIRunsTheCommandWhenItCannotMatchTheServer(t *testing.T) {
	f := serverAt(t, "0.5.0")
	a := testApp(t, "0.1.0", against(f), newFakeReleases(t, "v0.1.0", "v0.5.0-rc.1"))

	code, _, stderr := execute(a, context.Background(), "", "agent", "list")

	if code != 0 || !strings.Contains(stderr, "no CLI release matches the server") {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	if n := len(f.requests("GET", "/api/v1/agents")); n != 1 {
		t.Fatalf("agents requests = %d, want 1", n)
	}
}

func TestTheCLIKeepsItsBinaryWhenTheDownloadDoesNotMatchItsChecksum(t *testing.T) {
	f := serverAt(t, "0.2.0")
	releases := newFakeReleases(t, "v0.2.0")
	releases.corrupt.Store(true)
	a := testApp(t, "0.1.0", against(f), releases)
	exe, _ := a.executable()

	code, _, stderr := execute(a, context.Background(), "", "agent", "list")

	data, _ := os.ReadFile(exe)
	if code != 0 || string(data) != "old binary" || !strings.Contains(stderr, "does not match its checksum") {
		t.Fatalf("code = %d, binary = %q, stderr = %q", code, data, stderr)
	}
}

func TestTheCLILooksForANewerPatchOnceADay(t *testing.T) {
	f := serverAt(t, "0.2.0")
	vars := against(f)
	vars["HOME"] = t.TempDir()
	releases := newFakeReleases(t, "v0.2.0", "v0.2.3")

	a := testApp(t, "0.2.1", vars, releases)
	started := recordRestart(t, a)
	if code, _, stderr := execute(a, context.Background(), "", "agent", "list"); *started != "yaksh 0.2.3" {
		t.Fatalf("first command: code = %d, started %q, stderr = %q", code, *started, stderr)
	}

	a = testApp(t, "0.2.1", vars, releases)
	if code, _, stderr := execute(a, context.Background(), "", "agent", "list"); code != 0 || stderr != "" {
		t.Fatalf("second command: code = %d, stderr = %q", code, stderr)
	}
	if n := releases.lists.Load(); n != 1 {
		t.Fatalf("the CLI read the releases %d times, want 1", n)
	}

	stamp := filepath.Join(vars["HOME"], ".config", "yaksh", "update-check")
	if err := os.WriteFile(stamp, []byte(time.Now().Add(-25*time.Hour).Format(time.RFC3339)), 0o600); err != nil {
		t.Fatal(err)
	}
	a = testApp(t, "0.2.1", vars, releases)
	started = recordRestart(t, a)
	if code, _, _ := execute(a, context.Background(), "", "agent", "list"); *started != "yaksh 0.2.3" {
		t.Fatalf("a day later: code = %d, started %q", code, *started)
	}
}

func TestTheCLIDoesNotUpdate(t *testing.T) {
	for name, tt := range map[string]struct {
		version string
		vars    map[string]string
		args    []string
	}{
		"a build from source":             {"dev", nil, []string{"agent", "list"}},
		"after an update":                 {"0.1.0", map[string]string{updatedVar: "1"}, []string{"agent", "list"}},
		"for a command of the auth group": {"0.1.0", nil, []string{"auth", "status"}},
	} {
		t.Run(name, func(t *testing.T) {
			f := serverAt(t, "0.2.0")
			vars := against(f)
			for k, v := range tt.vars {
				vars[k] = v
			}
			releases := newFakeReleases(t, "v0.2.0")
			a := testApp(t, tt.version, vars, releases)

			code, _, stderr := execute(a, context.Background(), "", tt.args...)

			if code != 0 || stderr != "" || releases.lists.Load() != 0 {
				t.Fatalf("code = %d, stderr = %q, release reads = %d", code, stderr, releases.lists.Load())
			}
		})
	}
}
