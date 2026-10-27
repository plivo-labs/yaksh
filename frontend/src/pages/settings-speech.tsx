import { useState } from "react";

import { Panel, PanelHeader } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/confirm-dialogs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useAgents,
  usePersonas,
  useRemoveNimbleAccount,
  useSaveNimbleAccount,
  useVoices,
} from "@/lib/queries";
import {
  STT_LANGUAGES,
  STT_PROVIDERS,
  TTS_PROVIDERS,
  type TtsProvider,
  hasCredential,
  sttProvider,
  ttsProvider,
} from "@/lib/speech-providers";
import {
  type AppSettings,
  LANGUAGE_NAMES,
  type Language,
  type SettingsValues,
  type VoiceProvider,
  servedLanguages,
} from "@/lib/types";
import type { Change } from "@/pages/settings";
import { KeyRow, ProviderPanel, SettingRow, KeyRemovedNote } from "@/pages/settings-keys";

type Fields = { model: string; base_url?: string; url?: string };
type TtsFields = { model?: string } & Partial<Record<TtsProvider["address"], string>>;

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

/** The providers that voice personas: a list with each one's state, and one provider's
 * settings at a time. */
export function TextToSpeechPanel({
  settings,
  draft,
  change,
}: {
  settings: AppSettings;
  draft: SettingsValues;
  change: Change;
}) {
  const [open, setOpen] = useState<VoiceProvider | null>(null);
  const voices = useVoices();
  const personas = usePersonas();
  const voicesOf = (provider: VoiceProvider) =>
    (voices.data ?? []).filter((voice) => voice.provider === provider).length;
  if (open !== null) {
    const provider = ttsProvider(open);
    const users = (personas.data ?? []).filter((persona) => persona.voice.provider === open);
    return (
      <TtsProviderPanel
        provider={provider}
        settings={settings}
        draft={draft}
        change={change}
        voices={voicesOf(open)}
        personas={users.length}
        onBack={() => setOpen(null)}
      />
    );
  }
  return (
    <Panel>
      <PanelHeader title="Text to speech" />
      <p className="px-5 py-3 text-s-400 text-muted-foreground">
        The caller's voice. Each voice uses one provider. Built-in personas use ElevenLabs.
      </p>
      <ul className="border-t">
        {TTS_PROVIDERS.map((provider) => {
          const fields = draft[provider.section] as Fields;
          const saved = hasCredential(provider, settings.secrets);
          return (
            <li
              key={provider.value}
              className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-5 py-3 last:border-b-0"
            >
              <span className="w-28 text-s-500">{provider.label}</span>
              <span className="w-40 truncate font-mono text-xs-400 text-muted-foreground">
                {"model" in fields ? fields.model : ""}
              </span>
              <span className="flex flex-1 flex-wrap gap-1.5">
                <Badge variant={saved ? "success" : undefined}>{saved ? "Saved" : "Not set"}</Badge>
                {!provider.wordTimestamps && <Badge variant="warning">Sentence timing</Badge>}
              </span>
              <span className="w-20 text-right text-s-400 text-muted-foreground">
                {voicesOf(provider.value)} {voicesOf(provider.value) === 1 ? "voice" : "voices"}
              </span>
              <Button size="sm" variant="outline" onClick={() => setOpen(provider.value)}>
                {saved ? "Edit" : "Set up"}
              </Button>
            </li>
          );
        })}
      </ul>
      <p className="border-t px-5 py-3 text-xs-400 text-muted-foreground">
        Sentence timing: a cut-off reply shows whole sentences, not words.
      </p>
    </Panel>
  );
}

