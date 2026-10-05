import { useState } from "react";
import { Link } from "react-router";

import { Fact, Panel, PanelHeader } from "@/components/panel";
import { StatusLabel } from "@/components/status-label";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { percent } from "@/lib/format";
import { useJudgeAgreement, useRunMetrics } from "@/lib/queries";
import { VERDICT_TONE } from "@/lib/status";
import {
  CATEGORY_LABELS,
  DECIDED_BY_TEXT,
  JUDGE_TEXT,
  type JudgeAgreement,
  OUTCOME_TEXT,
  type Outcome,
  type RunVerdicts,
  VERDICT_TEXT,
} from "@/lib/types";

const FULL_COVERAGE = 0.95;

/** The run's verdicts over its judged calls: the pass rate, how far to trust it, each
 * scenario's repeats, each criterion, the caller check and the judges that decided. */
export function RunVerdictsPanel({ runId, active }: { runId: string; active: boolean }) {
  const metrics = useRunMetrics(runId, active);
  const agreement = useJudgeAgreement();
  if (!metrics.data) return null;
  const verdicts = metrics.data.verdicts;
  const judged = verdicts.scenarios.length > 0;
  if (!judged && verdicts.pending === 0 && verdicts.not_judged === 0) return null;
  return (
    <Panel className="overflow-hidden">
      <PanelHeader title="Verdicts" />
      <p className="border-b px-5 py-2.5 text-xs text-muted-foreground">
        Over the judged calls: the latest attempt of each repeat that completed and that no one
        stopped. The pass rate is the mean of the scenarios' pass rates, so a scenario with more
        calls does not count more.
        {verdicts.pending > 0 && ` ${verdicts.pending} calls are still being judged.`}
        {verdicts.not_judged > 0 &&
          ` ${verdicts.not_judged} calls were not judged: the server had no judge model.`}
      </p>
      {judged && (
        <>
          <Numbers verdicts={verdicts} />
          <ScenarioGrid verdicts={verdicts} />
          <Criteria verdicts={verdicts} />
          <Callers verdicts={verdicts} />
          <Judges verdicts={verdicts} agreement={agreement.data} />
        </>
      )}
    </Panel>
  );
}

function Numbers({ verdicts }: { verdicts: RunVerdicts }) {
  const full = (verdicts.coverage ?? 0) >= FULL_COVERAGE;
  const decided = Object.entries(verdicts.decided_by) as [keyof typeof DECIDED_BY_TEXT, number][];
  return (
    <dl className="grid grid-cols-1 gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-4">
      <Fact wrap label={full ? "Pass rate" : "Pass rate, worst to best"}>
        {full || verdicts.worst === null || verdicts.best === null
          ? rate(verdicts.pass_rate)
          : `${percent(verdicts.worst)} to ${percent(verdicts.best)}`}
      </Fact>
      <Fact wrap label="Scored calls">
        {rate(verdicts.coverage)}
        {!full && ": the range counts the unscored calls as fails, then as passes"}
      </Fact>
      <Fact wrap label='"This suite" 95% interval'>
        {verdicts.interval_low === null || verdicts.interval_high === null
          ? "Needs five scenarios with a scored call"
          : `${percent(verdicts.interval_low)} to ${percent(verdicts.interval_high)}`}
      </Fact>
      <Fact wrap label="Two repeats both pass">
        {verdicts.pass_hat_2 === null
          ? "Needs two scored repeats"
          : `${percent(verdicts.pass_hat_2)}, over ${verdicts.pass_hat_2_scenarios} scenarios`}
      </Fact>
      <Fact wrap label="Passed and failed across repeats">
        {verdicts.inconsistent.length === 0
          ? "No scenario"
          : `${verdicts.inconsistent.length} ${verdicts.inconsistent.length === 1 ? "scenario" : "scenarios"}`}
      </Fact>
      <Fact wrap label="Decided by">
        {decided.map(([who, count]) => `${DECIDED_BY_TEXT[who]} ${count}`).join(", ") || "None"}
        {verdicts.errors > 0 && `; ${verdicts.errors} no judge could decide`}
      </Fact>
    </dl>
  );
}

function rate(value: number | null): string {
  return value === null ? "None yet" : percent(value);
}

