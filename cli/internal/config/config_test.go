package config

import (
	"os"
	"path/filepath"
	"testing"
)

func env(vars map[string]string) func(string) string {
	return func(key string) string { return vars[key] }
}

func writeConfig(t *testing.T, home, content string) {
	t.Helper()
	path := filepath.Join(home, ".config", "truman", "config.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestLoad(t *testing.T) {
	saved := `{"server": "https://saved.example.com", "token": "saved-token"}`
	tests := []struct {
		name string
		file string
		vars map[string]string
		want Settings
	}{
		{name: "nothing", want: Settings{}},
		{name: "file only", file: saved, want: Settings{"https://saved.example.com", "saved-token"}},
		{
			name: "environment wins", file: saved,
			vars: map[string]string{"TRUMAN_URL": "http://localhost:8000", "TRUMAN_API_TOKEN": "env-token"},
			want: Settings{"http://localhost:8000", "env-token"},
		},
		{
			name: "environment fills one value", file: saved,
			vars: map[string]string{"TRUMAN_API_TOKEN": "env-token"},
			want: Settings{"https://saved.example.com", "env-token"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			home := t.TempDir()
			if tt.file != "" {
				writeConfig(t, home, tt.file)
			}
			vars := map[string]string{"HOME": home}
			for k, v := range tt.vars {
				vars[k] = v
			}
			got, err := Load(env(vars))
			if err != nil || got != tt.want {
				t.Fatalf("Load = %+v, %v; want %+v", got, err, tt.want)
			}
		})
	}
}

func TestLoadRejectsABrokenFile(t *testing.T) {
	home := t.TempDir()
	writeConfig(t, home, "{not json")
	if _, err := Load(env(map[string]string{"HOME": home})); err == nil {
		t.Fatal("Load accepted a file that is not JSON")
	}
}

func TestPath(t *testing.T) {
	got, err := Path(env(map[string]string{"XDG_CONFIG_HOME": "/xdg", "HOME": "/home/u"}))
	if err != nil || got != filepath.Join("/xdg", "truman", "config.json") {
		t.Fatalf("Path = %q, %v", got, err)
	}
	if _, err := Path(env(nil)); err == nil {
		t.Fatal("Path worked with no HOME and no XDG_CONFIG_HOME")
	}
}
