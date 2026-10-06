import { Plus } from "lucide-react";
import { type ReactElement, type ReactNode, type SubmitEvent, useState } from "react";
import { useNavigate } from "react-router";

import { BackgroundNoiseField } from "@/components/background-noise-field";
import { PersonaSelect } from "@/components/persona-select";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useDefaults, useScenarios, useStartConversation } from "@/lib/queries";
import type { AgentSummary, BackgroundNoise } from "@/lib/types";
import { ScenarioDialog } from "@/pages/scenario-dialog";

export function StartCallDialog({
  agents,
  agentId: presetAgent = "",
  scenarioId: presetScenario = "",
  render,
  children,
}: {
  agents: AgentSummary[];
  agentId?: string;
  scenarioId?: string;
  render: ReactElement;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [agentId, setAgentId] = useState(presetAgent);
  const [personaId, setPersonaId] = useState("");
  const [scenarioId, setScenarioId] = useState(presetScenario);
  const [creating, setCreating] = useState(false);
  /** Null plays the persona's own setting. */
  const [noise, setNoise] = useState<BackgroundNoise | null>(null);
  /** Null until the user types: the field then shows the server's default. */
  const [maxDuration, setMaxDuration] = useState<string | null>(null);
  const [maxTurns, setMaxTurns] = useState<string | null>(null);
  const defaults = useDefaults();
  const durationText = maxDuration ?? String(defaults.data?.max_duration_s ?? "");
  const turnsText = maxTurns ?? String(defaults.data?.max_turns ?? "");
  const start = useStartConversation();
  const navigate = useNavigate();
  const chosenAgent = agents.find((agent) => agent.id === agentId) ?? agents[0];
  const chosen = chosenAgent?.id ?? "";
  const scenarios = useScenarios(chosen, open);
  const selectedScenario =
    scenarios.data?.find((scenario) => scenario.id === scenarioId) ?? scenarios.data?.[0];
  const chosenScenario = selectedScenario?.id ?? "";
  const chosenPersona = personaId || selectedScenario?.persona_id || "";
  /** A new agent or scenario brings its own persona, so an earlier pick no longer applies. */
  const pickScenario = (id: string) => {
    setScenarioId(id);
    setPersonaId("");
  };
  const scenarioItems = (scenarios.data ?? []).map((scenario) => ({
    value: scenario.id,
    label: scenario.name,
  }));
  const agentItems = agents.map((agent) => ({ value: agent.id, label: agent.name }));
  const duration = durationText.trim() === "" ? null : Number(durationText);
  const turns = turnsText.trim() === "" ? null : Number(turnsText);
  const turnsOk = turns === null || (Number.isInteger(turns) && turns >= 1 && turns <= 100);
  const durationOk =
    duration === null || (Number.isInteger(duration) && duration >= 10 && duration <= 1800);

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    start.mutate(
      {
        agent_id: chosen,
        persona_id: chosenPersona,
        scenario_id: chosenScenario,
        ...(duration !== null && { max_duration_s: duration }),
        ...(turns !== null && { max_turns: turns }),
        ...(noise && { background_noise: noise }),
      },
      { onSuccess: (conversation) => navigate(`/conversations/${conversation.id}`) },
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={render}>{children}</DialogTrigger>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle>Start a conversation</DialogTitle>
          <DialogDescription>
            {chosenAgent?.direction === "outbound"
              ? "Yaksha asks the agent to call, then answers as the persona and follows the scenario."
              : "Yaksha calls the agent as the persona and follows the scenario."}
          </DialogDescription>
        </DialogHeader>
        <form
          id="start-form"
          onSubmit={submit}
          className="min-h-0 flex-1 overflow-y-auto px-6 py-1"
        >
          <FieldGroup className="pb-6">
            <Field>
              <FieldLabel htmlFor="agent">Agent</FieldLabel>
              <Select
                items={agentItems}
                value={chosen}
                onValueChange={(value) => {
                  setAgentId(value ?? "");
                  setPersonaId("");
                }}
              >
                <SelectTrigger id="agent" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {agentItems.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor="scenario">Scenario</FieldLabel>
              <div className="flex gap-2">
                <Select
                  items={scenarioItems}
                  value={chosenScenario}
                  onValueChange={(value) => pickScenario(value ?? "")}
                  disabled={scenarioItems.length === 0}
                >
                  <SelectTrigger id="scenario" className="min-w-0 flex-1">
                    <SelectValue
                      placeholder={
                        scenarios.isError
                          ? "Could not load scenarios"
                          : scenarios.isPending
                            ? "Loading scenarios"
                            : "No scenarios yet"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {scenarioItems.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!chosen}
                  onClick={() => setCreating(true)}
                >
                  <Plus />
                  New scenario
                </Button>
              </div>
              {selectedScenario && (
                <FieldDescription className="line-clamp-2">
                  {selectedScenario.goal}
                </FieldDescription>
              )}
              {scenarios.isError && <FieldError>{scenarios.error.message}</FieldError>}
            </Field>
            <Field>
              <FieldLabel htmlFor="persona">Persona</FieldLabel>
              <PersonaSelect id="persona" value={chosenPersona} onValueChange={setPersonaId} />
            </Field>
            <BackgroundNoiseField
              id="noise"
              value={noise}
              onChange={setNoise}
              inherit="Persona's setting"
            />
            <Field>
              <FieldLabel htmlFor="max_duration">Time limit</FieldLabel>
              <div className="flex items-center gap-2">
                <Input
                  id="max_duration"
                  type="number"
                  inputMode="numeric"
                  min={10}
                  max={1800}
                  placeholder="Default"
                  aria-invalid={!durationOk}
                  aria-describedby="max_duration_hint"
                  value={durationText}
                  onChange={(event) => setMaxDuration(event.target.value)}
                  className="w-24 tabular-nums"
                />
                <span className="text-p-400 text-muted-foreground">seconds</span>
              </div>
              {durationOk ? (
                <FieldDescription id="max_duration_hint">
                  Counts from when the call connects. Empty uses the server default.
                </FieldDescription>
              ) : (
                <FieldError id="max_duration_hint">
                  Enter a whole number from 10 to 1800, or none.
                </FieldError>
              )}
            </Field>
            <Field>
              <FieldLabel htmlFor="max_turns">Turn limit</FieldLabel>
              <div className="flex items-center gap-2">
                <Input
                  id="max_turns"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={100}
                  placeholder="Default"
                  aria-invalid={!turnsOk}
                  aria-describedby="max_turns_hint"
                  value={turnsText}
                  onChange={(event) => setMaxTurns(event.target.value)}
                  className="w-24 tabular-nums"
                />
                <span className="text-p-400 text-muted-foreground">turns</span>
              </div>
              {turnsOk ? (
                <FieldDescription id="max_turns_hint">
                  The caller answers the agent this many times, then says goodbye. Empty uses the
                  server default.
                </FieldDescription>
              ) : (
                <FieldError id="max_turns_hint">
                  Enter a whole number from 1 to 100, or none.
                </FieldError>
              )}
            </Field>
          </FieldGroup>
        </form>
        {start.error && <FieldError className="px-6 pb-3">{start.error.message}</FieldError>}
        <DialogFooter className="border-t px-6 py-4">
          <DialogClose render={<Button type="button" variant="ghost" />}>Cancel</DialogClose>
          <Button
            type="submit"
            form="start-form"
            disabled={start.isPending || !chosen || !chosenScenario || !durationOk || !turnsOk}
          >
            {start.isPending && <Spinner />}
            Start call
          </Button>
        </DialogFooter>
        {creating && chosenAgent && (
          <ScenarioDialog
            agent={chosenAgent}
            onSaved={(scenario) => pickScenario(scenario.id)}
            onClosed={() => setCreating(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