function ScenarioGrid({ verdicts }: { verdicts: RunVerdicts }) {
  const repeats = Math.max(
    ...verdicts.scenarios.flatMap((scenario) => scenario.calls.map((call) => call.repeat)),
  );
  const columns = Array.from({ length: repeats }, (_, index) => index + 1);
  const inconsistent = new Set(verdicts.inconsistent);
  return (
    <Table className="border-t">
      <TableHeader>
        <TableRow>
          <TableHead className="pl-5">Scenario</TableHead>
          <TableHead>Category</TableHead>
          {columns.map((repeat) => (
            <TableHead key={repeat}>Repeat {repeat}</TableHead>
          ))}
          <TableHead className="pr-5">Passed</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {verdicts.scenarios.map((scenario) => {
          const byRepeat = new Map(scenario.calls.map((call) => [call.repeat, call]));
          return (
            <TableRow key={scenario.scenario_id}>
              <TableCell className="max-w-72 truncate pl-5" title={scenario.name}>
                {scenario.name}
                {inconsistent.has(scenario.scenario_id) && (
                  <span className="ml-2 text-xs text-status-warning-text">mixed</span>
                )}
              </TableCell>
              <TableCell>{CATEGORY_LABELS[scenario.category]}</TableCell>
              {columns.map((repeat) => {
                const call = byRepeat.get(repeat);
                return (
                  <TableCell key={repeat}>
                    {call && (
                      <Link
                        to={`/conversations/${call.conversation_id}`}
                        className="rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
                      >
                        {call.verdict === null ? (
                          <StatusLabel tone="red">Evaluation failed</StatusLabel>
                        ) : (
                          <StatusLabel tone={VERDICT_TONE[call.verdict]}>
                            {VERDICT_TEXT[call.verdict]}
                          </StatusLabel>
                        )}
                      </Link>
                    )}
                  </TableCell>
                );
              })}
              <TableCell className="pr-5 tabular-nums">
                {scenario.passes} of {scenario.scored}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/** The criteria that did not always pass; all of them on request, since a run has a row for
 * each criterion of each scenario. */
function Criteria({ verdicts }: { verdicts: RunVerdicts }) {
  const [all, setAll] = useState(false);
  if (verdicts.criteria.length === 0) return null;
  const names = new Map(
    verdicts.scenarios.map((scenario) => [scenario.scenario_id, scenario.name]),
  );
  const mixed = verdicts.criteria.filter((criterion) =>
    Object.keys(criterion.counts).some((outcome) => outcome !== "pass"),
  );
  const shown = all ? verdicts.criteria : mixed;
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t px-5 py-3">
        <h3 className="text-xs-400 text-muted-foreground">
          {all
            ? `All ${verdicts.criteria.length} criteria`
            : mixed.length === 0
              ? `All ${verdicts.criteria.length} criteria passed every time`
              : `${mixed.length} of ${verdicts.criteria.length} criteria did not always pass`}
        </h3>
        {mixed.length < verdicts.criteria.length && (
          <Button variant="ghost" size="sm" onClick={() => setAll(!all)}>
            {all ? "Show the ones that did not pass" : "Show all criteria"}
          </Button>
        )}
      </div>
      {shown.length > 0 && <CriteriaTable criteria={shown} names={names} />}
    </>
  );
}

function CriteriaTable({
  criteria,
  names,
}: {
  criteria: RunVerdicts["criteria"];
  names: Map<string, string>;
}) {
  return (
    <Table className="border-t">
      <TableHeader>
        <TableRow>
          <TableHead className="pl-5">Criterion</TableHead>
          <TableHead>Scenario</TableHead>
          <TableHead>Pass rate</TableHead>
          <TableHead className="pr-5">Outcomes</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {criteria.map((criterion) => (
          <TableRow key={`${criterion.scenario_id}-${criterion.number}`}>
            <TableCell className="max-w-96 pl-5 whitespace-normal">{criterion.text}</TableCell>
            <TableCell className="max-w-48 truncate">{names.get(criterion.scenario_id)}</TableCell>
            <TableCell className="tabular-nums">
              {criterion.rate === null ? "No pass or fail" : percent(criterion.rate)}
            </TableCell>
            <TableCell className="pr-5 whitespace-normal text-muted-foreground">
              {Object.entries(criterion.counts)
                .map(([outcome, count]) => `${outcomeText(outcome)} ${count}`)
                .join(", ")}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function outcomeText(outcome: string): string {
  if (outcome === "not_testable") return "Not testable";
  return OUTCOME_TEXT[outcome as Outcome] ?? outcome;
}

function Callers({ verdicts }: { verdicts: RunVerdicts }) {
  if (verdicts.callers.length === 0) return null;
  return (
    <div className="grid gap-1 border-t px-5 py-4">
      <h3 className="text-xs-400 text-muted-foreground">
        Truman's caller, by the caller check: calls where it likely or possibly changed a result
      </h3>
      <ul className="grid gap-0.5 text-s-400">
        {verdicts.callers.map((caller) => (
          <li key={caller.persona}>
            {caller.persona}: {caller.likely} likely, {caller.possible} possibly, of {caller.calls}{" "}
            checked
          </li>
        ))}
      </ul>
    </div>
  );
}

function Judges({
  verdicts,
  agreement,
}: {
  verdicts: RunVerdicts;
  agreement: JudgeAgreement | undefined;
}) {
  if (verdicts.judge_versions.length === 0) return null;
  const measured = new Map(agreement?.versions.map((found) => [found.version, found.items]));
  return (
    <div className="grid gap-1 border-t px-5 py-4">
      <h3 className="text-xs-400 text-muted-foreground">
        Judges, and how often blind labels from the audit lane agree with them
      </h3>
      <ul className="grid gap-0.5 text-s-400">
        {verdicts.judge_versions.map((version) => {
          const items = measured.get(version.version);
          return (
            <li key={version.version} className="wrap-anywhere">
              {JUDGE_TEXT[version.judge] ?? version.judge}, {version.model},{" "}
              <span className="font-mono text-xs">{version.version}</span>: {version.items} items;{" "}
              {items && items.total > 0
                ? `agreement ${percent(items.count / items.total)} of ${items.total} ${items.total === 1 ? "label" : "labels"}${
                    items.low !== null && items.high !== null
                      ? ` (95%: ${percent(items.low)} to ${percent(items.high)})`
                      : ""
                  }`
                : "not yet measured on your agents"}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
