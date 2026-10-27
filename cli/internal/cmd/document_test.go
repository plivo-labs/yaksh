package cmd

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestReadDocumentResolvesYAMLAndRefusesWhatItCannotSend(t *testing.T) {
	tests := []struct {
		name, file, want, wantErr string
	}{
		{name: "merge key", file: "<<: {category: edge_case}\nname: Refund\n",
			want: `{"category":"edge_case","name":"Refund"}`},
		{name: "alias", file: "data_sets:\n  - {name: A, agent_data: &clinic [{name: Clinic, value: Maple Dental}]}\n  - {name: B, agent_data: *clinic}\n",
			want: `{"data_sets":[{"agent_data":[{"name":"Clinic","value":"Maple Dental"}],"name":"A"},{"agent_data":[{"name":"Clinic","value":"Maple Dental"}],"name":"B"}]}`},
		{name: "JSON as it is", file: `{"name": "😀 Booking", "count": 2}`,
			want: `{"name": "😀 Booking", "count": 2}`},
		{name: "alias of itself", file: "criteria: &x [*x]\n", wantErr: "contains itself"},
		{name: "key that is not a name", file: "null: x\n<<:\n  ? [a]\n  : b\n", wantErr: "line 3: a key must be a name"},
		{name: "key given twice", file: "name: A\nname: B\n", wantErr: `mapping key "name" already defined at line 1`},
		{name: "empty", file: "# no scenario yet\n", wantErr: "is empty"},
		{name: "two documents", file: "name: A\n---\nname: B\n", wantErr: "more than one document"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "scenario.yaml")
			if err := os.WriteFile(path, []byte(tt.file), 0o600); err != nil {
				t.Fatal(err)
			}

			got, err := readDocument(path)

			if tt.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), tt.wantErr) {
					t.Fatalf("got %s, err = %v; want an error with %q", got, err, tt.wantErr)
				}
				return
			}
			if err != nil || string(got) != tt.want {
				t.Fatalf("got %s, err = %v; want %s", got, err, tt.want)
			}
		})
	}
}
