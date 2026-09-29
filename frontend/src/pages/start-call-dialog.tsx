import { Plus } from "lucide-react";
import { type ReactElement, type ReactNode, type SubmitEvent, useState } from "react";
import { useNavigate } from "react-router";

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
import { usePersonas, useScenarios, useStartConversation } from "@/lib/queries";
import type { AgentSummary } from "@/lib/types";
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
  const [maxDuration, setMaxDuration] = useState("300");
  const personas = usePersonas();
  const start = useStartConversation();
  const navigate = useNavigate();
  const chosenAgent = agents.find((agent) => agent.id === agentId) ?? agents[0];
  const chosen = chosenAgent?.id ?? "";
  const chosenPersona = personaId || personas.data?.[0]?.id || "";
  const scenarios = useScenarios(chosen, open);
  const selectedScenario =
    scenarios.data?.find((scenario) => scenario.id === scenarioId) ?? scenarios.data?.[0];
  const chosenScenario = selectedScenario?.id ?? "";
  const scenarioItems = (scenarios.data ?? []).map((scenario) => ({
    value: scenario.id,
    label: scenario.name,
  }));
  const agentItems = agents.map((agent) => ({ value: agent.id, label: agent.name }));
  const personaItems = (personas.data ?? []).map((persona) => ({
    value: persona.id,
    label: persona.name,
  }));
  const duration = Number(maxDuration);
  const durationOk = Number.isInteger(duration) && duration >= 10 && duration <= 1800;

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    start.mutate(
      {
        agent_id: chosen,
        persona_id: chosenPersona,
        scenario_id: chosenScenario,
        max_duration_s: duration,
      },
      { onSuccess: (conversation) => navigate(`/conversations/${conversation.id}`) },
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={render}>{children}</DialogTrigger>
      <DialogContent className="gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle>Start a conversation</DialogTitle>
          <DialogDescription>
            {chosenAgent?.direction === "outbound"
              ? "Truman asks the agent to call, then answers as the persona and follows the scenario."
              : "Truman calls the agent as the persona and follows the scenario."}
          </DialogDescription>
        </DialogHeader>
        <form id="start-form" onSubmit={submit} className="px-6 pb-6">
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="agent">Agent</FieldLabel>
              <Select
                items={agentItems}
                value={chosen}
                onValueChange={(value) => setAgentId(value ?? "")}
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
                  onValueChange={(value) => setScenarioId(value ?? "")}
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
              <Select
                items={personaItems}
                value={chosenPersona}
                onValueChange={(value) => setPersonaId(value ?? "")}
              >
                <SelectTrigger id="persona" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {personaItems.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor="max_duration">Time limit</FieldLabel>
              <div className="flex items-center gap-2">
                <Input
                  id="max_duration"
                  type="number"
                  inputMode="numeric"
                  min={10}
                  max={1800}
                  aria-invalid={!durationOk}
                  aria-describedby="max_duration_hint"
                  value={maxDuration}
                  onChange={(event) => setMaxDuration(event.target.value)}
                  className="w-24 tabular-nums"
                />
                <span className="text-sm text-muted-foreground">seconds</span>
              </div>
              <FieldDescription id="max_duration_hint">
                {durationOk
                  ? "Counts from when the call connects."
                  : "Enter a whole number from 10 to 1800."}
              </FieldDescription>
            </Field>
          </FieldGroup>
        </form>
        {start.error && <FieldError className="px-6 pb-3">{start.error.message}</FieldError>}
        <DialogFooter className="border-t px-6 py-4">
          <DialogClose render={<Button type="button" variant="ghost" />}>Cancel</DialogClose>
          <Button
            type="submit"
            form="start-form"
            disabled={
              start.isPending || !chosen || !chosenPersona || !chosenScenario || !durationOk
            }
          >
            {start.isPending && <Spinner />}
            Start call
          </Button>
        </DialogFooter>
        {creating && chosenAgent && (
          <ScenarioDialog
            agent={chosenAgent}
            onSaved={(scenario) => setScenarioId(scenario.id)}
            onClosed={() => setCreating(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
