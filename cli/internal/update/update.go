// Package update finds the CLI's releases on GitHub and replaces the running binary with one of
// them. docs/decisions/0018 says when the CLI updates itself.
package update

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
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"golang.org/x/mod/semver"
)

// Releases is where the releases are: a list in the shape of the GitHub API, and the base URL of
// the files of each release.
type Releases struct {
	List     string
	Download string
	Client   *http.Client
}

// GitHub returns the releases of plivo-labs/yaksh.
func GitHub(client *http.Client) Releases {
	return Releases{
		List:     "https://api.github.com/repos/plivo-labs/yaksh/releases?per_page=100",
		Download: "https://github.com/plivo-labs/yaksh/releases/download",
		Client:   client,
	}
}

// Line returns the major and minor version of a version such as "0.4.2", as "v0.4". It returns
// "" when version is not a semantic version, such as "dev".
func Line(version string) string {
	return semver.MajorMinor("v" + version)
}

// Newer reports whether version a is higher than version b.
func Newer(a, b string) bool {
	return semver.Compare("v"+a, "v"+b) > 0
}

// Newest returns the highest release of line, such as "v0.4", without the "v". It returns "" when
// line has no release. Drafts and prereleases do not count. It reads every page of the list.
func (r Releases) Newest(ctx context.Context, line string) (string, error) {
	newest := ""
	for url := r.List; url != ""; {
		body, header, err := r.fetch(ctx, url)
		if err != nil {
			return "", fmt.Errorf("read the list of releases: %w", err)
		}
		var releases []struct {
			Tag        string `json:"tag_name"`
			Draft      bool   `json:"draft"`
			Prerelease bool   `json:"prerelease"`
		}
		if err := json.Unmarshal(body, &releases); err != nil {
			return "", fmt.Errorf("read the list of releases: %w", err)
		}
		for _, rel := range releases {
			if rel.Draft || rel.Prerelease || semver.Prerelease(rel.Tag) != "" || semver.MajorMinor(rel.Tag) != line {
				continue
			}
			if newest == "" || semver.Compare(rel.Tag, newest) > 0 {
				newest = rel.Tag
			}
		}
		url = nextPage(header.Get("Link"))
	}
	return strings.TrimPrefix(newest, "v"), nil
}

// nextPage returns the URL with rel="next" in a Link header, or "" when there is none.
func nextPage(link string) string {
	for part := range strings.SplitSeq(link, ",") {
		target, params, ok := strings.Cut(part, ";")
		if ok && strings.Contains(params, `rel="next"`) {
			return strings.Trim(strings.TrimSpace(target), "<>")
		}
	}
	return ""
}

// Install downloads the archive of version for this OS and architecture, checks it against the
// release's checksums.txt, and replaces the file at exe with the binary in it. It writes a
// temporary file next to exe and renames it, so exe is always a whole binary.
func (r Releases) Install(ctx context.Context, version, exe string) error {
	base := fmt.Sprintf("%s/v%s/", strings.TrimRight(r.Download, "/"), version)
	archive := fmt.Sprintf("yaksh_%s_%s.tar.gz", runtime.GOOS, runtime.GOARCH)
	sums, err := r.get(ctx, base+"checksums.txt")
	if err != nil {
		return fmt.Errorf("download the checksums: %w", err)
	}
	want, err := checksum(sums, archive)
	if err != nil {
		return err
	}
	data, err := r.get(ctx, base+archive)
	if err != nil {
		return fmt.Errorf("download %s: %w", archive, err)
	}
	if got := sha256.Sum256(data); hex.EncodeToString(got[:]) != want {
		return fmt.Errorf("%s does not match its checksum", archive)
	}
	binary, err := extract(data, "yaksh")
	if err != nil {
		return fmt.Errorf("read %s: %w", archive, err)
	}
	return replace(exe, binary)
}

func (r Releases) get(ctx context.Context, url string) ([]byte, error) {
	body, _, err := r.fetch(ctx, url)
	return body, err
}

func (r Releases) fetch(ctx context.Context, url string) ([]byte, http.Header, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, nil, err
	}
	resp, err := r.Client.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, nil, fmt.Errorf("%s answered %s", url, resp.Status)
	}
	body, err := io.ReadAll(resp.Body)
	return body, resp.Header, err
}

// checksum finds the SHA-256 of name in a checksums.txt, where each line is "<hex>  <name>".
func checksum(sums []byte, name string) (string, error) {
	for line := range strings.Lines(string(sums)) {
		fields := strings.Fields(line)
		if len(fields) == 2 && fields[1] == name {
			return fields[0], nil
		}
	}
	return "", fmt.Errorf("the release has no checksum for %s", name)
}

// extract returns the file called name in a .tar.gz archive.
func extract(data []byte, name string) ([]byte, error) {
	gz, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	tr := tar.NewReader(gz)
	for {
		h, err := tr.Next()
		if errors.Is(err, io.EOF) {
			return nil, fmt.Errorf("no file %s in the archive", name)
		}
		if err != nil {
			return nil, err
		}
		if h.Typeflag == tar.TypeReg && filepath.Base(h.Name) == name {
			return io.ReadAll(tr)
		}
	}
}

func replace(exe string, binary []byte) error {
	tmp, err := os.CreateTemp(filepath.Dir(exe), ".yaksh-update-*")
	if err != nil {
		return fmt.Errorf("write next to %s: %w", exe, err)
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(binary); err != nil {
		tmp.Close()
		return fmt.Errorf("write next to %s: %w", exe, err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("write next to %s: %w", exe, err)
	}
	if err := os.Chmod(tmp.Name(), 0o755); err != nil {
		return err
	}
	if err := os.Rename(tmp.Name(), exe); err != nil {
		return fmt.Errorf("replace %s: %w", exe, err)
	}
	return nil
}
