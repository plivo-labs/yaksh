import { Check, ChevronDown, Shuffle, XIcon } from "lucide-react";
import { Fragment, type SubmitEvent, useState } from "react";
import { Link, useNavigate } from "react-router";

import { PersonaChips } from "@/components/persona-chips";
import { ScenarioAdder } from "@/components/scenario-adder";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ANSWERS, DEFAULT_ANSWERING, withoutVerdict } from "@/lib/answering";
import { counted, when } from "@/lib/format";
import { revealErrors } from "@/lib/forms";
import { mixPersonas } from "@/lib/mix";
import { randomKey } from "@/lib/random-key";
import {
  useAgent,
  useDefaults,
  usePersonas,
  usePhoneNumbers,
  useRunScenarios,
  useScenarios,
  useStartRun,
} from "@/lib/queries";
import {
  AGENT_LANGUAGES,
  type AgentSummary,
  type AnsweredBy,
  type Language,
  LANGUAGE_NAMES,
  type RunSummary,
  type Scenario,
  type Transport,
  servedLanguages,
} from "@/lib/types";

const CONNECTIONS: { value: Transport; label: string }[] = [
  { value: "phone", label: "Phone" },
  { value: "text", label: "Text" },
];

/** The ids of the scenario's data sets that are still there, of `wanted` when given and any
 * of them is left, else all of them. */
function dataSetsToPlay(scenario: Scenario, wanted?: string[]): string[] {
  const ids = scenario.data_sets.map((dataSet) => dataSet.id ?? "");
  const kept = (wanted ?? []).filter((id) => ids.includes(id));
  return kept.length > 0 ? kept : ids;
}

/** The answers of `wanted` in menu order, or the caller when there are none. */
function answersToPlay(wanted?: AnsweredBy[]): AnsweredBy[] {
  const kept = ANSWERS.map((answer) => answer.value).filter((answer) => wanted?.includes(answer));
  return kept.length > 0 ? kept : ["caller"];
}

/** "The caller, voicemail": the first answer as its label, the others in lower case. */
function answersText(answers: AnsweredBy[]): string {
  return ANSWERS.filter((answer) => answers.includes(answer.value))
    .map((answer, index) => (index === 0 ? answer.label : answer.label.toLowerCase()))
    .join(", ");
}

const MACHINE_CALLS: Record<Exclude<AnsweredBy, "caller">, string> = {
  voicemail: "voicemail calls",
  screener: "screener calls",
};

const MIX_SIZES = ["2", "3", "4", "5"].map((value) => ({ value, label: value }));

/** A whole number from an input, null when it is empty, NaN when it is not a whole number. */
function whole(value: string): number | null {
  if (value.trim() === "") return null;
  const number = Number(value);
  return Number.isInteger(number) ? number : Number.NaN;
}

