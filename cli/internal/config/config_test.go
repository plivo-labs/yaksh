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
		want Loaded
	}{
		{name: "nothing", want: Loaded{ServerFrom: Unset, TokenFrom: Unset}},
		{
			name: "file only", file: saved,
			want: Loaded{Settings{"https://saved.example.com", "saved-token"}, FromFile, FromFile},
		},
		{
			name: "environment wins", file: saved,
			vars: map[string]string{"TRUMAN_URL": "http://localhost:8000", "TRUMAN_API_TOKEN": "env-token"},
			want: Loaded{Settings{"http://localhost:8000", "env-token"}, FromEnvironment, FromEnvironment},
		},
		{
			name: "environment sets one value", file: saved,
			vars: map[string]string{"TRUMAN_API_TOKEN": "env-token"},
			want: Loaded{Settings{"https://saved.example.com", "env-token"}, FromFile, FromEnvironment},
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

func TestLoadSkipsTheFileWhenTheEnvironmentSetsBoth(t *testing.T) {
	brokenHome := t.TempDir()
	writeConfig(t, brokenHome, "{not json")
	want := Loaded{Settings{"http://localhost:8000", "env-token"}, FromEnvironment, FromEnvironment}
	for name, home := range map[string]string{"broken file": brokenHome, "no HOME": ""} {
		t.Run(name, func(t *testing.T) {
			got, err := Load(env(map[string]string{
				"HOME": home, "TRUMAN_URL": "http://localhost:8000", "TRUMAN_API_TOKEN": "env-token",
			}))
			if err != nil || got != want {
				t.Fatalf("Load = %+v, %v; want %+v", got, err, want)
			}
		})
	}
}

func TestSaveThenLoadThenRemove(t *testing.T) {
	getenv := env(map[string]string{"HOME": t.TempDir()})
	want := Settings{Server: "https://truman.example.com", Token: "t0k"}

	if err := Save(getenv, want); err != nil {
		t.Fatal(err)
	}
	path, _ := Path(getenv)
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("saved file mode = %v, %v; want 0600", info.Mode().Perm(), err)
	}
	if got, err := Load(getenv); err != nil || got.Settings != want {
		t.Fatalf("Load after Save = %+v, %v", got, err)
	}
	if removed, err := Remove(getenv); !removed || err != nil {
		t.Fatalf("Remove = %v, %v; want true", removed, err)
	}
	if removed, err := Remove(getenv); removed || err != nil {
		t.Fatalf("second Remove = %v, %v; want false", removed, err)
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
