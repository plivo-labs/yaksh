import type { Row, SetupStart } from "@/lib/run-setup";
import type {
  AgentSummary,
  AnsweredBy,
  Persona,
  Run,
  RunNames,
  RunScenario,
  Scenario,
  SuiteEntry,
  SuiteEntryRead,
} from "@/lib/types";

/** The cards of saved or copied scenarios. A scenario, persona or data set that is gone is left
 * out, and with `names`, the run's names, each one is named in `lost`. A scenario that lost its
 * last persona or data set keeps an empty list: the form marks it, and the user fixes it. An
 * empty list never becomes null, which means the scenario's own persona or all data sets. */
export function cardsFrom(
  items: RunScenario[],
  scenarios: Scenario[],
  personas: Persona[],
  names?: RunNames,
): { rows: Row[]; lost: string[] } {
  const live = new Map(scenarios.map((scenario) => [scenario.id, scenario]));
  const known = new Set(personas.map((persona) => persona.id));
  const rows: Row[] = [];
  const lost = new Set<string>();
  for (const item of items) {
    const scenario = live.get(item.scenario_id);
    const scenarioName = names?.scenarios[item.scenario_id] ?? scenario?.name ?? "";
    if (!scenario) {
      lost.add(`the scenario "${scenarioName}"`);
      continue;
    }
    const personaIds = item.persona_ids ?? [scenario.persona_id];
    for (const id of personaIds.filter((id) => !known.has(id))) {
      lost.add(`the persona "${names?.personas[id] ?? ""}"`);
    }
    const dataSets = scenario.data_sets.map((dataSet) => dataSet.id ?? "");
    const wanted = item.data_set_ids ?? dataSets;
    for (const id of wanted.filter((id) => !dataSets.includes(id))) {
      lost.add(
        `the data set "${names?.data_sets[item.scenario_id]?.[id] ?? ""}" of "${scenarioName}"`,
      );
    }
    rows.push({
      scenario,
      personaIds: personaIds.filter((id) => known.has(id)),
      dataSetIds: wanted.filter((id) => dataSets.includes(id)),
      answers: item.answered_by ?? ["caller"],
    });
  }
  return { rows, lost: [...lost] };
}

/** A copy of a run's settings. A run stores its time limit, turn limit and retries with the
 * defaults filled in, so they are copied as values; no max parallel and no delay stay so. A
 * connection that the agent no longer has is kept: the form asks for another one. */
export function startFromRun(run: Run): SetupStart {
  return {
    transport: run.transport,
    repeats: String(run.repeats),
    maxDuration: String(run.max_duration_s),
    maxTurns: String(run.max_turns),
    maxParallel: run.max_parallel === null ? "" : String(run.max_parallel),
    delay: run.start_interval_s === null ? "" : String(run.start_interval_s),
    retries: String(run.max_retries),
  };
}

/** A saved entry's settings, or a new entry's when there is none. */
export function startFromEntry(entry: SuiteEntry | undefined, agent: AgentSummary): SetupStart {
  const shown = (value: number | null | undefined) => (value == null ? null : String(value));
  return {
    transport: entry?.transport ?? agent.transports[0],
    repeats: String(entry?.repeats ?? 1),
    maxDuration: shown(entry?.max_duration_s),
    maxTurns: shown(entry?.max_turns),
    maxParallel: shown(entry?.max_parallel) ?? "",
    delay: shown(entry?.start_interval_s) ?? "",
    retries: shown(entry?.max_retries),
  };
}

/** The scenarios of a saved entry that play every data set, also ones added later. */
export function playingEveryDataSet(entry: SuiteEntry | undefined): Set<string> {
  const scenarios = entry && Array.isArray(entry.scenarios) ? entry.scenarios : [];
  return new Set(
    scenarios.filter((item) => item.data_set_ids == null).map((item) => item.scenario_id),
  );
}

/** The cards as an entry saves them. The personas are fixed. A scenario that played every data
 * set keeps doing so while every data set is still checked. */
export function entryScenarios(
  rows: Row[],
  answering: boolean,
  everyDataSet: ReadonlySet<string>,
): RunScenario[] {
  return rows.map((row) => {
    const all = row.scenario.data_sets.map((dataSet) => dataSet.id ?? "");
    const unchanged =
      everyDataSet.has(row.scenario.id) &&
      all.length === row.dataSetIds.length &&
      all.every((id) => row.dataSetIds.includes(id));
    const answers: AnsweredBy[] = answering ? row.answers : ["caller"];
    return {
      scenario_id: row.scenario.id,
      persona_ids: row.personaIds,
      data_set_ids: unchanged ? null : row.dataSetIds,
      answered_by: answers,
    };
  });
}

/** A dialog keeps the suite it opened with, so a newer revision means that its save would be
 * refused. */
export const SUITE_CHANGED =
  "The suite changed after you opened this dialog. Close it and open it again.";

export function passPercentOk(percent: string): boolean {
  const rate = Number(percent);
  return Number.isInteger(rate) && rate >= 1 && rate <= 100;
}

/** A read entry as a save sends it back: the read-only facts left out. */
export function asEntry(entry: SuiteEntryRead): SuiteEntry {
  return {
    agent_id: entry.agent_id,
    transport: entry.transport,
    scenarios: entry.scenarios,
    repeats: entry.repeats,
    max_duration_s: entry.max_duration_s,
    max_turns: entry.max_turns,
    max_parallel: entry.max_parallel,
    start_interval_s: entry.start_interval_s,
    max_retries: entry.max_retries,
  };
}
