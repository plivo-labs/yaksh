import { Check, ChevronDown, Shuffle, XIcon } from "lucide-react";
import { Fragment, type ReactNode, useState } from "react";

import { PersonaChips } from "@/components/persona-chips";
import { ScenarioAdder } from "@/components/scenario-adder";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ANSWERS, DEFAULT_ANSWERING, withoutVerdict } from "@/lib/answering";
import { counted } from "@/lib/format";
import { mixPersonas } from "@/lib/mix";
import { type Row, type RunSetup, answersToPlay } from "@/lib/run-setup";
import {
  AGENT_LANGUAGES,
  type AgentRule,
  type AgentSummary,
  type AnsweredBy,
  type Answering,
  type Language,
  LANGUAGE_NAMES,
  type Persona,
  type Scenario,
  type Transport,
  servedLanguages,
} from "@/lib/types";

const CONNECTIONS: { value: Transport; label: string }[] = [
  { value: "phone", label: "Phone" },
  { value: "text", label: "Text" },
];

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

/** The scenario cards, then a button that adds one of the agent's other scenarios. */
export function ScenarioCards({
  setup,
  personas,
  served,
  rules,
  everyScenario,
  noun,
}: {
  setup: RunSetup;
  personas: Persona[];
  served: ReadonlySet<Language>;
  rules: AgentRule[] | undefined;
  everyScenario: Scenario[];
  /** What a removed scenario leaves: "this run" or "this agent". */
  noun: string;
}) {
  const byId = new Map(personas.map((persona) => [persona.id, persona]));
  const { submitted, answering, repeatsOk, repeatCount, one, many } = setup;
  return (
    <>
      {setup.scenarios.map((scenario) => {
        const ids = setup.cards[scenario.id] ?? [];
        const foreign = ids
          .map((id) => byId.get(id))
          .filter((persona) => persona && !served.has(persona.language));
        const sets = setup.played[scenario.id] ?? [];
        const answers = setup.answered[scenario.id] ?? [];
        const calls =
          ids.length * sets.length * answers.length * (repeatsOk && repeatCount ? repeatCount : 0);
        const settings = ids.map((id) => byId.get(id)?.answering ?? DEFAULT_ANSWERING);
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
                    onValueChange={(next) => setup.setRow(scenario.id, { answers: next })}
                  />
                )}
                <span className="text-xs-400 text-muted-foreground tabular-nums">
                  {counted(calls, one, many)}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${scenario.name} from ${noun}`}
                  title={`Remove from ${noun}`}
                  className="-mt-0.5 flex size-6 items-center justify-center rounded-sm text-muted-foreground hover:bg-hv1 hover:text-foreground"
                  onClick={() => setup.removeScenario(scenario.id)}
                >
                  <XIcon className="size-3.5" />
                </button>
              </span>
            </div>
            <PersonaChips
              label={scenario.name}
              personas={personas}
              value={ids}
              served={served}
              invalid={submitted && ids.length === 0}
              onValueChange={(next) => setup.setRow(scenario.id, { personaIds: next })}
            />
            {(scenario.data_sets.length > 1 || sets.length === 0) && (
              <DataSetChips
                scenario={scenario}
                value={sets}
                invalid={submitted && sets.length === 0}
                onValueChange={(next) => setup.setRow(scenario.id, { dataSetIds: next })}
              />
            )}
            {foreign.map(
              (persona) =>
                persona && (
                  <p key={persona.id} className="text-xs-400 text-status-warning-text">
                    {persona.name} speaks {LANGUAGE_NAMES[persona.language]}, which the agent does
                    not serve.
                  </p>
                ),
            )}
            <NoVerdictNote answers={answers} rules={rules} personas={settings} />
          </div>
        );
      })}
      {setup.rows !== null && (
        <ScenarioAdder
          scenarios={everyScenario.filter(
            (scenario) => !setup.scenarios.some((shown) => shown.id === scenario.id),
          )}
          onAdd={setup.addScenario}
        />
      )}
    </>
  );
}

/** Names the voicemail or screener answers whose calls get no verdict: no deciding rule checks
 * them for these personas' answering settings. */
export function NoVerdictNote({
  answers,
  rules,
  personas,
}: {
  answers: AnsweredBy[];
  rules: AgentRule[] | undefined;
  personas: Answering[];
}) {
  const unjudged = rules
    ? answers.filter(
        (answer): answer is keyof typeof MACHINE_CALLS =>
          answer !== "caller" && withoutVerdict(answer, rules, personas),
      )
    : [];
  if (unjudged.length === 0) return null;
  return (
    <p className="text-xs-400 text-status-warning-text">
      No rule decides {unjudged.map((answer) => MACHINE_CALLS[answer]).join(" or ")}, so they get no
      verdict.
    </p>
  );
}

/** Personas for every card at once: a mix from one language, one more persona, or each
 * scenario's own persona again. */
export function MixPersonas({
  setup,
  agent,
  personas,
}: {
  setup: RunSetup;
  agent: AgentSummary;
  personas: Persona[];
}) {
  const served = servedLanguages(agent.languages);
  const [open, setOpen] = useState(false);
  const [size, setSize] = useState("3");
  const [language, setLanguage] = useState<Language>(AGENT_LANGUAGES[agent.languages[0]].language);
  const pool = personas.filter((persona) => persona.language === language);
  const changed = (setup.rows ?? []).some(
    (row) => row.personaIds.length !== 1 || row.personaIds[0] !== row.scenario.persona_id,
  );
  const apply = (change: (row: Row) => string[]) => {
    setup.setPersonas(change);
    setOpen(false);
  };
  const mix = () => {
    const mixed = mixPersonas(
      setup.scenarios,
      pool.map((persona) => persona.id),
      Number(size),
    );
    apply((row) => mixed[row.scenario.id]);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={<Button type="button" variant="outline" size="sm" disabled={setup.rows === null} />}
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
              value={size}
              onValueChange={(value) => value && setSize(value)}
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
                items={[...served].map((item) => ({ value: item, label: LANGUAGE_NAMES[item] }))}
                value={language}
                onValueChange={(value) => value && setLanguage(value as Language)}
              >
                <SelectTrigger aria-label="Language of the personas" className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {[...served].map((item) => (
                      <SelectItem key={item} value={item}>
                        {LANGUAGE_NAMES[item]}
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
            title={`Each scenario keeps its own persona. The others come from the ${pool.length} ${LANGUAGE_NAMES[language]} personas, and each is used once before any is used twice.`}
          >
            Includes each scenario's own persona.
          </p>
        </div>
        <div className="grid gap-2 border-t p-4">
          <span className="text-s-500">Add a persona to every scenario</span>
          <Select
            items={personas.map((persona) => ({ value: persona.id, label: persona.name }))}
            value={null}
            onValueChange={(value) =>
              value &&
              apply((row) =>
                row.personaIds.includes(value) ? row.personaIds : [...row.personaIds, value],
              )
            }
          >
            <SelectTrigger aria-label="Persona to add" className="w-full">
              <SelectValue placeholder="Choose a persona" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {personas.map((persona) => (
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
            onClick={() => apply((row) => [row.scenario.persona_id])}
          >
            Reset to scenario personas
          </button>
        )}
      </PopoverContent>
    </Popover>
  );
}

/** The connection, the repeats and the limits. `children` comes after the connection. With
 * `fixedConnection`, an agent with one connection shows it, unchangeable. */
export function RunSettings({
  setup,
  agent,
  idPrefix,
  fixedConnection = false,
  children,
}: {
  setup: RunSetup;
  agent: AgentSummary;
  idPrefix: string;
  fixedConnection?: boolean;
  children?: ReactNode;
}) {
  const { submitted, one, many } = setup;
  const both = agent.transports.length > 1;
  return (
    <>
      <div className="grid gap-4">
        {(both || fixedConnection) && (
          <Field>
            <FieldLabel htmlFor={`${idPrefix}-transport`}>Connection</FieldLabel>
            <Select
              items={CONNECTIONS}
              value={setup.transport}
              disabled={!both && setup.transportOk}
              onValueChange={(value) => value && setup.setTransport(value)}
            >
              <SelectTrigger
                id={`${idPrefix}-transport`}
                aria-invalid={!setup.transportOk}
                className="w-full"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {CONNECTIONS.map((item) => (
                    <SelectItem
                      key={item.value}
                      value={item.value}
                      disabled={!agent.transports.includes(item.value)}
                    >
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            {setup.transportOk ? (
              <FieldDescription>
                {both
                  ? "The agent has both. Each run uses one."
                  : `The agent has ${setup.transport} only.`}
              </FieldDescription>
            ) : (
              <FieldError>
                The agent no longer has {setup.transport}. Choose {agent.transports.join(" or ")}.
              </FieldError>
            )}
          </Field>
        )}
        {children}
        <Field>
          <FieldLabel htmlFor={`${idPrefix}-repeats`}>Repeats</FieldLabel>
          <Input
            id={`${idPrefix}-repeats`}
            type="number"
            inputMode="numeric"
            min={1}
            aria-invalid={submitted && !setup.repeatsOk}
            className="tabular-nums"
            value={setup.repeats}
            onChange={(event) => setup.setRepeats(event.target.value)}
          />
          <FieldDescription>How many times each {one} runs.</FieldDescription>
          {submitted && !setup.repeatsOk && <FieldError>Enter a whole number from 1.</FieldError>}
        </Field>
      </div>

      <div className="grid gap-1">
        <div className="flex items-baseline justify-between">
          <span className="text-label text-secondary">Limits</span>
          <button
            type="button"
            className="text-s-400 text-brand-text"
            aria-expanded={setup.editLimits}
            onClick={() => setup.setEditLimits((current) => !current)}
          >
            {setup.editLimits ? "Done" : "Edit"}
          </button>
        </div>
        {setup.editLimits ? (
          <div className="grid gap-3 pt-2">
            <LimitField
              id={`${idPrefix}-duration`}
              label="Time limit, seconds"
              value={setup.durationText}
              placeholder="Default"
              invalid={submitted && !setup.durationOk}
              error="Enter a whole number from 10 to 1800, or none."
              onChange={setup.setMaxDuration}
            />
            <LimitField
              id={`${idPrefix}-turns`}
              label="Turn limit"
              value={setup.turnsText}
              placeholder="Default"
              invalid={submitted && !setup.turnsOk}
              error="Enter a whole number from 1 to 100, or none."
              onChange={setup.setMaxTurns}
            />
            <LimitField
              id={`${idPrefix}-parallel`}
              label="Max parallel"
              value={setup.maxParallel}
              placeholder="No run limit"
              invalid={submitted && !setup.parallelOk}
              error="Enter a whole number from 1, or none."
              onChange={setup.setMaxParallel}
            />
            <LimitField
              id={`${idPrefix}-delay`}
              label={`Delay between ${many}, seconds`}
              value={setup.delay}
              placeholder="None"
              invalid={submitted && !setup.intervalOk}
              error="Enter a whole number from 1, or none."
              onChange={setup.setDelay}
            />
            <LimitField
              id={`${idPrefix}-retries`}
              label="Retries"
              value={setup.retriesText}
              placeholder="Default"
              invalid={submitted && !setup.retriesOk}
              error="Enter a whole number from 0, or none."
              onChange={setup.setRetries}
            />
          </div>
        ) : (
          <dl className="grid">
            {setup.limits.map(([label, value]) => (
              <div key={label} className="flex justify-between border-t py-1.5 text-s-400">
                <dt className="text-muted-foreground">{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </>
  );
}

/** Who answers the scenario's calls, as a menu of checkboxes. The last checked answer is locked,
 * because each scenario needs at least one. */
export function AnswersMenu({
  value,
  onValueChange,
}: {
  value: AnsweredBy[];
  onValueChange: (answers: AnsweredBy[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const label = answersText(value);
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
            aria-label={`Answered by: ${label}`}
            className="-my-0.5 flex h-6 items-center gap-1 rounded-sm bg-muted pr-1.5 pl-2 text-xs-500 hover:bg-hv1"
          />
        }
      >
        {label}
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
