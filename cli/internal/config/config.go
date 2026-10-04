// Package config finds the Truman server and its API token. The environment variables
// TRUMAN_URL and TRUMAN_API_TOKEN win over the file that "truman auth login" saves.
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
)

// Settings are the server URL and the API token. Either can be empty.
type Settings struct {
	Server string `json:"server"`
	Token  string `json:"token"`
}

// Load reads the saved file, if there is one, then lets the environment override each value.
// getenv is os.Getenv outside tests.
func Load(getenv func(string) string) (Settings, error) {
	var s Settings
	path, err := Path(getenv)
	if err != nil {
		return s, err
	}
	data, err := os.ReadFile(path)
	switch {
	case errors.Is(err, fs.ErrNotExist):
	case err != nil:
		return s, fmt.Errorf("read %s: %w", path, err)
	default:
		if err := json.Unmarshal(data, &s); err != nil {
			return s, fmt.Errorf("read %s: %w", path, err)
		}
	}
	if v := getenv("TRUMAN_URL"); v != "" {
		s.Server = v
	}
	if v := getenv("TRUMAN_API_TOKEN"); v != "" {
		s.Token = v
	}
	return s, nil
}

// Path is the saved file: $XDG_CONFIG_HOME/truman/config.json, or ~/.config/truman/config.json
// when XDG_CONFIG_HOME is not set.
func Path(getenv func(string) string) (string, error) {
	dir := getenv("XDG_CONFIG_HOME")
	if dir == "" {
		home := getenv("HOME")
		if home == "" {
			return "", errors.New("HOME is not set")
		}
		dir = filepath.Join(home, ".config")
	}
	return filepath.Join(dir, "truman", "config.json"), nil
}
