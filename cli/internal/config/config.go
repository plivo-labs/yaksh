// Package config finds the Yaksh server and its API token. The environment variables
// YAKSH_URL and YAKSH_API_TOKEN win over the file that "yaksh auth login" saves.
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

// Origin is where Load found a value.
type Origin string

const (
	FromEnvironment Origin = "environment"
	FromFile        Origin = "file"
	Unset           Origin = "unset"
)

// Loaded is what Load found, and where each value came from.
type Loaded struct {
	Settings
	ServerFrom, TokenFrom Origin
}

// Load reads the saved file, if there is one, then lets the environment override each value.
// When the environment sets both values, Load does not read the file at all.
// getenv is os.Getenv outside tests.
func Load(getenv func(string) string) (Loaded, error) {
	server, token := getenv("YAKSH_URL"), getenv("YAKSH_API_TOKEN")
	if server != "" && token != "" {
		return Loaded{
			Settings:   Settings{Server: server, Token: token},
			ServerFrom: FromEnvironment,
			TokenFrom:  FromEnvironment,
		}, nil
	}
	l := Loaded{ServerFrom: Unset, TokenFrom: Unset}
	path, err := Path(getenv)
	if err != nil {
		return l, err
	}
	data, err := os.ReadFile(path)
	switch {
	case errors.Is(err, fs.ErrNotExist):
	case err != nil:
		return l, fmt.Errorf("read %s: %w", path, err)
	default:
		if err := json.Unmarshal(data, &l.Settings); err != nil {
			return l, fmt.Errorf("read %s: %w", path, err)
		}
	}
	if l.Server != "" {
		l.ServerFrom = FromFile
	}
	if l.Token != "" {
		l.TokenFrom = FromFile
	}
	if server != "" {
		l.Server, l.ServerFrom = server, FromEnvironment
	}
	if token != "" {
		l.Token, l.TokenFrom = token, FromEnvironment
	}
	return l, nil
}

// Save writes s to the file, readable by the user only. It writes a temporary file and renames
// it, so a crash never leaves half a file behind.
func Save(getenv func(string) string, s Settings) error {
	path, err := Path(getenv)
	if err != nil {
		return err
	}
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("create %s: %w", dir, err)
	}
	tmp, err := os.CreateTemp(dir, "config-*.json")
	if err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(append(data, '\n')); err != nil {
		tmp.Close()
		return fmt.Errorf("write %s: %w", path, err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	if err := os.Rename(tmp.Name(), path); err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	return nil
}

// Remove deletes the file. It reports false when there was no file.
func Remove(getenv func(string) string) (bool, error) {
	path, err := Path(getenv)
	if err != nil {
		return false, err
	}
	switch err := os.Remove(path); {
	case errors.Is(err, fs.ErrNotExist):
		return false, nil
	case err != nil:
		return false, fmt.Errorf("delete %s: %w", path, err)
	}
	return true, nil
}

// Path is the saved file: $XDG_CONFIG_HOME/yaksh/config.json, or ~/.config/yaksh/config.json
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
	return filepath.Join(dir, "yaksh", "config.json"), nil
}
