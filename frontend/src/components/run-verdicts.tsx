import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Panel, PanelHeader } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Explained, Meter, OutcomeIcon, SegmentBar, Stat } from "@/components/verdict-ui";
import { percent } from "@/lib/format";
import { useJudgeAgreement, useRunMetrics } from "@/lib/queries";
import {
  CATEGORY_LABELS,
  DECIDED_BY_TEXT,
  JUDGE_TEXT,
  type JudgeAgreement,
  OUTCOME_TEXT,
  type Outcome,
  type RunVerdicts,
  type Verdict,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const FULL_COVERAGE = 0.95;

type Scenario = RunVerdicts["scenarios"][number];
type Criterion = RunVerdicts["criteria"][number];

/** The run's verdicts. The tiles answer "how did it do, and how far can I trust that" at a
 * glance; the scenario list shows which scenarios failed and opens to their criteria; how the
 * calls were judged sits last, closed. */
export function RunVerdictsPanel({ runId, active }: { runId: string; active: boolean }) {
  const metrics = useRunMetrics(runId, active);
  const agreement = useJudgeAgreement();
  if (!metrics.data) return null;
  const verdicts = metrics.data.verdicts;
  const judged = verdicts.scenarios.length > 0;
  if (!judged && verdicts.pending === 0 && verdicts.not_judged === 0) return null;
  return (
    <Panel className="overflow-hidden">
      <PanelHeader title="Verdicts" action={<Progress verdicts={verdicts} />} />
      {judged ? (
        <>
          <Scorecard verdicts={verdicts} />
          <ScenarioList verdicts={verdicts} />
          <HowJudged verdicts={verdicts} agreement={agreement.data} />
        </>
      ) : (
        <p className="px-5 py-4 text-s-400 text-muted-foreground">
          {verdicts.pending > 0
            ? "The first calls are being judged."
            : "No call was judged: the server had no judge model."}
        </p>
      )}
    </Panel>
  );
}

function Progress({ verdicts }: { verdicts: RunVerdicts }) {
  const parts = [
    verdicts.pending > 0 && `${verdicts.pending} still being judged`,
    verdicts.not_judged > 0 && `${verdicts.not_judged} not judged (no judge model)`,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return <span className="text-xs-400 text-muted-foreground">{parts.join(" · ")}</span>;
}

function tone(rate: number): "good" | "warn" | "bad" {
  return rate >= 0.8 ? "good" : rate >= 0.5 ? "warn" : "bad";
}

function Scorecard({ verdicts }: { verdicts: RunVerdicts }) {
  const full = (verdicts.coverage ?? 0) >= FULL_COVERAGE;
  const calls = verdicts.scenarios.reduce((sum, s) => sum + s.calls.length, 0);
  const scored = verdicts.scenarios.reduce((sum, s) => sum + s.scored, 0);
  const checked = verdicts.callers.reduce((sum, c) => sum + c.calls, 0);
  const likely = verdicts.callers.reduce((sum, c) => sum + c.likely, 0);
  const possible = verdicts.callers.reduce((sum, c) => sum + c.possible, 0);
  const ranged = !full && verdicts.worst !== null && verdicts.best !== null;
  const rate = ranged ? verdicts.worst : verdicts.pass_rate;
  return (
    <div className="grid grid-cols-1 gap-3 border-b bg-muted/30 px-5 py-4 sm:grid-cols-2 xl:grid-cols-4">
      <Stat
        label="Pass rate"
        hint="The mean of each scenario's pass rate, so a scenario with more calls does not count more. The band is the 95% range for this set of scenarios."
        value={
          ranged
            ? `${percent(verdicts.worst ?? 0)} to ${percent(verdicts.best ?? 0)}`
            : verdicts.pass_rate === null
              ? "None yet"
              : percent(verdicts.pass_rate)
        }
      >
        {rate !== null && (
          <Meter
            value={rate}
            low={ranged ? verdicts.worst : verdicts.interval_low}
            high={ranged ? verdicts.best : verdicts.interval_high}
            tone={tone(rate)}
            label="Pass rate"
          />
        )}
        <p className="text-xs-400 text-muted-foreground">
          {ranged
            ? "Calls that were not scored count as fails, then as passes."
            : verdicts.interval_low !== null && verdicts.interval_high !== null
              ? `95% range ${percent(verdicts.interval_low)} to ${percent(verdicts.interval_high)}`
              : "A range needs five scenarios with a scored call."}
        </p>
      </Stat>
      <Stat
        label="Both repeats pass"
        hint="The chance that two repeats of the same scenario both pass. A low value means the agent passes some tries of a scenario and fails others."
        value={verdicts.pass_hat_2 === null ? "None yet" : percent(verdicts.pass_hat_2)}
      >
        {verdicts.pass_hat_2 !== null && (
          <Meter
            value={verdicts.pass_hat_2}
            tone={tone(verdicts.pass_hat_2)}
            label="Both repeats pass"
          />
        )}
        <p className="text-xs-400 text-muted-foreground">
          {verdicts.pass_hat_2 === null
            ? "Needs two scored repeats of a scenario."
            : verdicts.inconsistent.length === 0
              ? "No scenario both passed and failed."
              : `${verdicts.inconsistent.length} ${verdicts.inconsistent.length === 1 ? "scenario" : "scenarios"} passed and failed across repeats.`}
        </p>
      </Stat>
      <Stat
        label="Scored calls"
        hint="Calls with a pass or a fail. A call is not scored when one of its items could not be decided, for example when Truman's own caller broke the test or the judge failed."
        value={
          <>
            {scored}
            <span className="text-s-400 text-muted-foreground"> of {calls}</span>
          </>
        }
      >
        <Meter value={calls ? scored / calls : 0} tone="neutral" label="Scored calls" />
        <p className="text-xs-400 text-muted-foreground">
          {calls - scored === 0
            ? "Every judged call has a verdict."
            : `${calls - scored} not scored. Below 95%, read the pass rate as a range.`}
        </p>
      </Stat>
      <Stat
        label="Truman's caller"
        hint="The caller check looks for calls where Truman's own simulated caller broke its test. A likely effect blocks the criteria it touched: they are not scored, and not blamed on the agent."
        value={
          <>
            {likely}
            <span className="text-s-400 text-muted-foreground"> likely</span>
          </>
        }
      >
        <p className="text-xs-400 text-muted-foreground">
          {checked === 0
            ? "No call was checked."
            : `Changed a result in ${likely} of ${checked} calls; ${possible} more possibly.`}
        </p>
      </Stat>
    </div>
  );
}

function ScenarioList({ verdicts }: { verdicts: RunVerdicts }) {
  const repeats = Math.max(...verdicts.scenarios.flatMap((s) => s.calls.map((c) => c.repeat)));
  const byScenario = new Map<string, Criterion[]>();
  for (const criterion of verdicts.criteria) {
    byScenario.set(criterion.scenario_id, [
      ...(byScenario.get(criterion.scenario_id) ?? []),
      criterion,
    ]);
  }
  const [open, setOpen] = useState<Set<string>>(new Set());
  const allOpen = open.size === verdicts.scenarios.length;
  const toggle = (id: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const inconsistent = new Set(verdicts.inconsistent);
  return (
    <section aria-label="Scenarios">
      <div className="flex items-center justify-between gap-3 px-5 pt-4 pb-2">
        <h3 className="text-s-500">Scenarios</h3>
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            setOpen(allOpen ? new Set() : new Set(verdicts.scenarios.map((s) => s.scenario_id)))
          }
        >
          {allOpen ? "Close all" : "Open all criteria"}
        </Button>
      </div>
      <div
        aria-hidden
        className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 border-b px-5 pb-2 text-label text-muted-foreground sm:grid-cols-[minmax(0,1fr)_auto_8rem]"
      >
        <span className="pl-6">Scenario</span>
        <span>{repeats === 1 ? "Call" : `Repeats 1 to ${repeats}`}</span>
        <span className="hidden sm:block">Passed</span>
      </div>
      <ul className="divide-y">
        {verdicts.scenarios.map((scenario) => (
          <ScenarioRow
            key={scenario.scenario_id}
            scenario={scenario}
            repeats={repeats}
            criteria={byScenario.get(scenario.scenario_id) ?? []}
            mixed={inconsistent.has(scenario.scenario_id)}
            open={open.has(scenario.scenario_id)}
            onToggle={() => toggle(scenario.scenario_id)}
          />
        ))}
      </ul>
    </section>
  );
}

const CHIP: Record<Verdict, string> = {
  pass: "bg-status-success/14 text-status-success-text",
  fail: "bg-status-danger/12 text-status-danger-text",
  not_scored: "bg-status-warning/16 text-status-warning-text",
};

const CHIP_OUTCOME: Record<Verdict, Outcome> = {
  pass: "pass",
  fail: "fail",
  not_scored: "unsure",
};

const CHIP_TEXT: Record<Verdict, string> = {
  pass: "passed",
  fail: "failed",
  not_scored: "not scored",
};

function ScenarioRow({
  scenario,
  repeats,
  criteria,
  mixed,
  open,
  onToggle,
}: {
  scenario: Scenario;
  repeats: number;
  criteria: Criterion[];
  mixed: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const byRepeat = new Map(scenario.calls.map((call) => [call.repeat, call]));
  const failing = criteria.filter((c) => c.counts.fail);
  const blocked = criteria.filter((c) => c.counts.blocked && !c.counts.fail);
  const panel = `scenario-${scenario.scenario_id}`;
  const rate = scenario.scored ? scenario.passes / scenario.scored : 0;
  return (
    <li>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-6 px-5 py-2.5 transition-colors duration-150 hover:bg-muted/40 sm:grid-cols-[minmax(0,1fr)_auto_8rem]">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panel}
          onClick={onToggle}
          className="flex min-w-0 items-start gap-2 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          <ChevronRight
            aria-hidden
            className={cn(
              "mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform duration-150 ease-out motion-reduce:transition-none",
              open && "rotate-90",
            )}
          />
          <span className="grid min-w-0 gap-0.5">
            <span className="truncate text-s-500" title={scenario.name}>
              {scenario.name}
            </span>
            <span className="flex flex-wrap items-center gap-x-2 text-xs-400 text-muted-foreground">
              <span>{CATEGORY_LABELS[scenario.category]}</span>
              {mixed && <span className="text-status-warning-text">Passed and failed</span>}
              {failing.length > 0 && (
                <span className="text-status-danger-text">
                  {failing.length} {failing.length === 1 ? "criterion" : "criteria"} failed
                </span>
              )}
              {blocked.length > 0 && <span>{blocked.length} blocked by the caller check</span>}
            </span>
          </span>
        </button>
        <div className="flex gap-1">
          {Array.from({ length: repeats }, (_, index) => index + 1).map((repeat) => {
            const call = byRepeat.get(repeat);
            if (!call) {
              return (
                <span
                  key={repeat}
                  aria-label={`Repeat ${repeat}: no judged call`}
                  className="size-6 rounded-md border border-dashed"
                />
              );
            }
            const said = call.verdict === null ? "the evaluation failed" : CHIP_TEXT[call.verdict];
            return (
              <Tooltip key={repeat}>
                <TooltipTrigger
                  render={
                    <Link
                      to={`/conversations/${call.conversation_id}`}
                      aria-label={`Repeat ${repeat} ${said}. Open the call.`}
                    />
                  }
                  className={cn(
                    "grid size-6 place-items-center rounded-md outline-none transition-transform duration-150 ease-out focus-visible:ring-2 focus-visible:ring-ring/50 active:scale-95",
                    call.verdict === null ? "bg-muted text-muted-foreground" : CHIP[call.verdict],
                  )}
                >
                  <OutcomeIcon
                    outcome={call.verdict === null ? "error" : CHIP_OUTCOME[call.verdict]}
                    className="size-3.5 text-current"
                  />
                </TooltipTrigger>
                <TooltipContent>
                  Repeat {repeat} {said}. Open the call.
                </TooltipContent>
              </Tooltip>
            );
          })}
        </div>
        <div className="hidden items-center gap-2 sm:flex">
          <Meter
            value={rate}
            tone={scenario.scored ? tone(rate) : "neutral"}
            label={`${scenario.name}: passed`}
          />
          <span className="shrink-0 text-xs-500 tabular-nums">
            {scenario.passes}/{scenario.scored}
          </span>
        </div>
      </div>
      {open && (
        <div id={panel} className="border-t bg-muted/20 py-1 pr-5 pl-11">
          {criteria.length === 0 ? (
            <p className="py-2 text-xs-400 text-muted-foreground">No criterion was judged.</p>
          ) : (
            <ol className="divide-y divide-border/60">
              {criteria.map((criterion) => (
                <CriterionRow key={criterion.number} criterion={criterion} />
              ))}
            </ol>
          )}
        </div>
      )}
    </li>
  );
}

function outcomeName(key: string): string {
  return key === "not_testable" ? "Not testable" : (OUTCOME_TEXT[key as Outcome] ?? key);
}

function CriterionRow({ criterion }: { criterion: Criterion }) {
  const total = Object.values(criterion.counts).reduce((sum, count) => sum + count, 0);
  const passed = criterion.counts.pass ?? 0;
  const detail = Object.entries(criterion.counts)
    .map(([key, count]) => `${outcomeName(key)} ${count}`)
    .join(", ");
  const problem = Boolean(criterion.counts.fail || criterion.counts.error);
  return (
    <li className="grid grid-cols-[1.25rem_minmax(0,1fr)_6rem_2.5rem] items-center gap-x-3 py-2">
      <span className="text-xs-400 text-muted-foreground tabular-nums">{criterion.number}</span>
      <span className={cn("text-s-400", !problem && "text-muted-foreground")}>
        {criterion.text}
      </span>
      <Tooltip>
        <TooltipTrigger className="w-full cursor-help rounded-sm py-1 outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
          <SegmentBar
            counts={criterion.counts}
            label={`Criterion ${criterion.number}: ${detail}`}
          />
        </TooltipTrigger>
        <TooltipContent>{detail}</TooltipContent>
      </Tooltip>
      <span className="text-right text-xs-500 tabular-nums">
        {passed}/{total}
      </span>
    </li>
  );
}

function HowJudged({
  verdicts,
  agreement,
}: {
  verdicts: RunVerdicts;
  agreement: JudgeAgreement | undefined;
}) {
  const measured = new Map(agreement?.versions.map((found) => [found.version, found.items]));
  const decided = Object.entries(verdicts.decided_by) as [keyof typeof DECIDED_BY_TEXT, number][];
  const summary = [
    decided.map(([who, count]) => `${DECIDED_BY_TEXT[who]} decided ${count}`).join(", "),
    verdicts.errors > 0 && `${verdicts.errors} not decided`,
    verdicts.judge_versions.some((v) => measured.get(v.version)?.total)
      ? "agreement with labels measured"
      : "agreement with labels not yet measured",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <details className="group border-t">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-3 outline-none select-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset [&::-webkit-details-marker]:hidden">
        <ChevronRight
          aria-hidden
          className="size-4 shrink-0 text-muted-foreground transition-transform duration-150 ease-out group-open:rotate-90 motion-reduce:transition-none"
        />
        <span className="shrink-0 text-s-500">How the calls were judged</span>
        <span className="truncate text-xs-400 text-muted-foreground">{summary}</span>
      </summary>
      <div className="grid gap-6 px-5 pt-1 pb-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <section className="grid content-start gap-2">
          <h4 className="text-label text-muted-foreground">Judges</h4>
          <ul className="divide-y rounded-md border">
            {verdicts.judge_versions.map((version) => {
              const items = measured.get(version.version);
              return (
                <li key={version.version} className="grid gap-0.5 px-3 py-2">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-s-500">{JUDGE_TEXT[version.judge] ?? version.judge}</span>
                    <span className="text-xs-400 text-muted-foreground tabular-nums">
                      {version.items} items
                    </span>
                  </div>
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-xs-400 text-muted-foreground">
                    <span>
                      {version.model} · <span className="font-mono">{version.version}</span>
                    </span>
                    {items && items.total > 0 ? (
                      <Explained
                        hint={`How often the first blind label from the audit lane agrees with this judge, over ${items.total} ${items.total === 1 ? "item" : "items"}.${items.low !== null && items.high !== null ? ` 95% range ${percent(items.low)} to ${percent(items.high)}.` : ""}`}
                      >
                        Agrees with labels {percent(items.count / items.total)}
                      </Explained>
                    ) : (
                      <span>Not yet measured on your agents</span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="text-xs-400 text-muted-foreground">
            {decided.map(([who, count]) => `${DECIDED_BY_TEXT[who]}: ${count} items`).join(" · ")}
            {verdicts.errors > 0 && ` · ${verdicts.errors} items no judge could decide`}
          </p>
        </section>
        {verdicts.callers.length > 0 && (
          <section className="grid content-start gap-2">
            <h4 className="text-label text-muted-foreground">Truman's caller, by persona</h4>
            <ul className="divide-y rounded-md border">
              {verdicts.callers.map((caller) => (
                <li
                  key={caller.persona}
                  className="flex items-baseline justify-between gap-3 px-3 py-2"
                >
                  <span className="text-s-400">{caller.persona}</span>
                  <span className="text-xs-400 text-muted-foreground tabular-nums">
                    <span
                      className={cn(caller.likely > 0 && "font-medium text-status-warning-text")}
                    >
                      {caller.likely} likely
                    </span>
                    , {caller.possible} possible, of {caller.calls}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </details>
  );
}
