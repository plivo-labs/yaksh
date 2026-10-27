import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAgents } from "@/lib/queries";
import { STT_LANGUAGES, STT_PROVIDERS, sttProvider } from "@/lib/speech-providers";
import {
  type AppSettings,
  LANGUAGE_NAMES,
  type Language,
  type SettingsValues,
  servedLanguages,
} from "@/lib/types";
import type { Change } from "@/pages/settings";
import { KeyRow, ProviderPanel, SettingRow, KeyRemovedNote } from "@/pages/settings-keys";

type Fields = { model: string; base_url?: string; url?: string };

/** The one provider that hears the agent on every call, with its own address, model and key. */
export function SpeechToTextPanel({
  settings,
  draft,
  change,
}: {
  settings: AppSettings;
  draft: SettingsValues;
  change: Change;
}) {
  const provider = sttProvider(draft.speech.stt);
  const fields = draft[provider.section] as Fields;
  const saved = settings.values[provider.section] as Fields;
  const address = provider.address === null ? undefined : fields[provider.address];
  const moved = provider.address !== null && address !== saved[provider.address];
  const key = settings.secrets[provider.secret];
  const edit = (field: keyof Fields, value: string) =>
    change(provider.section, field as never, value as never);
  const unheard = useUnheard(draft.speech.stt);
  return (
    <ProviderPanel
      title="Speech to text"
      description="Hears the agent. One provider for all calls."
      provider={provider.test}
      canTest={Boolean(key)}
      edits={JSON.stringify([draft.speech, fields])}
    >
      <SettingRow
        label="Provider"
        htmlFor="stt-provider"
        help={
          (!key || unheard) && (
            <span className="grid gap-1 text-warning-foreground">
              {!key && (
                <span>{provider.label} has no key. Phone tests can't start until you add one.</span>
              )}
              {unheard && <span>{unheard}</span>}
            </span>
          )
        }
      >
        <Select
          items={STT_PROVIDERS.map((item) => ({ value: item.value, label: item.label }))}
          value={draft.speech.stt}
          onValueChange={(next) => next && change("speech", "stt", next)}
        >
          <SelectTrigger id="stt-provider" className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STT_PROVIDERS.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingRow>
      {provider.address !== null && (
        <SettingRow
          label="Base URL"
          htmlFor="stt-url"
          help={moved && key ? <KeyRemovedNote /> : undefined}
        >
          <Input
            id="stt-url"
            value={address}
            onChange={(event) => edit(provider.address ?? "url", event.target.value.trim())}
          />
        </SettingRow>
      )}
      <SettingRow label="Model" htmlFor="stt-model">
        <Input
          id="stt-model"
          className="max-w-56"
          value={fields.model}
          onChange={(event) => edit("model", event.target.value)}
        />
      </SettingRow>
      <KeyRow name={provider.secret} label="API key" state={key} url={address} checked />
    </ProviderPanel>
  );
}

/** A warning when a saved agent serves a language the provider doesn't hear; phone runs that
 * need it are refused. */
function useUnheard(stt: SettingsValues["speech"]["stt"]): string | null {
  const agents = useAgents();
  const heard = new Set(STT_LANGUAGES[stt]);
  const missing = new Map<Language, number>();
  for (const agent of agents.data ?? []) {
    for (const language of servedLanguages(agent.languages)) {
      if (!heard.has(language)) missing.set(language, (missing.get(language) ?? 0) + 1);
    }
  }
  if (missing.size === 0) return null;
  const label = sttProvider(stt).label;
  return [...missing]
    .map(
      ([language, count]) =>
        `${label} doesn't hear ${LANGUAGE_NAMES[language]}. ${count} ${count === 1 ? "agent serves" : "agents serve"} it.`,
    )
    .join(" ");
}
