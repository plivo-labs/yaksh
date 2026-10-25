import { Check, TriangleAlert } from "lucide-react";
import { type SubmitEvent, useState } from "react";

import {
  AnswersMenu,
  MixPersonas,
  NoVerdictNote,
  RunSettings,
  ScenarioCards,
} from "@/components/run-setup";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { DEFAULT_ANSWERING } from "@/lib/answering";
import { counted, runTitle } from "@/lib/format";
import { revealErrors } from "@/lib/forms";
import { useAgent, useAgents, usePersonas, useSaveSuite, useScenarios } from "@/lib/queries";
import { useRunSetup } from "@/lib/run-setup";
import {
  asEntry,
  cardsFrom,
  entryScenarios,
  playingEveryDataSet,
  startFromEntry,
  startFromRun,
  SUITE_CHANGED,
} from "@/lib/suites";
import {
  type AgentSummary,
  type AnsweredBy,
  type Run,
  type Suite,
  type SuiteEntry,
  type SuiteEntryRead,
  servedLanguages,
} from "@/lib/types";

/** Adds an agent to a suite, or edits one of its entries. With `copyRun`, which the run page
 * passes, the new entry starts as a copy of that run. */
export function SuiteEntryDialog({
  suite,
  entry,
  copyRun,
  onSaved,
  onClosed,
}: {
  suite: Suite;
  entry?: SuiteEntryRead;
  copyRun?: Run;
  onSaved?: () => void;
  onClosed: () => void;
}) {
  const [open, setOpen] = useState(true);
  // The suite as the dialog opened on it. A save sends its revision, so a change made since then
  // gets a 409 and is never overwritten.
  const [base] = useState(suite);
  const [agentId, setAgentId] = useState(entry?.agent_id ?? copyRun?.agent_id ?? "");
  const agents = useAgents();
  const agent = agents.data?.find((item) => item.id === agentId);
  const save = useSaveSuite(suite.id);

  const agentItems = (agents.data ?? []).map((item) => ({ value: item.id, label: item.name }));
  const stale = suite.revision !== base.revision && !save.isSuccess;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && !save.isPending && setOpen(false)}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="flex h-[min(760px,90vh)] flex-col gap-0 p-0 sm:max-w-5xl">
        <DialogHeader className="border-b px-6 py-5">
          <DialogTitle>{entry ? "Edit agent" : "Add an agent"}</DialogTitle>
          <DialogDescription>
            {copyRun
              ? `${suite.name}. A copy of ${runTitle(copyRun)}; the suite does not use its results.`
              : suite.name}
          </DialogDescription>
        </DialogHeader>
        {!entry && !copyRun && (
          <div className="border-b px-6 py-4">
            <Field className="max-w-md">
              <FieldLabel htmlFor="entry-agent">Agent</FieldLabel>
              <Select
                items={agentItems}
                value={agentId || null}
                onValueChange={(value) => value && setAgentId(value)}
              >
                <SelectTrigger id="entry-agent" className="w-full">
                  <SelectValue placeholder="Choose an agent" />
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
          </div>
        )}
        {agent === undefined ? (
          <p className="px-6 py-5 text-s-400 text-muted-foreground">
            {agents.isError
              ? `Could not load the agents: ${agents.error.message}`
              : agentId
                ? "Loading"
                : "Choose the agent to test."}
          </p>
        ) : (
          <EntryForm
            key={agent.id}
            agent={agent}
            entry={entry}
            copied={copyRun}
            pending={save.isPending}
            stale={stale}
            error={stale ? SUITE_CHANGED : save.error?.message}
            onCancel={() => setOpen(false)}
            onSave={(saved) =>
              save.mutate(
                {
                  revision: base.revision,
                  entries: entry
                    ? base.entries.map((other) =>
                        other.position === entry.position ? saved : asEntry(other),
                      )
                    : [...base.entries.map(asEntry), saved],
                },
                {
                  onSuccess: () => {
                    setOpen(false);
                    onSaved?.();
                  },
                },
              )
            }
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function EntryForm({
  agent,
  entry,
  copied,
  pending,
  stale,
  error,
  onCancel,
  onSave,
}: {
  agent: AgentSummary;
  entry?: SuiteEntryRead;
  copied?: Run;
  pending: boolean;
  /** The suite changed after the dialog opened, so a save would be refused. */
  stale: boolean;
  error?: string;
  onCancel: () => void;
  onSave: (entry: SuiteEntry) => void;
}) {
  const saved = entry && !Array.isArray(entry.scenarios) ? entry.scenarios : null;
  const setup = useRunSetup(agent, copied ? startFromRun(copied) : startFromEntry(entry, agent));
  const [mode, setMode] = useState<"all" | "choose">(
    copied || (entry && Array.isArray(entry.scenarios)) ? "choose" : "all",
  );
  const [answers, setAnswers] = useState<AnsweredBy[]>(saved?.answered_by ?? ["caller"]);
  const [lost, setLost] = useState<string[]>([]);
  const everyScenario = useScenarios(agent.id);
  const personas = usePersonas();
  const rules = useAgent(agent.id).data?.rules;
  const known = personas.data ?? [];
  const live = everyScenario.data ?? [];

  const settled =
    everyScenario.isSuccess &&
    everyScenario.fetchStatus === "idle" &&
    personas.isSuccess &&
    !personas.isFetching;
  if (setup.rows === null && settled) {
    const items = copied
      ? copied.scenarios
      : entry && Array.isArray(entry.scenarios)
        ? entry.scenarios
        : [];
    const cards = cardsFrom(items, live, known);
    setup.setRows(cards.rows);
    if (copied) setLost(cards.lost);
  }

  const { one, many, answering } = setup;
  const allAnswers: AnsweredBy[] = answering ? answers : ["caller"];
  const repeatCount = setup.repeatsOk && setup.repeatCount ? setup.repeatCount : 0;
  const allCalls = live.reduce(
    (sum, scenario) => sum + scenario.data_sets.length * allAnswers.length * repeatCount,
    0,
  );
  const calls = mode === "all" ? allCalls : setup.total;
  const valid =
    setup.transportOk && setup.repeatsOk && setup.limitsOk && (mode === "all" || setup.cardsOk);
  const machineAnswers = (
    mode === "all" ? answers : (setup.rows ?? []).flatMap((row) => row.answers)
  ).some((answer) => answer !== "caller");

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!revealErrors(event.currentTarget, () => setup.setSubmitted(true), valid)) {
      if (!setup.limitsOk) setup.setEditLimits(true);
      return;
    }
    onSave({
      agent_id: agent.id,
      transport: setup.transport,
      scenarios:
        mode === "all"
          ? { answered_by: allAnswers }
          : entryScenarios(setup.rows ?? [], answering, playingEveryDataSet(entry)),
      ...setup.settings(),
    });
  };

  return (
    <>
      <form
        id="entry-form"
        noValidate
        onSubmit={submit}
        className="grid min-h-0 flex-1 grid-cols-1 sm:grid-cols-[minmax(0,1fr)_18rem]"
      >
        <section className="flex min-h-0 flex-col gap-4 px-6 py-5">
          {lost.length > 0 && (
            <p
              role="status"
              className="flex gap-2 rounded-sm bg-warning px-3 py-2 text-s-400 text-warning-foreground"
            >
              <TriangleAlert className="mt-0.5 size-4 shrink-0" />
              <span>Deleted after the run, so not in the copy: {lost.join(", ")}.</span>
            </p>
          )}
          {machineAnswers && !answering && setup.transportOk && (
            <p
              role="status"
              className="flex gap-2 rounded-sm bg-warning px-3 py-2 text-s-400 text-warning-foreground"
            >
              <TriangleAlert className="mt-0.5 size-4 shrink-0" />
              <span>
                Voicemail and call screening need a phone connection to an outbound agent. Save
                keeps only the caller.
              </span>
            </p>
          )}
          {entry && entry.problems.length > 0 && (
            <p
              role="status"
              className="flex gap-2 rounded-sm bg-warning px-3 py-2 text-s-400 text-warning-foreground"
            >
              <TriangleAlert className="mt-0.5 size-4 shrink-0" />
              <span>
                {entry.problems.join("; ")}. Save removes what was deleted. Fix the rest below.
              </span>
            </p>
          )}
          <div className="flex items-end justify-between gap-4">
            <div className="grid min-w-0 gap-2">
              <span className="text-label text-secondary">Scenarios</span>
              <div role="group" aria-label="Which scenarios" className="flex gap-1.5">
                {(["all", "choose"] as const).map((value) => (
                  <Button
                    key={value}
                    type="button"
                    size="sm"
                    variant={mode === value ? "tertiary" : "ghost"}
                    aria-pressed={mode === value}
                    onClick={() => setMode(value)}
                  >
                    {mode === value && <Check />}
                    {value === "all" ? "All scenarios" : "Choose"}
                  </Button>
                ))}
              </div>
              <span className="text-s-400 text-muted-foreground">
                {mode === "all"
                  ? "Each with its own persona and all its data sets. Scenarios added later join too."
                  : "Each scenario runs once for each persona in its list."}
              </span>
            </div>
            {mode === "choose" && <MixPersonas setup={setup} agent={agent} personas={known} />}
          </div>

          {mode === "all" && answering && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-s-500">Answered by</span>
              <AnswersMenu value={answers} onValueChange={setAnswers} />
              <span className="text-xs-400 text-muted-foreground">
                For every scenario. Each answer is a call of its own.
              </span>
              <NoVerdictNote
                answers={answers}
                rules={rules}
                personas={live.map(
                  (scenario) =>
                    known.find((persona) => persona.id === scenario.persona_id)?.answering ??
                    DEFAULT_ANSWERING,
                )}
              />
            </div>
          )}

          {mode === "choose" && setup.submitted && setup.empty.length > 0 && (
            <p role="alert" className="text-s-400 text-destructive">
              Add a persona to {counted(setup.empty.length, "scenario", "scenarios")}.
            </p>
          )}

          <div className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto pr-1">
            {everyScenario.error || personas.error ? (
              <p role="alert" className="text-destructive">
                Could not load the scenarios or personas:{" "}
                {(everyScenario.error ?? personas.error)?.message}
              </p>
            ) : setup.rows === null ? (
              <p className="text-s-400 text-muted-foreground">Loading the scenarios and personas</p>
            ) : mode === "all" ? (
              live.length === 0 ? (
                <p className="text-s-400 text-muted-foreground">
                  The agent has no scenarios yet. A start refuses an entry with none.
                </p>
              ) : (
                <ul aria-label="Scenarios that run" className="divide-y border">
                  {live.map((scenario) => (
                    <li
                      key={scenario.id}
                      className="flex justify-between gap-4 px-3 py-1.5 text-s-400"
                    >
                      <span className="truncate">{scenario.name}</span>
                      <span className="shrink-0 text-muted-foreground tabular-nums">
                        {counted(
                          scenario.data_sets.length * allAnswers.length * repeatCount,
                          one,
                          many,
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )
            ) : (
              <ScenarioCards
                setup={setup}
                personas={known}
                served={servedLanguages(agent.languages)}
                rules={rules}
                everyScenario={live}
                noun="this agent"
              />
            )}
          </div>
        </section>

        <aside className="flex min-h-0 flex-col gap-6 overflow-y-auto border-t bg-muted/40 px-6 py-5 sm:border-t-0 sm:border-l">
          <RunSettings setup={setup} agent={agent} idPrefix="entry" fixedConnection />
        </aside>
      </form>

      <DialogFooter className="items-center border-t px-6 py-4 sm:justify-between">
        <div className="grid gap-0.5">
          <span className="text-s-400 text-muted-foreground tabular-nums">
            {counted(calls, one, many)} in each suite run
          </span>
          {error && <FieldError>{error}</FieldError>}
        </div>
        <div className="flex gap-2">
          <Button type="button" variant="ghost" disabled={pending} onClick={onCancel}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="entry-form"
            disabled={pending || setup.rows === null || stale}
          >
            {pending && <Spinner />}
            {entry ? "Save" : "Add to suite"}
          </Button>
        </div>
      </DialogFooter>
    </>
  );
}
