import { ChevronRight } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";

import { EffortSelect } from "@/components/effort-select";
import { ModelCombobox } from "@/components/model-combobox";
import { Panel, PanelHeader } from "@/components/panel";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MAX_DATA_SETS } from "@/lib/types";
import { RISE } from "@/lib/motion";
import { useSaveSettingsValues, useSettings } from "@/lib/queries";
import type { AppSettings, SettingsValues } from "@/lib/types";
import { KeyRow, ProviderPanel, SettingRow } from "@/pages/settings-keys";
import { PhoneAccountPanel } from "@/pages/settings-phone";
import { ImportExport } from "@/pages/settings-import";
import { TriggersPanel } from "@/pages/settings-triggers";

const TABS = [
  { value: "providers", label: "Providers" },
  { value: "models", label: "Models" },
  { value: "phone", label: "Phone" },
  { value: "limits", label: "Limits" },
] as const;

type Tab = (typeof TABS)[number]["value"];
type Section = keyof SettingsValues;
type Change = <S extends Section, K extends keyof SettingsValues[S]>(
  section: S,
  key: K,
  value: SettingsValues[S][K],
) => void;

/** The settings of this Yaksh. Keys save one by one, after their provider accepts them; the
 * other values save together from the bar at the bottom. A change applies to the next call. */
export function SettingsPage() {
  const settings = useSettings();
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.find((item) => item.value === params.get("tab"))?.value ?? "providers";
  const header = (
    <div className="flex min-h-[30px] flex-wrap items-center gap-x-2 gap-y-4">
      <h1 className="mr-auto text-h3-500">Settings</h1>
      <ImportExport />
    </div>
  );
  return (
    <div className="flex min-h-full max-w-5xl flex-col gap-6">
      {settings.data === undefined && header}
      {settings.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load the settings</AlertTitle>
          <AlertDescription>{settings.error.message}</AlertDescription>
        </Alert>
      ) : settings.data === undefined ? (
        <div className="grid gap-4">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} className="h-40" />
          ))}
        </div>
      ) : (
        <Form
          settings={settings.data}
          header={header}
          tab={tab}
          onTab={(next) => setParams({ tab: next }, { replace: true })}
        />
      )}
    </div>
  );
}

