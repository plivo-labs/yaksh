package cmd

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestScenarioCreateSendsEachValueAsTheFileWritesIt(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/agents/{id}/scenarios": reply(201, `{"id":"`+scenA+`"}`),
	})
	file := filepath.Join(t.TempDir(), "scenario.yaml")
	document := `name: Move to a weekday morning
persona_id: ` + personaID + `
instructions: >
  You want to move your appointment.
  Once the agent confirms the new time, say goodbye.
first_words: ~
data_sets:
  - name: Priya
    known_facts:
      - {name: Date of birth, value: 1988-03-14}
      - {name: Member code, value: 0042}
      - {name: Phone, value: +14155550100}
criteria:
  - Reads back {{Date of birth}}.
`
	if err := os.WriteFile(file, []byte(document), 0o600); err != nil {
		t.Fatal(err)
	}

	code, stdout, stderr := run(t, context.Background(), against(f), "", "scenario", "create", "--agent", agentID, "-f", file)

	if code != 0 || stderr != "" || !strings.Contains(stdout, scenA) {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", code, stdout, stderr)
	}
	want := `{"criteria":["Reads back {{Date of birth}}."],"data_sets":[{"known_facts":[` +
		`{"name":"Date of birth","value":"1988-03-14"},{"name":"Member code","value":"0042"},{"name":"Phone","value":"+14155550100"}],` +
		`"name":"Priya"}],"first_words":null,` +
		`"instructions":"You want to move your appointment. Once the agent confirms the new time, say goodbye.\n",` +
		`"name":"Move to a weekday morning","persona_id":"` + personaID + `"}`
	if sent := string(f.requests("POST", "/api/v1/agents/"+agentID+"/scenarios")[0].body); sent != want {
		t.Fatalf("sent %s\nwant %s", sent, want)
	}
}

func TestScenarioUpdateSendsOnlyTheFieldsOfTheFile(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{"PATCH /api/v1/scenarios/{id}": reply(200, `{"id":"`+scenA+`"}`)})
	file := filepath.Join(t.TempDir(), "scenario.json")
	if err := os.WriteFile(file, []byte(`{"criteria": ["Asks for the date of birth."]}`), 0o600); err != nil {
		t.Fatal(err)
	}

	code, _, stderr := run(t, context.Background(), against(f), "", "scenario", "update", scenA, "-f", file)

	sent := f.requests("PATCH", "/api/v1/scenarios/"+scenA)
	if code != 0 || len(sent) != 1 || string(sent[0].body) != `{"criteria": ["Asks for the date of birth."]}` {
		t.Fatalf("code = %d, stderr = %q, sent = %q", code, stderr, sent)
	}
}

func generationStream(finished string) string {
	stream := ": ping\n\n" +
		`event: started` + "\n" + `data: {"generation_id":"` + genID + `"}` + "\n\n" +
		`event: planned` + "\n" + `data: {"count":2}` + "\n\n" +
		`event: scenario` + "\n" + `data: {"id":"` + scenA + `","name":"Move a booking"}` + "\n\n" +
		`event: dropped` + "\n" + `data: {"reason":"it tests the same thing as another scenario"}` + "\n\n"
	if finished != "" {
		stream += "event: finished\ndata: " + finished + "\n\n"
	}
	return stream
}

func TestScenarioGeneratePrintsTheScenariosThatItSaved(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		// The stream stays open after the finished event, until the command closes it.
		"POST /api/v1/agents/{id}/scenarios/generate": func(w http.ResponseWriter, r *http.Request) {
			w.Write([]byte(generationStream(`{"status":"done","saved":1,"dropped":1,"error":null}`)))
			w.(http.Flusher).Flush()
			<-r.Context().Done()
		},
	})

	code, stdout, stderr := run(t, context.Background(), against(f), "",
		"scenario", "generate", "--agent", agentID, "--persona", personaID, "--count", "2")

	if code != 0 {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	if sent := string(f.requests("POST", "/api/v1/agents/"+agentID+"/scenarios/generate")[0].body); sent != `{"count":2,"persona_ids":["`+personaID+`"]}` {
		t.Fatalf("sent %s", sent)
	}
	var printed struct {
		GenerationID string `json:"generation_id"`
		Status       string `json:"status"`
		Scenarios    []struct {
			ID string `json:"id"`
		} `json:"scenarios"`
	}
	if err := json.Unmarshal([]byte(stdout), &printed); err != nil || printed.GenerationID != genID ||
		printed.Status != "done" || len(printed.Scenarios) != 1 || printed.Scenarios[0].ID != scenA {
		t.Fatalf("err = %v, stdout = %q", err, stdout)
	}
	for _, line := range []string{
		"saved scenario " + scenA + ": Move a booking",
		"dropped a scenario: it tests the same thing as another scenario",
		"generation " + genID + " done: 1 saved, 1 dropped",
	} {
		if !strings.Contains(stderr, line) {
			t.Fatalf("stderr = %q, want %q", stderr, line)
		}
	}
}

func TestScenarioGenerateKeepsAGenerationIDThatIsNotAUUIDOutOfTheNextCommand(t *testing.T) {
	f := newFakeAPI(t, map[string]http.HandlerFunc{
		"POST /api/v1/agents/{id}/scenarios/generate": reply(200,
			"event: started\ndata: {\"generation_id\":\"x; rm -rf ~\"}\n\n"),
	})

	code, _, stderr := run(t, context.Background(), against(f), "", "scenario", "generate", "--agent", agentID, "--persona", personaID)

	if code != 1 || strings.Contains(stderr, "rm -rf") ||
		!strings.Contains(stderr, "next: yaksh scenario list --agent "+agentID+"\n") {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
}

func TestScenarioGenerateFailsUnlessTheGenerationIsDone(t *testing.T) {
	tests := []struct {
		name, finished, want string
	}{
		{"failed", `{"status":"failed","saved":1,"dropped":1,"error":"the scenario writing model timed out"}`,
			"error: generation " + genID + " failed: 1 saved, 1 dropped: the scenario writing model timed out"},
		{"cut off", "", "next: yaksh scenario list --agent " + agentID + " --generation " + genID},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			f := newFakeAPI(t, map[string]http.HandlerFunc{
				"POST /api/v1/agents/{id}/scenarios/generate": reply(200, generationStream(tt.finished)),
			})

			code, _, stderr := run(t, context.Background(), against(f), "", "scenario", "generate", "--agent", agentID, "--persona", personaID)

			if code != 1 || !strings.Contains(stderr, tt.want) {
				t.Fatalf("code = %d, stderr = %q, want %q", code, stderr, tt.want)
			}
		})
	}
}
