import { type SubmitEvent, useState } from "react";
import { Link, useNavigate } from "react-router";

import { MixPersonas, RunSettings, ScenarioCards } from "@/components/run-setup";
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
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { counted, when } from "@/lib/format";
import { revealErrors } from "@/lib/forms";
import { randomKey } from "@/lib/random-key";
import { answersToPlay, text, useRunSetup } from "@/lib/run-setup";
import {
  useAgent,
  usePersonas,
  usePhoneNumbers,
  useRunScenarios,
  useScenarios,
  useStartRun,
} from "@/lib/queries";
import {
  type AgentSummary,
  type AnsweredBy,
  type RunSummary,
  type Scenario,
  servedLanguages,
} from "@/lib/types";

/** The ids of the scenario's data sets that are still there, of `wanted` when given and any
 * of them is left, else all of them. */
function dataSetsToPlay(scenario: Scenario, wanted?: string[]): string[] {
  const ids = scenario.data_sets.map((dataSet) => dataSet.id ?? "");
  const kept = (wanted ?? []).filter((id) => ids.includes(id));
  return kept.length > 0 ? kept : ids;
}

/** Starts a run of the scenarios, in the order given, or of every scenario of the agent when
 * `scenarioIds` is absent. Each scenario runs once for each persona on its card, each data set
 * and each answer checked on it: its own persona, every data set and the caller at first, or the
 * ones in `personasOf`, `dataSetsOf` and `answersOf` for "Run again". `earlier` fills the other
 * fields, and scenarios, personas or data sets deleted since are left out. */
