/** The state of a run's setup that the run dialog and a suite's entry dialog share: the scenario
 * cards with their personas, data sets and answers, the connection, the repeats and the limits.
 * Each dialog fills the cards its own way. */

import { useState } from "react";

import { ANSWERS } from "@/lib/answering";
import { useDefaults } from "@/lib/queries";
import type { AgentSummary, AnsweredBy, RunScenario, Scenario, Transport } from "@/lib/types";

/** The answers of `wanted` in menu order, or the caller when there are none. */
export function answersToPlay(wanted?: AnsweredBy[]): AnsweredBy[] {
  const kept = ANSWERS.map((answer) => answer.value).filter((answer) => wanted?.includes(answer));
  return kept.length > 0 ? kept : ["caller"];
}

/** A whole number from an input, null when it is empty, NaN when it is not a whole number. */
function whole(value: string): number | null {
  if (value.trim() === "") return null;
  const number = Number(value);
  return Number.isInteger(number) ? number : Number.NaN;
}

export function text(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

export interface Row {
  scenario: Scenario;
  personaIds: string[];
  /** The data sets each persona plays: all of them at first. */
  dataSetIds: string[];
  /** Who answers each call: the caller at first. Phone runs of an outbound agent only. */
  answers: AnsweredBy[];
}

/** A new card: the scenario's own persona, every data set and the caller. */
export function newRow(scenario: Scenario): Row {
  return {
    scenario,
    personaIds: [scenario.persona_id],
    dataSetIds: scenario.data_sets.map((dataSet) => dataSet.id ?? ""),
    answers: answersToPlay(),
  };
}

/** The settings that start a setup. A limit that is null shows the server's default until the
 * user types, and is sent as null. */
export interface SetupStart {
  transport: Transport;
  repeats: string;
  maxDuration: string | null;
  maxTurns: string | null;
  maxParallel: string;
  delay: string;
  retries: string | null;
}

export type RunSetup = ReturnType<typeof useRunSetup>;

export function useRunSetup(agent: AgentSummary, start: SetupStart) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [transport, setTransport] = useState<Transport>(start.transport);
  const [repeats, setRepeats] = useState(start.repeats);
  const [maxDuration, setMaxDuration] = useState(start.maxDuration);
  const [maxTurns, setMaxTurns] = useState(start.maxTurns);
  const [maxParallel, setMaxParallel] = useState(start.maxParallel);
  const [delay, setDelay] = useState(start.delay);
  const [retries, setRetries] = useState(start.retries);
  const [editLimits, setEditLimits] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const defaults = useDefaults();

  // Voicemail and call screening answer the calls that Yaksh receives from an outbound agent.
  const phone = transport === "phone";
  const outbound = agent.direction === "outbound";
  const answering = phone && outbound;
  /** A saved or copied connection can be one that the agent no longer has. */
  const transportOk = agent.transports.includes(transport);
  const [one, many] = transport === "text" ? ["conversation", "conversations"] : ["call", "calls"];
  const scenarios = (rows ?? []).map((row) => row.scenario);
  const cards = Object.fromEntries((rows ?? []).map((row) => [row.scenario.id, row.personaIds]));
  const played = Object.fromEntries((rows ?? []).map((row) => [row.scenario.id, row.dataSetIds]));
  const answered = Object.fromEntries(
    (rows ?? []).map((row): [string, AnsweredBy[]] => [
      row.scenario.id,
      answering ? row.answers : ["caller"],
    ]),
  );

  const setRow = (scenarioId: string, change: Partial<Row>) =>
    setRows((current) =>
      (current ?? []).map((row) => (row.scenario.id === scenarioId ? { ...row, ...change } : row)),
    );
  const setPersonas = (change: (row: Row) => string[]) =>
    setRows((current) => (current ?? []).map((row) => ({ ...row, personaIds: change(row) })));

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
  const different = scenarios.reduce(
    (sum, scenario) =>
      sum +
      (cards[scenario.id]?.length ?? 0) *
        (played[scenario.id]?.length ?? 0) *
        (answered[scenario.id]?.length ?? 0),
    0,
  );

  return {
    rows,
    setRows,
    setRow,
    setPersonas,
    removeScenario: (scenarioId: string) =>
      setRows((current) => (current ?? []).filter((row) => row.scenario.id !== scenarioId)),
    addScenario: (scenario: Scenario) =>
      setRows((current) => [...(current ?? []), newRow(scenario)]),
    transport,
    setTransport,
    transportOk,
    repeats,
    setRepeats,
    durationText,
    setMaxDuration,
    turnsText,
    setMaxTurns,
    maxParallel,
    setMaxParallel,
    delay,
    setDelay,
    retriesText,
    setRetries,
    editLimits,
    setEditLimits,
    submitted,
    setSubmitted,
    phone,
    outbound,
    answering,
    one,
    many,
    scenarios,
    cards,
    played,
    answered,
    repeatCount,
    repeatsOk,
    durationOk,
    turnsOk,
    parallelOk,
    intervalOk,
    retriesOk,
    limitsOk,
    empty,
    unplayed,
    /** Every card has a persona and a data set, and the numbers are whole and in range. */
    cardsOk: rows !== null && scenarios.length > 0 && empty.length === 0 && unplayed.length === 0,
    different,
    total: different * (repeatsOk && repeatCount !== null ? repeatCount : 0),
    personaCount: new Set(scenarios.flatMap((scenario) => cards[scenario.id] ?? [])).size,
    dataSetCount: scenarios.reduce((sum, scenario) => sum + (played[scenario.id]?.length ?? 0), 0),
    times: !repeatsOk
      ? ""
      : repeatCount === 1
        ? "once"
        : repeatCount === 2
          ? "twice"
          : `${repeatCount} times`,
    limits: [
      ["Time limit", duration === null ? "Default" : `${duration} s`],
      ["Turn limit", turns === null ? "Default" : `${turns} turns`],
      ["At once", parallel === null ? "No run limit" : String(parallel)],
      ["Delay", interval === null ? "None" : `${interval} s`],
      ["Retries", retryCount === null ? "Default" : `Up to ${retryCount}`],
    ] as [string, string][],
    /** The cards as a run request lists them. One data set is sent as null, every data set. */
    runScenarios: (): RunScenario[] =>
      scenarios.map((scenario) => ({
        scenario_id: scenario.id,
        persona_ids: cards[scenario.id],
        data_set_ids: scenario.data_sets.length > 1 ? played[scenario.id] : null,
        answered_by: answered[scenario.id],
      })),
    /** The settings as a request sends them. Untouched fields go as null, for the defaults they
     * show: a resent request then stays the same whether or not the defaults had loaded. */
    settings: () => ({
      repeats: repeatCount ?? 1,
      max_duration_s: maxDuration === null ? null : duration,
      max_turns: maxTurns === null ? null : turns,
      max_parallel: parallel,
      start_interval_s: interval,
      max_retries: retries === null ? null : retryCount,
    }),
  };
}
