import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";

import { ModelCombobox } from "@/components/model-combobox";
import { Panel, PanelHeader } from "@/components/panel";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useModelEfforts, useSaveSettingsValues, useSettings } from "@/lib/queries";
import type { AppSettings, SettingsValues } from "@/lib/types";
import { KeyRow, PlivoAccountRow, ProviderPanel, SettingRow } from "@/pages/settings-keys";
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

/** The settings of this Yaksha. Keys save one by one, after their provider accepts them; the
 * other values save together from the bar at the bottom. A change applies to the next call. */
export function SettingsPage() {
  const settings = useSettings();
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.find((item) => item.value === params.get("tab"))?.value ?? "providers";
  return (
    <div className="grid max-w-5xl gap-6">
      <div className="flex min-h-[30px] flex-wrap items-center gap-x-2 gap-y-4">
        <h1 className="mr-auto text-h3-500">Settings</h1>
        <ImportExport />
      </div>
      <p className="-mt-3 max-w-3xl text-p-400 text-muted-foreground">
        Keys and models for the caller, the judges and the phone. A change applies to the next call.
        A call in progress keeps the settings it started with.
      </p>
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
          tab={tab}
          onTab={(next) => setParams({ tab: next }, { replace: true })}
        />
      )}
    </div>
  );
}