function text(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

interface Row {
  scenario: Scenario;
  personaIds: string[];
  /** The data sets each persona plays: all of them at first. */
  dataSetIds: string[];
  /** Who answers each call: the caller at first. Phone runs of an outbound agent only. */
  answers: AnsweredBy[];
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
  const [repeats, setRepeats] = useState(() => text(earlier?.repeats ?? 1));
  /** Null until the user types: the field then shows the server's default. */
  const [maxDuration, setMaxDuration] = useState(earlier ? text(earlier.max_duration_s) : null);
  const [maxTurns, setMaxTurns] = useState(earlier ? text(earlier.max_turns) : null);
  const [maxParallel, setMaxParallel] = useState(() => text(earlier?.max_parallel));
  const [delay, setDelay] = useState(() => text(earlier?.start_interval_s));
  const [retries, setRetries] = useState(earlier ? text(earlier.max_retries) : null);
  const [transport, setTransport] = useState<Transport>(() =>
    earlier && agent.transports.includes(earlier.transport)
      ? earlier.transport
      : agent.transports[0],
  );
  const [one, many] = transport === "text" ? ["conversation", "conversations"] : ["call", "calls"];
  const [editLimits, setEditLimits] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  /** The run's scenarios and the personas on each card, copied once when they load, so a
   * refresh in the background never changes what the user set up; null until then. */
  const [rows, setRows] = useState<Row[] | null>(null);
  const [mixSize, setMixSize] = useState("3");
  const served = servedLanguages(agent.languages);
  const [mixLanguage, setMixLanguage] = useState<Language>(
    AGENT_LANGUAGES[agent.languages[0]].language,
  );
  const [mixOpen, setMixOpen] = useState(false);
  const {
    scenarios: loaded,
    leftOut,
    ready,
    error: loadError,
  } = useRunScenarios(agent.id, scenarioIds);
  const everyScenario = useScenarios(agent.id);
  const rules = useAgent(agent.id).data?.rules;
  const personas = usePersonas();
  const defaults = useDefaults();
  const numbers = usePhoneNumbers();
  const start = useStartRun(requestKey);
  const navigate = useNavigate();

  const known = personas.data ?? [];
  const byId = new Map(known.map((persona) => [persona.id, persona]));
  // Wait for the current persona list, not a cached one, so a persona deleted since the
  // earlier run is left out before the cards are filled.
  const personasSettled = personas.isSuccess && !personas.isFetching;
  if (rows === null && ready && personasSettled) {
    setRows(
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
  // Voicemail and call screening answer the calls that Yaksh receives from an outbound agent.
  const phone = transport === "phone";
  const outbound = agent.direction === "outbound";
  const answering = phone && outbound;
  const scenarios = (rows ?? []).map((row) => row.scenario);
  const cards = Object.fromEntries((rows ?? []).map((row) => [row.scenario.id, row.personaIds]));
  const answered = Object.fromEntries(
    (rows ?? []).map((row): [string, AnsweredBy[]] => [
      row.scenario.id,
      answering ? row.answers : ["caller"],
    ]),
  );
  const changed = (rows ?? []).some(
    (row) => row.personaIds.length !== 1 || row.personaIds[0] !== row.scenario.persona_id,
  );
  const pool = known.filter((persona) => persona.language === mixLanguage);

  const update = (change: (row: Row) => string[]) =>
    setRows((current) => (current ?? []).map((row) => ({ ...row, personaIds: change(row) })));
  const setDataSets = (scenarioId: string, ids: string[]) =>
    setRows((current) =>
      (current ?? []).map((row) =>
        row.scenario.id === scenarioId ? { ...row, dataSetIds: ids } : row,
      ),
    );
  const played = Object.fromEntries((rows ?? []).map((row) => [row.scenario.id, row.dataSetIds]));
  const setAnswers = (scenarioId: string, answers: AnsweredBy[]) =>
    setRows((current) =>
      (current ?? []).map((row) => (row.scenario.id === scenarioId ? { ...row, answers } : row)),
    );
  const setCard = (scenarioId: string, ids: string[]) =>
    update((row) => (row.scenario.id === scenarioId ? ids : row.personaIds));
  const removeScenario = (scenarioId: string) =>
    setRows((current) => (current ?? []).filter((row) => row.scenario.id !== scenarioId));
  const addScenario = (scenario: Scenario) =>
    setRows((current) => [
      ...(current ?? []),
      {
        scenario,
        personaIds: [scenario.persona_id],
        dataSetIds: dataSetsToPlay(scenario),
        answers: answersToPlay(),
      },
    ]);
  const mix = () => {
    const mixed = mixPersonas(
      scenarios,
      pool.map((persona) => persona.id),
      Number(mixSize),
    );
    update((row) => mixed[row.scenario.id]);
    setMixOpen(false);
  };
  const addToAll = (personaId: string) => {
    update((row) =>
      row.personaIds.includes(personaId) ? row.personaIds : [...row.personaIds, personaId],
    );
    setMixOpen(false);
  };
  const resetToOwn = () => {
    update((row) => [row.scenario.persona_id]);
    setMixOpen(false);
  };

  const durationText = maxDuration ?? text(defaults.data?.max_duration_s);
  const turnsText = maxTurns ?? text(defaults.data?.max_turns);
  const retriesText = retries ?? text(defaults.data?.max_retries);
  const repeatCount = whole(repeats);
  const duration = whole(durationText);
  const turns = whole(turnsText);
  const parallel = whole(maxParallel);
  const interval = whole(delay);
  const retryCount = whole(retriesText);
  const repeatsOk = repeatCount !== null && repeatCount >= 1;
  const durationOk = duration === null || (duration >= 10 && duration <= 1800);
  const turnsOk = turns === null || (turns >= 1 && turns <= 100);
  const parallelOk = parallel === null || parallel >= 1;
  const intervalOk = interval === null || interval >= 1;
  const retriesOk = retryCount === null || retryCount >= 0;
  const limitsOk = durationOk && turnsOk && parallelOk && intervalOk && retriesOk;
  const empty = scenarios.filter((scenario) => (cards[scenario.id] ?? []).length === 0);
  const unplayed = scenarios.filter((scenario) => (played[scenario.id] ?? []).length === 0);
  const valid =
    rows !== null &&
    scenarios.length > 0 &&
    empty.length === 0 &&
    unplayed.length === 0 &&
    repeatsOk &&
    limitsOk;
  const different = scenarios.reduce(
    (sum, scenario) =>
      sum +
      (cards[scenario.id]?.length ?? 0) *
        (played[scenario.id]?.length ?? 0) *
        (answered[scenario.id]?.length ?? 0),
    0,
  );
  const total = different * (repeatsOk ? repeatCount : 0);
  const personaCount = new Set(scenarios.flatMap((scenario) => cards[scenario.id] ?? [])).size;
  const dataSetCount = scenarios.reduce(
    (sum, scenario) => sum + (played[scenario.id]?.length ?? 0),
    0,
  );
  const times = !repeatsOk
    ? ""
    : repeatCount === 1
      ? "once"
      : repeatCount === 2
        ? "twice"
        : `${repeatCount} times`;

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
    if (
      !revealErrors(event.currentTarget, () => setSubmitted(true), valid) ||
      repeatCount === null
    ) {
      if (!limitsOk) setEditLimits(true);
      return;
    }
    start.mutate(
      {
        agent_id: agent.id,
        transport,
        scenarios: scenarios.map((scenario) => ({
          scenario_id: scenario.id,
          persona_ids: cards[scenario.id],
          data_set_ids: scenario.data_sets.length > 1 ? played[scenario.id] : null,
          answered_by: answered[scenario.id],
        })),
        repeats: repeatCount,
        // Untouched fields go as null, for the defaults they show: a resent request then stays
        // the same whether or not the defaults had loaded when it was first sent.
        max_duration_s: maxDuration === null ? null : duration,
        max_turns: maxTurns === null ? null : turns,
        max_parallel: parallel,
        start_interval_s: interval,
        max_retries: retries === null ? null : retryCount,
        name: name.trim() || null,
      },
      { onSuccess: (run) => navigate(`/runs/${run.id}`) },
    );
  };

  const limits: [string, string][] = [
    ["Time limit", duration === null ? "Default" : `${duration} s`],
    ["Turn limit", turns === null ? "Default" : `${turns} turns`],
    ["At once", parallel === null ? "No run limit" : String(parallel)],
    ["Delay", interval === null ? "None" : `${interval} s`],
    ["Retries", retryCount === null ? "Default" : `Up to ${retryCount}`],
  ];

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
              <Popover open={mixOpen} onOpenChange={setMixOpen}>
                <PopoverTrigger
                  render={
                    <Button type="button" variant="outline" size="sm" disabled={rows === null} />
                  }
                >
                  <Shuffle />
                  Mix personas
                </PopoverTrigger>
                <PopoverContent align="end" className="w-80 gap-0 p-0">
                  <div className="grid gap-3 p-4">
                    <span className="text-s-500">Mix personas</span>
                    <div className="flex items-center gap-2">
                      <Select
                        items={MIX_SIZES}
                        value={mixSize}
                        onValueChange={(value) => value && setMixSize(value)}
                      >
                        <SelectTrigger aria-label="Personas for each scenario" className="w-16">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectGroup>
                            {MIX_SIZES.map((item) => (
                              <SelectItem key={item.value} value={item.value}>
                                {item.label}
                              </SelectItem>
                            ))}
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                      <span className="text-s-400 text-muted-foreground">for each scenario</span>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="ml-auto"
                        disabled={pool.length === 0}
                        onClick={mix}
                      >
                        Mix
                      </Button>
                    </div>
                    {served.size > 1 && (
                      <div className="flex items-center gap-2">
                        <Select
                          items={[...served].map((language) => ({
                            value: language,
                            label: LANGUAGE_NAMES[language],
                          }))}
                          value={mixLanguage}
                          onValueChange={(value) => value && setMixLanguage(value as Language)}
                        >
                          <SelectTrigger aria-label="Language of the personas" className="w-28">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectGroup>
                              {[...served].map((language) => (
                                <SelectItem key={language} value={language}>
                                  {LANGUAGE_NAMES[language]}
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                        <span className="text-s-400 text-muted-foreground">personas</span>
                      </div>
                    )}
                    <p
                      className="text-xs-400 text-muted-foreground"
                      title={`Each scenario keeps its own persona. The others come from the ${pool.length} ${LANGUAGE_NAMES[mixLanguage]} personas, and each is used once before any is used twice.`}
                    >
                      Includes each scenario's own persona.
                    </p>
                  </div>
                  <div className="grid gap-2 border-t p-4">
                    <span className="text-s-500">Add a persona to every scenario</span>
                    <Select
                      items={known.map((persona) => ({ value: persona.id, label: persona.name }))}
                      value={null}
                      onValueChange={(value) => value && addToAll(value)}
                    >
                      <SelectTrigger aria-label="Persona to add" className="w-full">
                        <SelectValue placeholder="Choose a persona" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {known.map((persona) => (
                            <SelectItem key={persona.id} value={persona.id}>
                              {persona.name}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>
                  {changed && (
                    <button
                      type="button"
                      className="w-full border-t px-4 py-3 text-left text-s-400 hover:bg-hv1"
                      onClick={resetToOwn}
                    >
                      Reset to scenario personas
                    </button>
                  )}
                </PopoverContent>
              </Popover>
            </div>

            {submitted && empty.length > 0 && (
              <p role="alert" className="text-s-400 text-destructive">
                Add a persona to {counted(empty.length, "scenario", "scenarios")} to start the run.
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
              ) : rows === null ? (
                <p className="text-s-400 text-muted-foreground">
                  Loading the scenarios and personas
                </p>
              ) : (
                scenarios.map((scenario) => {
                  const ids = cards[scenario.id] ?? [];
                  const foreign = ids
                    .map((id) => byId.get(id))
                    .filter((persona) => persona && !served.has(persona.language));
                  const sets = played[scenario.id] ?? [];
                  const answers = answered[scenario.id] ?? [];
                  const calls =
                    ids.length * sets.length * answers.length * (repeatsOk ? repeatCount : 0);
                  const settings = ids.map((id) => byId.get(id)?.answering ?? DEFAULT_ANSWERING);
                  const unjudged = rules
                    ? answers.filter(
                        (answer): answer is keyof typeof MACHINE_CALLS =>
                          answer !== "caller" && withoutVerdict(answer, rules, settings),
                      )
                    : [];
                  return (
                    <div
                      key={scenario.id}
                      className={`grid gap-3 border p-4 ${submitted && (ids.length === 0 || sets.length === 0) ? "border-destructive" : ""}`}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <span className="text-s-500">{scenario.name}</span>
                        <span className="flex shrink-0 items-center gap-2">
                          {answering && (
                            <AnswersMenu
                              value={answers}
                              onValueChange={(next) => setAnswers(scenario.id, next)}
                            />
                          )}
                          <span className="text-xs-400 text-muted-foreground tabular-nums">
                            {counted(calls, one, many)}
                          </span>
                          <button
                            type="button"
                            aria-label={`Remove ${scenario.name} from this run`}
                            title="Remove from this run"
                            className="-mt-0.5 flex size-6 items-center justify-center rounded-sm text-muted-foreground hover:bg-hv1 hover:text-foreground"
                            onClick={() => removeScenario(scenario.id)}
                          >
                            <XIcon className="size-3.5" />
                          </button>
                        </span>
                      </div>
                      <PersonaChips
                        label={scenario.name}
                        personas={known}
                        value={ids}
                        served={served}
                        invalid={submitted && ids.length === 0}
                        onValueChange={(next) => setCard(scenario.id, next)}
                      />
                      {scenario.data_sets.length > 1 && (
                        <DataSetChips
                          scenario={scenario}
                          value={sets}
                          invalid={submitted && sets.length === 0}
                          onValueChange={(next) => setDataSets(scenario.id, next)}
                        />
                      )}
                      {foreign.map(
                        (persona) =>
                          persona && (
                            <p key={persona.id} className="text-xs-400 text-status-warning-text">
                              {persona.name} speaks {LANGUAGE_NAMES[persona.language]}, which the
                              agent does not serve.
                            </p>
                          ),
                      )}
                      {unjudged.length > 0 && (
                        <p className="text-xs-400 text-status-warning-text">
                          No rule decides{" "}
                          {unjudged.map((answer) => MACHINE_CALLS[answer]).join(" or ")}, so they
                          get no verdict.
                        </p>
                      )}
                    </div>
                  );
                })
              )}
              {rows !== null && (
                <ScenarioAdder
                  scenarios={(everyScenario.data ?? []).filter(
                    (scenario) => !scenarios.some((shown) => shown.id === scenario.id),
                  )}
                  onAdd={addScenario}
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
            <div className="grid gap-4">
              {agent.transports.length > 1 && (
                <Field>
                  <FieldLabel htmlFor="run-transport">Connection</FieldLabel>
                  <Select
                    items={CONNECTIONS}
                    value={transport}
                    onValueChange={(value) => value && setTransport(value)}
                  >
                    <SelectTrigger id="run-transport" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {CONNECTIONS.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FieldDescription>The agent has both. Each run uses one.</FieldDescription>
                </Field>
              )}
              {earlier && !agent.transports.includes(earlier.transport) && (
                <p className="text-s-400 text-muted-foreground">
                  The earlier run used {earlier.transport}. The agent no longer has that connection,
                  so this run uses {transport}.
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
              <Field>
                <FieldLabel htmlFor="run-repeats">Repeats</FieldLabel>
                <Input
                  id="run-repeats"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  aria-invalid={submitted && !repeatsOk}
                  className="tabular-nums"
                  value={repeats}
                  onChange={(event) => setRepeats(event.target.value)}
                />
                <FieldDescription>How many times each {one} runs.</FieldDescription>
                {submitted && !repeatsOk && <FieldError>Enter a whole number from 1.</FieldError>}
              </Field>
            </div>

            <div className="grid gap-1">
              <div className="flex items-baseline justify-between">
                <span className="text-label text-secondary">Limits</span>
                <button
                  type="button"
                  className="text-s-400 text-brand-text"
                  aria-expanded={editLimits}
                  onClick={() => setEditLimits((current) => !current)}
                >
                  {editLimits ? "Done" : "Edit"}
                </button>
              </div>
              {editLimits ? (
                <div className="grid gap-3 pt-2">
                  <LimitField
                    id="run-duration"
                    label="Time limit, seconds"
                    value={durationText}
                    placeholder="Default"
                    invalid={submitted && !durationOk}
                    error="Enter a whole number from 10 to 1800, or none."
                    onChange={setMaxDuration}
                  />
                  <LimitField
                    id="run-turns"
                    label="Turn limit"
                    value={turnsText}
                    placeholder="Default"
                    invalid={submitted && !turnsOk}
                    error="Enter a whole number from 1 to 100, or none."
                    onChange={setMaxTurns}
                  />
                  <LimitField
                    id="run-parallel"
                    label="Max parallel"
                    value={maxParallel}
                    placeholder="No run limit"
                    invalid={submitted && !parallelOk}
                    error="Enter a whole number from 1, or none."
                    onChange={setMaxParallel}
                  />
                  <LimitField
                    id="run-delay"
                    label={`Delay between ${many}, seconds`}
                    value={delay}
                    placeholder="None"
                    invalid={submitted && !intervalOk}
                    error="Enter a whole number from 1, or none."
                    onChange={setDelay}
                  />
                  <LimitField
                    id="run-retries"
                    label="Retries"
                    value={retriesText}
                    placeholder="Default"
                    invalid={submitted && !retriesOk}
                    error="Enter a whole number from 0, or none."
                    onChange={setRetries}
                  />
                </div>
              ) : (
                <dl className="grid">
                  {limits.map(([label, value]) => (
                    <div key={label} className="flex justify-between border-t py-1.5 text-s-400">
                      <dt className="text-muted-foreground">{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </aside>
        </form>

        <DialogFooter className="items-center border-t px-6 py-4 sm:justify-between">
          <div className="grid gap-0.5">
            {rows !== null && repeatsOk && (
              <span className="text-s-400 text-muted-foreground tabular-nums">
                {counted(different, `different ${one}`, `different ${many}`)}, each run {times} ·{" "}
                {counted(scenarios.length, "scenario", "scenarios")},{" "}
                {counted(personaCount, "persona", "personas")}
                {dataSetCount > scenarios.length &&
                  `, ${counted(dataSetCount, "data set", "data sets")}`}
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
                start.isPending || rows === null || scenarios.length === 0 || Boolean(blocked)
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

/** Who answers the scenario's calls, as a menu of checkboxes. The last checked answer is locked,
 * because each scenario needs at least one. */
function AnswersMenu({
  value,
  onValueChange,
}: {
  value: AnsweredBy[];
  onValueChange: (answers: AnsweredBy[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const text = answersText(value);
  const toggle = (answer: AnsweredBy) =>
    onValueChange(
      value.includes(answer)
        ? value.filter((item) => item !== answer)
        : answersToPlay([...value, answer]),
    );
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label={`Answered by: ${text}`}
            className="-my-0.5 flex h-6 items-center gap-1 rounded-sm bg-muted pr-1.5 pl-2 text-xs-500 hover:bg-hv1"
          />
        }
      >
        {text}
        <ChevronDown className={`size-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 gap-0 p-1">
        <span className="px-2.5 pt-2 pb-1 text-xs-400 text-muted-foreground">Answered by</span>
        {ANSWERS.map((answer) => {
          const on = value.includes(answer.value);
          const locked = on && value.length === 1;
          const row = (
            <label
              className={`flex items-start gap-2.5 rounded-sm px-2.5 py-2 ${locked ? "cursor-not-allowed" : "cursor-pointer hover:bg-hv1"}`}
            >
              <Checkbox
                className="mt-0.5"
                checked={on}
                disabled={locked}
                onCheckedChange={() => toggle(answer.value)}
              />
              <span className="grid">
                <span className="text-s-500">{answer.label}</span>
                <span className="text-xs-400 text-muted-foreground">{answer.description}</span>
              </span>
            </label>
          );
          return locked ? (
            <Tooltip key={answer.value}>
              <TooltipTrigger
                render={
                  <div
                    tabIndex={0}
                    className="rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                  />
                }
              >
                {row}
              </TooltipTrigger>
              <TooltipContent side="left">
                A scenario needs at least one. Check another one first.
              </TooltipContent>
            </Tooltip>
          ) : (
            <Fragment key={answer.value}>{row}</Fragment>
          );
        })}
      </PopoverContent>
    </Popover>
  );
}

/** The scenario's data sets as toggles: each checked one is played by every persona. */
function DataSetChips({
  scenario,
  value,
  invalid,
  onValueChange,
}: {
  scenario: Scenario;
  value: string[];
  invalid: boolean;
  onValueChange: (ids: string[]) => void;
}) {
  const toggle = (id: string) =>
    onValueChange(
      value.includes(id)
        ? value.filter((item) => item !== id)
        : scenario.data_sets
            .map((dataSet) => dataSet.id ?? "")
            .filter((item) => item === id || value.includes(item)),
    );
  return (
    <div className="grid gap-1.5">
      <div
        role="group"
        aria-label={`Data sets of ${scenario.name}`}
        className="flex flex-wrap items-center gap-1.5"
      >
        <span className="mr-1 text-xs-400 text-muted-foreground">Data sets</span>
        {scenario.data_sets.map((dataSet) => {
          const on = value.includes(dataSet.id ?? "");
          return (
            <Button
              key={dataSet.id}
              type="button"
              size="sm"
              variant={on ? "tertiary" : "ghost"}
              aria-pressed={on}
              className={on ? undefined : "text-muted-foreground"}
              onClick={() => toggle(dataSet.id ?? "")}
            >
              {on && <Check />}
              {dataSet.name}
            </Button>
          );
        })}
      </div>
      {invalid && <FieldError>Check at least one data set.</FieldError>}
    </div>
  );
}

function LimitField({
  id,
  label,
  value,
  placeholder,
  invalid,
  error,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  placeholder: string;
  invalid: boolean;
  error: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        placeholder={placeholder}
        aria-invalid={invalid}
        className="tabular-nums"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {invalid && <FieldError>{error}</FieldError>}
    </Field>
  );
}