export function RunDialog({
  agent,
  scenarioIds,
  personasOf,
  dataSetsOf,
  answersOf,
  earlier,
  onClosed,
}: {
  agent: AgentSummary;
  scenarioIds?: string[];
  personasOf?: Record<string, string[]>;
  dataSetsOf?: Record<string, string[]>;
  answersOf?: Record<string, AnsweredBy[]>;
  earlier?: RunSummary;
  onClosed: () => void;
}) {
  const [open, setOpen] = useState(true);
  const [requestKey] = useState(randomKey);
  const [name, setName] = useState(() => `Run of ${when(new Date().toISOString())}`);
  const setup = useRunSetup(agent, {
    transport:
      earlier && agent.transports.includes(earlier.transport)
        ? earlier.transport
        : agent.transports[0],
    repeats: text(earlier?.repeats ?? 1),
    maxDuration: earlier ? text(earlier.max_duration_s) : null,
    maxTurns: earlier ? text(earlier.max_turns) : null,
    maxParallel: text(earlier?.max_parallel),
    delay: text(earlier?.start_interval_s),
    retries: earlier ? text(earlier.max_retries) : null,
  });
  const served = servedLanguages(agent.languages);
  const {
    scenarios: loaded,
    leftOut,
    ready,
    error: loadError,
  } = useRunScenarios(agent.id, scenarioIds);
  const everyScenario = useScenarios(agent.id);
  const rules = useAgent(agent.id).data?.rules;
  const personas = usePersonas();
  const numbers = usePhoneNumbers();
  const start = useStartRun(requestKey);
  const navigate = useNavigate();

  const known = personas.data ?? [];
  const byId = new Map(known.map((persona) => [persona.id, persona]));
  // Wait for the current persona list, not a cached one, so a persona deleted since the
  // earlier run is left out before the cards are filled.
  const personasSettled = personas.isSuccess && !personas.isFetching;
  if (setup.rows === null && ready && personasSettled) {
    setup.setRows(
      loaded.map((scenario) => {
        const kept = (personasOf?.[scenario.id] ?? []).filter((id) => byId.has(id));
        return {
          scenario,
          personaIds: kept.length ? kept : [scenario.persona_id],
          dataSetIds: dataSetsToPlay(scenario, dataSetsOf?.[scenario.id]),
          answers: answersToPlay(answersOf?.[scenario.id]),
        };
      }),
    );
  }
  const { phone, outbound, one, many, scenarios, total } = setup;
  const valid = setup.cardsOk && setup.repeatsOk && setup.limitsOk;

  // Text tests use no phone number, so phone readiness never blocks them.
  const blocked =
    phone && numbers.data
      ? outbound
        ? numbers.data.outbound_problem
        : numbers.data.problem
      : null;
  const usable =
    !phone || blocked
      ? []
      : (numbers.data?.items ?? []).filter((number) => number.owner === "test");
  const waits = usable.length > 0 && total > usable.length;

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!revealErrors(event.currentTarget, () => setup.setSubmitted(true), valid)) {
      if (!setup.limitsOk) setup.setEditLimits(true);
      return;
    }
    start.mutate(
      {
        agent_id: agent.id,
        transport: setup.transport,
        scenarios: setup.runScenarios(),
        ...setup.settings(),
        name: name.trim() || null,
      },
      { onSuccess: (run) => navigate(`/runs/${run.id}`) },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && !start.isPending && setOpen(false)}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="flex h-[min(760px,90vh)] flex-col gap-0 p-0 sm:max-w-5xl">
        <DialogHeader className="border-b px-6 py-5">
          <DialogTitle>
            {earlier ? "Run again" : scenarios.length === 1 ? "Run scenario" : "Run scenarios"}
          </DialogTitle>
          <DialogDescription>
            {agent.name} · {counted(scenarios.length, "scenario", "scenarios")}
          </DialogDescription>
        </DialogHeader>

        <form
          id="run-form"
          noValidate
          onSubmit={submit}
          className="grid min-h-0 flex-1 grid-cols-1 sm:grid-cols-[minmax(0,1fr)_18rem]"
        >
          <section className="flex min-h-0 flex-col gap-4 px-6 py-5">
            <div className="flex items-end justify-between gap-4">
              <div className="grid min-w-0 gap-1">
                <span className="text-label text-secondary">Scenarios</span>
                <span className="text-s-400 text-muted-foreground">
                  Each scenario runs once for each persona in its list.
                </span>
              </div>
              <MixPersonas setup={setup} agent={agent} personas={known} />
            </div>

            {setup.submitted && setup.empty.length > 0 && (
              <p role="alert" className="text-s-400 text-destructive">
                Add a persona to {counted(setup.empty.length, "scenario", "scenarios")} to start the
                run.
              </p>
            )}

            <div className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto pr-1">
              {loadError ? (
                <p role="alert" className="text-destructive">
                  Could not load the scenarios: {loadError.message}
                </p>
              ) : personas.error ? (
                <p role="alert" className="text-destructive">
                  Could not load the personas: {personas.error.message}{" "}
                  <button type="button" className="underline" onClick={() => personas.refetch()}>
                    Try again
                  </button>
                </p>
              ) : setup.rows === null ? (
                <p className="text-s-400 text-muted-foreground">
                  Loading the scenarios and personas
                </p>
              ) : (
                <ScenarioCards
                  setup={setup}
                  personas={known}
                  served={served}
                  rules={rules}
                  everyScenario={everyScenario.data ?? []}
                  noun="this run"
                />
              )}
              {leftOut > 0 && (
                <p className="text-s-400 text-muted-foreground">
                  {counted(leftOut, "scenario", "scenarios")}
                  {earlier && " of the earlier run"} no longer {leftOut === 1 ? "exists" : "exist"}{" "}
                  and {leftOut === 1 ? "is" : "are"} left out.
                </p>
              )}
            </div>
          </section>

          <aside className="flex min-h-0 flex-col gap-6 overflow-y-auto border-t bg-muted/40 px-6 py-5 sm:border-t-0 sm:border-l">
            <RunSettings setup={setup} agent={agent} idPrefix="run">
              {earlier && !agent.transports.includes(earlier.transport) && (
                <p className="text-s-400 text-muted-foreground">
                  The earlier run used {earlier.transport}. The agent no longer has that connection,
                  so this run uses {setup.transport}.
                </p>
              )}
              <Field>
                <FieldLabel htmlFor="run-name">Name</FieldLabel>
                <Input
                  id="run-name"
                  maxLength={80}
                  value={name}
                  onFocus={(event) => event.currentTarget.select()}
                  onChange={(event) => setName(event.target.value)}
                />
              </Field>
            </RunSettings>
          </aside>
        </form>

        <DialogFooter className="items-center border-t px-6 py-4 sm:justify-between">
          <div className="grid gap-0.5">
            {setup.rows !== null && setup.repeatsOk && (
              <span className="text-s-400 text-muted-foreground tabular-nums">
                {counted(setup.different, `different ${one}`, `different ${many}`)}, each run{" "}
                {setup.times} · {counted(scenarios.length, "scenario", "scenarios")},{" "}
                {counted(setup.personaCount, "persona", "personas")}
                {setup.dataSetCount > scenarios.length &&
                  `, ${counted(setup.dataSetCount, "data set", "data sets")}`}
              </span>
            )}
            {waits && (
              <span
                className="text-xs-400 text-status-warning-text"
                title={
                  outbound
                    ? `The agent calls Yaksh, and each test number takes one call at a time, then rests ${numbers.data?.rest_s} s.`
                    : "Yaksh calls the agent from its test numbers, one call at a time on each."
                }
              >
                {counted(total, "call", "calls")} on {counted(usable.length, "number", "numbers")}:
                they run {usable.length} at a time.
              </span>
            )}
            {blocked && (
              <span className="text-xs-400 text-status-warning-text">
                Calls can't start: {blocked}.{" "}
                <Link to="/numbers" className="underline underline-offset-2">
                  Open Numbers
                </Link>
              </span>
            )}
            {start.error && <FieldError>{start.error.message}</FieldError>}
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              disabled={start.isPending}
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              form="run-form"
              disabled={
                start.isPending || setup.rows === null || scenarios.length === 0 || Boolean(blocked)
              }
            >
              {start.isPending && <Spinner />}
              Start {counted(total, one, many)}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