function Form({
  settings,
  header,
  tab,
  onTab,
}: {
  settings: AppSettings;
  header: ReactNode;
  tab: Tab;
  onTab: (tab: Tab) => void;
}) {
  const [draft, setDraft] = useState(settings.values);
  const [base, setBase] = useState(settings.values);
  const saved = JSON.stringify(settings.values);
  if (saved !== JSON.stringify(base)) {
    // The saved values changed, here or in another tab: an untouched form follows them.
    setBase(settings.values);
    if (JSON.stringify(draft) === JSON.stringify(base)) setDraft(settings.values);
    // The Phone account panel saves the receiving application on its own; a changed form takes
    // it over, so saving the form does not undo that choice.
    else
      setDraft({
        ...draft,
        phone: { ...draft.phone, application_id: settings.values.phone.application_id },
      });
  }
  const save = useSaveSettingsValues();
  const dirty = JSON.stringify(draft) !== saved;
  const change: Change = (section, key, value) =>
    setDraft((current) => ({ ...current, [section]: { ...current[section], [key]: value } }));
  const secrets = settings.secrets;
  const llmMoved = draft.llm.base_url !== settings.values.llm.base_url;
  const deepgramMoved = draft.deepgram.base_url !== settings.values.deepgram.base_url;

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  return (
    <>
      <Tabs value={tab} onValueChange={(next) => onTab(next as Tab)} className="gap-5">
        {/* The title and the tabs stay in view; only the panels below them scroll. The negative
            margins reach over the shell's padding, so nothing shows above the header. */}
        <div className="sticky -top-5 z-10 -mx-6 -mt-5 grid gap-4 bg-background px-6 pt-5">
          {header}
          <TabsList variant="line">
            {TABS.map((item) => (
              <TabsTrigger key={item.value} value={item.value}>
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <TabsContent value="providers" className="grid gap-5">
          <ProviderPanel
            title="LLM provider"
            provider="llm"
            canTest={Boolean(secrets.llm_api_key) && !llmMoved}
            description="Any API with OpenAI's Responses endpoint, such as OpenAI or Azure OpenAI. Used by the caller, scenario writing and the judges."
          >
            <SettingRow
              label="Base URL"
              htmlFor="llm-url"
              help={keyRemovedBy(llmMoved && secrets.llm_api_key)}
            >
              <Input
                id="llm-url"
                value={draft.llm.base_url}
                onChange={(event) => change("llm", "base_url", event.target.value.trim())}
              />
            </SettingRow>
            <KeyRow
              name="llm_api_key"
              label="API key"
              state={secrets.llm_api_key}
              url={draft.llm.base_url}
              checked
            />
          </ProviderPanel>
          <ProviderPanel
            title="Deepgram"
            description="Speech to text."
            provider="deepgram"
            canTest={Boolean(secrets.deepgram_api_key) && !deepgramMoved}
          >
            <SettingRow
              label="Base URL"
              htmlFor="deepgram-url"
              help={keyRemovedBy(deepgramMoved && secrets.deepgram_api_key)}
            >
              <Input
                id="deepgram-url"
                value={draft.deepgram.base_url}
                onChange={(event) => change("deepgram", "base_url", event.target.value.trim())}
              />
            </SettingRow>
            <SettingRow label="Model" htmlFor="deepgram-model">
              <Input
                id="deepgram-model"
                className="max-w-56"
                value={draft.deepgram.model}
                onChange={(event) => change("deepgram", "model", event.target.value)}
              />
            </SettingRow>
            <KeyRow
              name="deepgram_api_key"
              label="API key"
              state={secrets.deepgram_api_key}
              url={draft.deepgram.base_url}
              checked
            />
          </ProviderPanel>
          <ProviderPanel
            title="ElevenLabs"
            description="Text to speech."
            provider="elevenlabs"
            canTest={Boolean(secrets.elevenlabs_api_key)}
          >
            <KeyRow
              name="elevenlabs_api_key"
              label="API key"
              state={secrets.elevenlabs_api_key}
              checked
            />
          </ProviderPanel>
          <ProviderPanel
            title="TypeSafe"
            provider="typesafe"
            canTest={Boolean(secrets.typesafe_api_key)}
            description="Optional. Transcripts are sent to TypeSafe."
          >
            <KeyRow
              name="typesafe_api_key"
              label="API key"
              state={secrets.typesafe_api_key}
              removable
              checked
            />
          </ProviderPanel>
        </TabsContent>

        <TabsContent value="models" className="grid gap-5">
          <Panel>
            <PanelHeader title="Caller" />
            <SettingRow
              label="Model"
              htmlFor="caller-model"
              help={
                draft.caller.model.startsWith("gpt-4.1") && (
                  <span className="text-warning-foreground">
                    gpt-4.1 can speak several replies at once.
                  </span>
                )
              }
            >
              <ModelCombobox
                id="caller-model"
                value={draft.caller.model}
                onValueChange={(model) => model && change("caller", "model", model)}
              />
            </SettingRow>
            <SettingRow label="Reasoning effort" htmlFor="caller-effort">
              <EffortSelect
                id="caller-effort"
                model={draft.caller.model}
                value={draft.caller.reasoning_effort}
                onValueChange={(effort) => change("caller", "reasoning_effort", effort)}
                unset="none"
                hidden={["none"]}
              />
            </SettingRow>
          </Panel>
          <Panel>
            <PanelHeader title="Scenario writing" />
            <SettingRow label="Model" htmlFor="generation-model">
              <ModelCombobox
                id="generation-model"
                value={draft.generation.model}
                inherit={draft.caller.model}
                onValueChange={(model) => change("generation", "model", model)}
              />
            </SettingRow>
            <SettingRow label="Reasoning effort" htmlFor="generation-effort">
              <EffortSelect
                id="generation-effort"
                model={draft.generation.model ?? draft.caller.model}
                value={draft.generation.reasoning_effort}
                onValueChange={(effort) => change("generation", "reasoning_effort", effort)}
                unset="default"
              />
            </SettingRow>
            <NumberRow
              id="generation-timeout"
              label="Request timeout"
              unit="seconds"
              value={draft.generation.timeout_s}
              onValueChange={(value) => change("generation", "timeout_s", value)}
            />
          </Panel>
          <Panel>
            <PanelHeader title="Brief drafting" />
            <SettingRow
              label="Model"
              htmlFor="brief-model"
              help="Drafts an agent's brief while you wait."
            >
              <ModelCombobox
                id="brief-model"
                value={draft.brief.model}
                onValueChange={(model) => model && change("brief", "model", model)}
              />
            </SettingRow>
            <SettingRow label="Reasoning effort" htmlFor="brief-effort">
              <EffortSelect
                id="brief-effort"
                model={draft.brief.model}
                value={draft.brief.reasoning_effort}
                onValueChange={(effort) => change("brief", "reasoning_effort", effort)}
                unset="default"
              />
            </SettingRow>
            <NumberRow
              id="brief-timeout"
              label="Request timeout"
              unit="seconds"
              min={1}
              value={draft.brief.timeout_s}
              onValueChange={(value) => change("brief", "timeout_s", value)}
            />
          </Panel>
          <Panel>
            <PanelHeader title="Judges" />
            <SettingRow label="Model" htmlFor="judge-model">
              <ModelCombobox
                id="judge-model"
                value={draft.judges.model}
                onValueChange={(model) => model && change("judges", "model", model)}
              />
            </SettingRow>
            <SettingRow label="Reasoning effort" htmlFor="judge-effort">
              <EffortSelect
                id="judge-effort"
                model={draft.judges.model}
                value={draft.judges.reasoning_effort}
                onValueChange={(effort) => change("judges", "reasoning_effort", effort)}
                unset="default"
              />
            </SettingRow>
            <details className="group border-t">
              <summary className="flex cursor-pointer list-none items-center gap-1.5 px-5 py-3 text-s-500 select-none hover:bg-hv1 [&::-webkit-details-marker]:hidden">
                <ChevronRight className="size-4 text-muted-foreground transition-transform duration-150 ease-out group-open:rotate-90 motion-reduce:transition-none" />
                Advanced
              </summary>
              <NumberRow
                id="judge-timeout"
                label="Request timeout"
                unit="seconds"
                value={draft.judges.timeout_s}
                onValueChange={(value) => change("judges", "timeout_s", value)}
              />
              <NumberRow
                id="judge-sources-timeout"
                label="Timeout with instructions or documents"
                unit="seconds"
                value={draft.judges.sources_timeout_s}
                onValueChange={(value) => change("judges", "sources_timeout_s", value)}
              />
              <NumberRow
                id="judge-output"
                help="Reasoning tokens count too."
                label="Output tokens per request"
                min={1}
                value={draft.judges.max_output_tokens}
                onValueChange={(value) => change("judges", "max_output_tokens", value)}
              />
              <NumberRow
                id="judge-input"
                help="Larger sources make the judge item an error."
                label="Input characters per request"
                min={1}
                value={draft.judges.max_input_chars}
                onValueChange={(value) => change("judges", "max_input_chars", value)}
              />
            </details>
          </Panel>
          <Panel>
            <PanelHeader title="Evaluation" />
            <NumberRow
              id="evaluations-at-once"
              label="Evaluations at once"
              help="For each evaluator. Keep within the LLM provider's rate limits."
              min={1}
              max={32}
              value={draft.evaluation.evaluations_at_once}
              onValueChange={(value) => change("evaluation", "evaluations_at_once", value)}
            />
            <NumberRow
              id="judge-calls-at-once"
              label="Judge calls at once"
              help="Judge model calls across one evaluator's evaluations. Keep within the LLM provider's rate limits."
              min={1}
              max={64}
              value={draft.evaluation.judge_calls_at_once}
              onValueChange={(value) => change("evaluation", "judge_calls_at_once", value)}
            />
          </Panel>
          <Panel>
            <PanelHeader title="Jev and audit" />
            <NumberRow
              id="jev-bar"
              label="Jev pass bar"
              help="Minimum confidence for a pass."
              step={0.01}
              min={0}
              max={1}
              value={draft.judges.jev_pass_bar}
              onValueChange={(value) => change("judges", "jev_pass_bar", value)}
            />
            <NumberRow
              id="audit-rate"
              help="Judged calls picked for people to review, to measure how often the judges agree with them."
              label="Audit sample"
              unit="% of judged calls"
              min={0}
              max={100}
              value={Math.round(draft.audit.sample_rate * 1000) / 10}
              onValueChange={(value) => change("audit", "sample_rate", value / 100)}
            />
            <NumberRow
              id="audit-budget"
              help="The most of those calls the review queue offers each week."
              label="Weekly audit budget"
              unit="conversations a week"
              value={draft.audit.weekly_budget}
              onValueChange={(value) => change("audit", "weekly_budget", value)}
            />
          </Panel>
        </TabsContent>

        <TabsContent value="phone" className="grid gap-5">
          <PhoneAccountPanel settings={settings} />
          <TriggersPanel settings={settings} />
          <Panel>
            <PanelHeader title="Calls" />
            <NumberRow
              id="ring-timeout"
              help="Then the call ends as no answer."
              label="Ring timeout"
              unit="seconds"
              value={draft.phone.ring_timeout_s}
              onValueChange={(value) => change("phone", "ring_timeout_s", value)}
            />
            <NumberRow
              id="number-rest"
              label="Number rest"
              help="Wait before a number is reused."
              unit="seconds"
              value={draft.phone.number_rest_s}
              onValueChange={(value) => change("phone", "number_rest_s", value)}
            />
            <NumberRow
              id="check-interval"
              label="Check numbers every"
              help="To see changes made in the Plivo console."
              unit="minutes"
              min={1}
              max={1440}
              value={draft.phone.check_interval_s / 60}
              onValueChange={(value) => change("phone", "check_interval_s", Math.round(value * 60))}
            />
            <SettingRow label="Time zone" htmlFor="timezone" help="Sets the caller's “today”.">
              <Input
                id="timezone"
                className="max-w-72"
                list="timezones"
                value={draft.phone.timezone}
                onChange={(event) => change("phone", "timezone", event.target.value)}
              />
              <datalist id="timezones">
                {Intl.supportedValuesOf("timeZone").map((zone) => (
                  <option key={zone} value={zone} />
                ))}
              </datalist>
            </SettingRow>
          </Panel>
        </TabsContent>

        <TabsContent value="limits" className="grid gap-5">
          <Panel>
            <PanelHeader title="Defaults for a run" />
            <NumberRow
              id="max-turns"
              help="Agent turns before the caller says goodbye."
              label="Turns per call"
              min={1}
              max={100}
              value={draft.limits.default_max_turns}
              onValueChange={(value) => change("limits", "default_max_turns", value)}
            />
            <NumberRow
              id="call-length"
              label="Call length"
              unit="seconds"
              min={10}
              max={1800}
              value={draft.limits.default_max_duration_s}
              onValueChange={(value) => change("limits", "default_max_duration_s", value)}
            />
          </Panel>
          <Panel>
            <PanelHeader title="Maximums for a run" />
            <NumberRow
              id="max-conversations"
              label="Conversations"
              help="Scenarios times repeats. Retries do not count."
              min={1}
              value={draft.limits.max_run_conversations}
              onValueChange={(value) => change("limits", "max_run_conversations", value)}
            />
            <NumberRow
              id="max-repeats"
              label="Repeats per scenario"
              min={1}
              value={draft.limits.max_run_repeats}
              onValueChange={(value) => change("limits", "max_run_repeats", value)}
            />
            <NumberRow
              id="max-retries"
              label="Retries per conversation"
              min={0}
              value={draft.limits.max_run_retries}
              onValueChange={(value) => change("limits", "max_run_retries", value)}
            />
            <NumberRow
              id="start-interval"
              help="Longest wait a run can set between call starts."
              label="Start interval"
              unit="seconds"
              min={1}
              value={draft.limits.max_run_start_interval_s}
              onValueChange={(value) => change("limits", "max_run_start_interval_s", value)}
            />
            <NumberRow
              id="max-data-sets"
              help="Each data set of a scenario is its own call in a run."
              label="Data sets per scenario"
              min={1}
              max={MAX_DATA_SETS}
              value={draft.limits.max_scenario_data_sets}
              onValueChange={(value) => change("limits", "max_scenario_data_sets", value)}
            />
          </Panel>
        </TabsContent>
      </Tabs>
      <p className="text-xs-400 text-muted-foreground">
        Database, API token, encryption key, public URL, ports and file storage are set in the
        environment.{" "}
        <a
          href="https://github.com/plivo-labs/yaksh/tree/dev/docs/content/docs/configuration.mdx"
          target="_blank"
          rel="noreferrer"
          className="underline"
        >
          Docs
        </a>
      </p>

      {dirty && (
        <div
          role="region"
          aria-label="Unsaved changes"
          className={`sticky -bottom-5 z-20 -mx-6 -mb-5 mt-auto border-t bg-background ${RISE}`}
        >
          <div className="flex flex-wrap items-center gap-3 px-6 py-3">
            <span className="text-s-500">You have unsaved changes.</span>
            {save.isError && (
              <span className="text-s-400 text-destructive">{save.error.message}</span>
            )}
            <span className="flex-1" />
            <Button variant="ghost" onClick={() => setDraft(settings.values)}>
              Discard
            </Button>
            <Button
              disabled={save.isPending}
              onClick={() =>
                save.mutate(draft, { onSuccess: () => toast.success("Settings saved") })
              }
            >
              {save.isPending && <Spinner />}
              Save changes
            </Button>
          </div>
        </div>
      )}
    </>
  );
}

function NumberRow({
  id,
  label,
  help,
  unit,
  step = 1,
  min,
  max,
  value,
  onValueChange,
}: {
  id: string;
  label: string;
  help?: string;
  unit?: string;
  step?: number;
  min?: number;
  max?: number;
  value: number;
  onValueChange: (value: number) => void;
}) {
  return (
    <SettingRow label={label} htmlFor={id} help={help}>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          step={step}
          min={min}
          max={max}
          className="max-w-36"
          value={Number.isFinite(value) ? value : ""}
          onChange={(event) => onValueChange(event.target.valueAsNumber)}
        />
        {unit && <span className="text-s-400 text-muted-foreground">{unit}</span>}
      </div>
    </SettingRow>
  );
}

/** The warning a changed base URL shows while its provider has a saved key. */
function keyRemovedBy(changed: unknown) {
  return changed ? (
    <span className="text-warning-foreground">
      Saving removes the saved key. A new key saves with this address.
    </span>
  ) : undefined;
}