function Form({
  settings,
  tab,
  onTab,
}: {
  settings: AppSettings;
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
  }
  const save = useSaveSettingsValues();
  const dirty = JSON.stringify(draft) !== saved;
  const change: Change = (section, key, value) =>
    setDraft((current) => ({ ...current, [section]: { ...current[section], [key]: value } }));
  const secrets = settings.secrets;

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  return (
    <>
      <Alert>
        <AlertDescription>
          These settings stay in the environment: the database address, the encryption key, the API
          token, the ports and file storage. Yaksha reads them before it can open the database.
        </AlertDescription>
      </Alert>
      <Tabs value={tab} onValueChange={(next) => onTab(next as Tab)} className="gap-5">
        <TabsList variant="line">
          {TABS.map((item) => (
            <TabsTrigger key={item.value} value={item.value}>
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="providers" className="grid gap-5">
          <ProviderPanel
            title="LLM provider"
            provider="llm"
            canTest={Boolean(secrets.llm_api_key)}
            description="Any OpenAI-compatible API with the Responses endpoint: OpenAI, Azure OpenAI or a gateway. The caller, scenario writing and the judges use it."
          >
            <SettingRow
              label="Base URL"
              htmlFor="llm-url"
              help="For Azure OpenAI: https://<resource>.openai.azure.com/openai/v1/. A new base URL removes the saved key; add the key again after you save."
            >
              <Input
                id="llm-url"
                value={draft.llm.base_url}
                onChange={(event) => change("llm", "base_url", event.target.value)}
              />
            </SettingRow>
            <KeyRow
              name="llm_api_key"
              label="API key"
              help="Yaksha never shows a saved key again."
              state={secrets.llm_api_key}
              checkedWith="the base URL"
            />
          </ProviderPanel>
          <ProviderPanel
            title="Deepgram"
            provider="deepgram"
            canTest={Boolean(secrets.deepgram_api_key)}
            description="Speech to text. Hears the agent."
          >
            <SettingRow
              label="Base URL"
              htmlFor="deepgram-url"
              help="Change it for a self-hosted Deepgram. A new base URL removes the saved key; add the key again after you save."
            >
              <Input
                id="deepgram-url"
                value={draft.deepgram.base_url}
                onChange={(event) => change("deepgram", "base_url", event.target.value)}
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
              checkedWith="Deepgram"
            />
          </ProviderPanel>
          <ProviderPanel
            title="ElevenLabs"
            provider="elevenlabs"
            canTest={Boolean(secrets.elevenlabs_api_key)}
            description="Text to speech. Speaks as the caller and plays voice previews."
          >
            <KeyRow
              name="elevenlabs_api_key"
              label="API key"
              help="The API also uses it to look up voices."
              state={secrets.elevenlabs_api_key}
              checkedWith="ElevenLabs"
            />
          </ProviderPanel>
          <ProviderPanel
            title="TypeSafe"
            provider="typesafe"
            canTest={Boolean(secrets.typesafe_api_key)}
            description="Optional. Jev, TypeSafe's classifier, checks criteria and agent rules before the judges. Yaksha sends call transcripts to TypeSafe."
          >
            <KeyRow
              name="typesafe_api_key"
              label="API key"
              state={secrets.typesafe_api_key}
              removable
              checkedWith="TypeSafe"
            />
          </ProviderPanel>
        </TabsContent>

        <TabsContent value="models" className="grid gap-5">
          <Panel>
            <PanelHeader title="Caller" />
            <SettingRow
              label="Model"
              htmlFor="caller-model"
              help="The list comes from the LLM provider. For Azure, type the deployment name. Do not use gpt-4.1."
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
                unset="none, the fastest"
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
                unset="the model's default"
              />
            </SettingRow>
            <NumberRow
              id="generation-timeout"
              label="Request timeout"
              help="Yaksha sends a failed request one more time."
              unit="seconds"
              value={draft.generation.timeout_s}
              onValueChange={(value) => change("generation", "timeout_s", value)}
            />
          </Panel>
          <Panel>
            <PanelHeader title="Judges" />
            <p className="px-5 py-3 text-s-400 text-muted-foreground">
              The model that judges each call after it ends.
            </p>
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
                unset="the model's default"
              />
            </SettingRow>
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
              help="For judges that read the agent's whole instructions or documents."
              unit="seconds"
              value={draft.judges.sources_timeout_s}
              onValueChange={(value) => change("judges", "sources_timeout_s", value)}
            />
            <NumberRow
              id="judge-output"
              label="Output tokens"
              help="The maximum for one request. Reasoning tokens count too."
              value={draft.judges.max_output_tokens}
              onValueChange={(value) => change("judges", "max_output_tokens", value)}
            />
            <NumberRow
              id="judge-input"
              label="Input characters"
              help="The maximum for one request. A larger source makes that judge's item an error."
              value={draft.judges.max_input_chars}
              onValueChange={(value) => change("judges", "max_input_chars", value)}
            />
          </Panel>
          <Panel>
            <PanelHeader title="Jev and audit" />
            <NumberRow
              id="jev-bar"
              label="Jev pass bar"
              help="From 0 to 1. Jev publishes a pass only at or above this value."
              step={0.01}
              value={draft.judges.jev_pass_bar}
              onValueChange={(value) => change("judges", "jev_pass_bar", value)}
            />
            <NumberRow
              id="audit-rate"
              label="Audit sample"
              help="The share of judged calls in the audit lane, from 0 to 1."
              step={0.01}
              value={draft.audit.sample_rate}
              onValueChange={(value) => change("audit", "sample_rate", value)}
            />
            <NumberRow
              id="audit-budget"
              label="Weekly audit budget"
              unit="conversations a week"
              value={draft.audit.weekly_budget}
              onValueChange={(value) => change("audit", "weekly_budget", value)}
            />
          </Panel>
        </TabsContent>

        <TabsContent value="phone" className="grid gap-5">
          <ProviderPanel
            title="Plivo account"
            provider="plivo"
            canTest={Boolean(secrets.plivo_auth_id && secrets.plivo_auth_token)}
            description="The account that owns the numbers and places the calls."
          >
            <PlivoAccountRow settings={settings} />
          </ProviderPanel>
          <TriggersPanel settings={settings} />
          <Panel>
            <PanelHeader title="Calls" />
            <NumberRow
              id="ring-timeout"
              label="Ring timeout"
              help="After this time, the call ends as no answer."
              unit="seconds"
              value={draft.phone.ring_timeout_s}
              onValueChange={(value) => change("phone", "ring_timeout_s", value)}
            />
            <NumberRow
              id="number-rest"
              label="Number rest"
              help="A released number waits this long, so a late call does not reach the next test."
              unit="seconds"
              value={draft.phone.number_rest_s}
              onValueChange={(value) => change("phone", "number_rest_s", value)}
            />
            <SettingRow
              label="Time zone"
              htmlFor="timezone"
              help="Sets the date the caller is told is today. A run takes it when it starts."
            >
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
            <PanelHeader title="Run limits" />
            <p className="px-5 py-3 text-s-400 text-muted-foreground">
              These limits control the cost of one run.
            </p>
            <NumberRow
              id="max-turns"
              label="Turns per call"
              help="The caller says goodbye after this many agent turns, when the run does not set a value. From 1 to 100."
              value={draft.limits.default_max_turns}
              onValueChange={(value) => change("limits", "default_max_turns", value)}
            />
            <NumberRow
              id="call-length"
              label="Call length"
              help="The longest a call lasts, when the run does not set a value. From 10 to 1800."
              unit="seconds"
              value={draft.limits.default_max_duration_s}
              onValueChange={(value) => change("limits", "default_max_duration_s", value)}
            />
            <NumberRow
              id="max-conversations"
              label="Conversations per run"
              help="Scenarios times repeats. Retries do not count."
              value={draft.limits.max_run_conversations}
              onValueChange={(value) => change("limits", "max_run_conversations", value)}
            />
            <NumberRow
              id="max-repeats"
              label="Repeats per scenario"
              value={draft.limits.max_run_repeats}
              onValueChange={(value) => change("limits", "max_run_repeats", value)}
            />
            <NumberRow
              id="max-retries"
              label="Retries per conversation"
              value={draft.limits.max_run_retries}
              onValueChange={(value) => change("limits", "max_run_retries", value)}
            />
            <NumberRow
              id="start-interval"
              label="Start interval"
              help="The longest wait a run can set between two call starts."
              unit="seconds"
              value={draft.limits.max_run_start_interval_s}
              onValueChange={(value) => change("limits", "max_run_start_interval_s", value)}
            />
          </Panel>
        </TabsContent>
      </Tabs>

      {dirty && (
        <div
          role="region"
          aria-label="Unsaved changes"
          className="sticky bottom-0 z-20 -mx-6 -mb-5 border-t bg-background"
        >
          <div className="flex flex-wrap items-center gap-3 px-6 py-3">
            <span className="text-s-500">You have unsaved changes.</span>
            <span className="text-s-400 text-muted-foreground">
              Saved changes apply to the next call.
            </span>
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
  value,
  onValueChange,
}: {
  id: string;
  label: string;
  help?: string;
  unit?: string;
  step?: number;
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
          className="max-w-36"
          value={Number.isFinite(value) ? value : ""}
          onChange={(event) => onValueChange(event.target.valueAsNumber)}
        />
        {unit && <span className="text-s-400 text-muted-foreground">{unit}</span>}
      </div>
    </SettingRow>
  );
}

const UNSET = "unset";

/** The reasoning efforts the model takes, as Yaksha checked them with the provider. `unset`
 * names what no effort means for this field. */
function EffortSelect({
  id,
  model,
  value,
  onValueChange,
  unset,
  hidden = [],
}: {
  id: string;
  model: string;
  value: string | null;
  onValueChange: (effort: string | null) => void;
  unset: string;
  hidden?: string[];
}) {
  const efforts = useModelEfforts(model);
  if (efforts.isPending) {
    return (
      <span className="flex items-center gap-2 text-s-400 text-muted-foreground">
        <Spinner /> Checking which efforts {model} takes
      </span>
    );
  }
  if (efforts.isError) {
    return (
      <span className="text-s-400">
        {value ?? unset}
        <span className="block text-xs-400 text-muted-foreground">
          Yaksha cannot check this model now: {efforts.error.message}
        </span>
      </span>
    );
  }
  const taken = efforts.data.efforts;
  if (taken.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Badge>This model has no reasoning</Badge>
        {value !== null && (
          <Button size="sm" variant="outline" onClick={() => onValueChange(null)}>
            Send no effort
          </Button>
        )}
      </div>
    );
  }
  const items = [
    { value: UNSET, label: unset },
    ...taken
      .filter((effort) => !hidden.includes(effort))
      .map((effort) => ({ value: effort, label: effort })),
  ];
  const refused = value !== null && !taken.includes(value);
  return (
    <>
      <Select
        items={items}
        value={value ?? UNSET}
        onValueChange={(next) => next && onValueChange(next === UNSET ? null : next)}
      >
        <SelectTrigger id={id} className="w-56" aria-invalid={refused}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {refused && (
        <span className="text-xs-400 text-destructive">
          {model} does not take {value}; choose another effort.
        </span>
      )}
    </>
  );
}