function TtsProviderPanel({
  provider,
  settings,
  draft,
  change,
  voices,
  personas,
  onBack,
}: {
  provider: TtsProvider;
  settings: AppSettings;
  draft: SettingsValues;
  change: Change;
  voices: number;
  personas: number;
  onBack: () => void;
}) {
  const fields = draft[provider.section] as TtsFields;
  const saved = settings.values[provider.section] as TtsFields;
  const address = fields[provider.address] ?? "";
  const moved = address !== saved[provider.address];
  const key = hasCredential(provider, settings.secrets);
  const region = provider.address === "region";
  const removeWarning =
    voices + personas > 0
      ? {
          title: `Remove the ${provider.label} key?`,
          description: `${voices} ${voices === 1 ? "voice" : "voices"} and ${personas} ${personas === 1 ? "persona" : "personas"} use ${provider.label}. Their phone tests can't start until you add a key again.`,
        }
      : undefined;
  const edit = (field: string, value: string) =>
    change(provider.section, field as never, value as never);
  return (
    <div className="grid gap-3">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-s-400">
        <Button size="sm" variant="ghost" onClick={onBack}>
          Text to speech
        </Button>
        <span aria-hidden className="text-muted-foreground">
          /
        </span>
        <span className="text-s-500">{provider.label}</span>
      </nav>
      <ProviderPanel
        title={provider.label}
        provider={provider.test}
        canTest={key}
        edits={JSON.stringify(fields)}
        description={
          provider.wordTimestamps
            ? undefined
            : "Sentence timing: a cut-off reply shows whole sentences, not words."
        }
      >
        <SettingRow
          label={region ? "Region" : "Base URL"}
          htmlFor="tts-address"
          help={moved && key ? <KeyRemovedNote address={region ? "region" : "URL"} /> : undefined}
        >
          <Input
            id="tts-address"
            className={region ? "max-w-56 font-mono" : undefined}
            value={address}
            onChange={(event) => edit(provider.address, event.target.value.trim())}
          />
        </SettingRow>
        {"model" in fields && (
          <SettingRow label="Model" htmlFor="tts-model">
            <Input
              id="tts-model"
              className="max-w-56"
              value={fields.model}
              onChange={(event) => edit("model", event.target.value)}
            />
          </SettingRow>
        )}
        {provider.secrets.length === 1 ? (
          <KeyRow
            name={provider.secrets[0]}
            label="API key"
            help={provider.value === "sarvam" ? "Also Sarvam's speech to text key." : undefined}
            state={settings.secrets[provider.secrets[0]]}
            url={address}
            checked
            removable
            removeWarning={removeWarning}
          />
        ) : (
          <NimbleAccountRow settings={settings} baseUrl={address} removeWarning={removeWarning} />
        )}
      </ProviderPanel>
    </div>
  );
}

/** Nimble's Auth ID and Auth token: they change together, are checked at the base URL the form
 * shows, and are saved with it. */
function NimbleAccountRow({
  settings,
  baseUrl,
  removeWarning,
}: {
  settings: AppSettings;
  baseUrl: string;
  removeWarning?: { title: string; description: string };
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [authId, setAuthId] = useState("");
  const [token, setToken] = useState("");
  const save = useSaveNimbleAccount();
  const remove = useRemoveNimbleAccount();
  const id = settings.secrets.nimble_auth_id;
  const saved = id && settings.secrets.nimble_auth_token;
  const close = () => {
    setEditing(false);
    setAuthId("");
    setToken("");
    save.reset();
  };
  return (
    <SettingRow label="Auth ID and token" htmlFor={editing ? "nimble-auth-id" : undefined}>
      {editing ? (
        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(
              { auth_id: authId.trim(), auth_token: token.trim(), base_url: baseUrl },
              { onSuccess: close },
            );
          }}
        >
          <Input
            id="nimble-auth-id"
            autoComplete="off"
            placeholder="Auth ID"
            value={authId}
            onChange={(event) => setAuthId(event.target.value)}
          />
          <Input
            type="password"
            autoComplete="off"
            aria-label="Auth token"
            placeholder="Auth token"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          {save.isError && <p className="text-xs-400 text-destructive">{save.error.message}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="submit"
              size="sm"
              disabled={!authId.trim() || !token.trim() || save.isPending}
            >
              {save.isPending && <Spinner />}
              Check and save
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={close}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {saved ? (
            <>
              <span className="font-mono text-s-400">
                ••••{id.hint ?? ""} / ••••{saved.hint ?? ""}
              </span>
              <Badge variant="success">Saved</Badge>
            </>
          ) : (
            <Badge>Not set</Badge>
          )}
          <span className="flex-1" />
          {saved && (
            <Button
              size="sm"
              variant="ghost"
              disabled={remove.isPending}
              onClick={() => (removeWarning ? setConfirming(true) : remove.mutate())}
            >
              Remove
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            {saved ? "Replace" : "Add"}
          </Button>
          {removeWarning && (
            <ConfirmDialog
              title={removeWarning.title}
              description={removeWarning.description}
              action="Remove"
              destructive
              pending={remove.isPending}
              error={remove.error?.message}
              open={confirming}
              onOpenChange={setConfirming}
              onConfirm={(done) => remove.mutate(undefined, { onSuccess: done })}
            />
          )}
        </div>
      )}
    </SettingRow>
  );
}
