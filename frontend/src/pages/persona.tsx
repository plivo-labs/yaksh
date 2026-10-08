import { Play, Square } from "lucide-react";
import { type ReactNode, type SubmitEvent, useEffect, useRef, useState } from "react";
import { Link, useBlocker, useNavigate, useParams } from "react-router";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { CopyId } from "@/components/copy-id";
import { GenderBadge } from "@/components/gender-badge";
import { SurroundingsField } from "@/components/surroundings-field";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useVoicePreview } from "@/hooks/use-voice-preview";
import { surroundingsLabel } from "@/lib/format";
import { APPEAR } from "@/lib/motion";
import { revealErrors } from "@/lib/forms";
import {
  useDefaults,
  useDeletePersona,
  usePersona,
  usePersonaScenarios,
  useSavePersona,
  useVoices,
} from "@/lib/queries";
import {
  LANGUAGE_ITEMS,
  LANGUAGE_NAMES,
  type Language,
  type Persona,
  type PersonaInput,
  QUIET,
  type Surroundings,
  type Voice,
} from "@/lib/types";

interface Draft {
  name: string;
  prompt: string;
  language: Language;
  voice_id: string;
  speed: number;
  stability: number;
  surroundings: Surroundings;
  sample_line: string;
}

const EMPTY: Draft = {
  name: "",
  prompt: "",
  language: "en",
  voice_id: "",
  speed: 1,
  stability: 0.5,
  surroundings: QUIET,
  sample_line: "",
};

const VOICE = "voice";

function toDraft(persona: Persona): Draft {
  return {
    name: persona.name,
    prompt: persona.prompt,
    language: persona.language,
    voice_id: persona.voice.id,
    speed: persona.voice.speed,
    stability: persona.voice.stability,
    surroundings: persona.surroundings,
    sample_line: persona.sample_line ?? "",
  };
}

function toInput(draft: Draft): PersonaInput {
  return {
    name: draft.name.trim(),
    prompt: draft.prompt.trim(),
    language: draft.language,
    voice: {
      provider: "elevenlabs",
      id: draft.voice_id.trim(),
      speed: draft.speed,
      stability: draft.stability,
    },
    surroundings: draft.surroundings,
    sample_line: draft.sample_line.trim() || null,
  };
}

function voiceLabel(voice: Voice): string {
  const details = [voice.gender, voice.accent].filter(Boolean).join(", ");
  return details ? `${voice.name} (${details})` : voice.name;
}

function SliderField({
  id,
  label,
  min,
  max,
  value,
  onChange,
  children,
}: {
  id: string;
  label: string;
  min: number;
  max: number;
  value: number;
  onChange: (value: number) => void;
  children?: ReactNode;
}) {
  return (
    <Field>
      <div className="flex items-baseline justify-between">
        <FieldLabel id={`${id}-label`}>{label}</FieldLabel>
        <span aria-hidden className="font-mono text-s-400">
          {value.toFixed(2)}
        </span>
      </div>
      <Slider
        aria-labelledby={`${id}-label`}
        min={min}
        max={max}
        step={0.05}
        value={value}
        onValueChange={(next) => onChange(next as number)}
      />
      {children}
    </Field>
  );
}

/** A persona's own page: `/personas/new` adds one, `/personas/<id>` edits one. */
export function PersonaPage() {
  const { id } = useParams();
  const persona = usePersona(id);
  if (!id) return <PersonaEditor key="new" />;
  if (persona.isPending) {
    return (
      <div className="grid gap-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }
  if (persona.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the persona</AlertTitle>
        <AlertDescription>{persona.error.message}</AlertDescription>
      </Alert>
    );
  }
  return <PersonaEditor key={`${id}-${persona.data.updated_at}`} persona={persona.data} />;
}

function PersonaEditor({ persona }: { persona?: Persona }) {
  const id = persona?.id;
  const navigate = useNavigate();
  const save = useSavePersona(id);
  const remove = useDeletePersona();
  const scenarios = usePersonaScenarios(id);
  const preview = useVoicePreview();
  const [initial, setInitial] = useState<Draft>(() => (persona ? toDraft(persona) : EMPTY));
  const [draft, setDraft] = useState<Draft>(initial);
  const [submitted, setSubmitted] = useState(false);
  const leaving = useRef(false);
  const voices = useVoices(draft.language);
  const defaults = useDefaults();

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    save.reset();
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const listed = voices.data ?? [];
  const chosen = listed.find((voice) => voice.provider_voice_id === draft.voice_id);
  const voiceItems = listed.map((voice) => ({
    value: voice.provider_voice_id,
    label: voiceLabel(voice),
  }));
  const hasVoice = draft.voice_id !== "";
  const input = toInput(draft);
  // What would be saved, so a change the server trims away, such as a trailing space, is none.
  const changed = JSON.stringify(input) !== JSON.stringify(toInput(initial));
  const users = scenarios.data ?? [];

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      !leaving.current && changed && currentLocation.pathname !== nextLocation.pathname,
  );
  useEffect(() => {
    if (!changed) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [changed]);

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const valid = hasVoice && Boolean(input.name) && Boolean(input.prompt);
    if (!revealErrors(event.currentTarget, () => setSubmitted(true), valid)) return;
    save.mutate(input, {
      onSuccess: (saved) => {
        setInitial(toDraft(saved));
        setDraft(toDraft(saved));
        leaving.current = true;
        navigate(`/personas/${saved.id}`, { replace: !id });
        leaving.current = false;
      },
    });
  };

  return (
    <form id="persona-form" noValidate onSubmit={submit} className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle>
            <h1 className="truncate text-h3-500">{id ? initial.name : "New persona"}</h1>
          </CardTitle>
          {persona && (
            <CardDescription className="flex flex-wrap items-center gap-x-4 gap-y-1 text-s-400">
              <span>{LANGUAGE_NAMES[persona.language]}</span>
              {persona.voice_gender && <GenderBadge gender={persona.voice_gender} />}
              <span>{surroundingsLabel(persona.surroundings) ?? "Quiet room"}</span>
              <span className="font-mono text-xs-400">Version {persona.current_version}</span>
              {persona.builtin_key && <Badge>Built-in</Badge>}
              <CopyId id={persona.id} label="persona id" />
            </CardDescription>
          )}
          <CardAction className="flex items-center gap-2">
            {id && changed && (
              <Button
                type="button"
                variant="outline"
                className={APPEAR}
                onClick={() => {
                  save.reset();
                  setDraft(initial);
                  setSubmitted(false);
                }}
              >
                Discard
              </Button>
            )}
            <Button type="submit" disabled={save.isPending || (Boolean(id) && !changed)}>
              {save.isPending && <Spinner />}
              {id ? "Save changes" : "Create persona"}
            </Button>
          </CardAction>
        </CardHeader>
        {save.error && (
          <CardContent>
            <FieldError>{save.error.message}</FieldError>
          </CardContent>
        )}
      </Card>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="grid gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Caller</CardTitle>
            </CardHeader>
            <CardContent>
              <FieldGroup>
                <div className="grid gap-4 sm:grid-cols-[1fr_12rem]">
                  <Field>
                    <FieldLabel htmlFor="name">Name</FieldLabel>
                    <Input
                      id="name"
                      required
                      maxLength={80}
                      aria-invalid={submitted && !input.name}
                      value={draft.name}
                      onChange={(e) => set("name", e.target.value)}
                    />
                    {submitted && !input.name && <FieldError>Enter a name.</FieldError>}
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="language">Language</FieldLabel>
                    <Select
                      items={LANGUAGE_ITEMS}
                      value={draft.language}
                      onValueChange={(value) => value && set("language", value as Language)}
                    >
                      <SelectTrigger id="language" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {LANGUAGE_ITEMS.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                              {item.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                </div>
                <Field>
                  <FieldLabel htmlFor="prompt">Behavior</FieldLabel>
                  <Textarea
                    id="prompt"
                    rows={6}
                    required
                    aria-invalid={submitted && !input.prompt}
                    maxLength={4000}
                    placeholder="You are in a hurry. Give short answers and sometimes leave out a detail until the agent asks again."
                    value={draft.prompt}
                    onChange={(e) => set("prompt", e.target.value)}
                  />
                  {submitted && !input.prompt && (
                    <FieldError>Describe how this caller behaves.</FieldError>
                  )}
                  <FieldDescription>
                    Do not put instructions or facts here; the scenario gives them.
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="sample-line">Sample line</FieldLabel>
                  <Input
                    id="sample-line"
                    maxLength={200}
                    placeholder={defaults.data?.sample_lines[draft.language]}
                    value={draft.sample_line}
                    onChange={(e) => set("sample_line", e.target.value)}
                  />
                  <FieldDescription>
                    What the previews say in this persona's voice. Calls do not use it. Empty says
                    the sentence shown here.
                  </FieldDescription>
                </Field>
              </FieldGroup>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Voice</CardTitle>
              <CardAction>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!hasVoice}
                  aria-busy={preview.isLoading(VOICE)}
                  onClick={() =>
                    preview.toggle(VOICE, input.voice, input.language, input.sample_line)
                  }
                >
                  {preview.isLoading(VOICE) ? (
                    <Spinner />
                  ) : preview.isPlaying(VOICE) ? (
                    <Square />
                  ) : (
                    <Play />
                  )}
                  {preview.isPlaying(VOICE) ? "Stop" : "Hear the voice"}
                </Button>
              </CardAction>
            </CardHeader>
            <CardContent>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="voice">Voice</FieldLabel>
                  <Select
                    items={voiceItems}
                    value={chosen ? draft.voice_id : null}
                    onValueChange={(value) => value && set("voice_id", value)}
                    disabled={voices.isPending || voices.isPlaceholderData || voices.isError}
                  >
                    <SelectTrigger
                      id="voice"
                      aria-invalid={submitted && !hasVoice}
                      className="w-full"
                    >
                      <SelectValue
                        placeholder={
                          voices.isPending
                            ? "Loading voices"
                            : voices.isError
                              ? "Voices did not load"
                              : draft.voice_id
                                ? "Voice not in this list"
                                : "Choose a voice"
                        }
                      />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {voiceItems.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  {submitted && !hasVoice && <FieldError>Choose a voice.</FieldError>}
                  {voices.isError && (
                    <FieldError>Could not load voices: {voices.error.message}</FieldError>
                  )}
                  {preview.error(VOICE) && <FieldError>{preview.error(VOICE)}</FieldError>}
                </Field>
                <div className="grid gap-6 sm:grid-cols-2">
                  <SliderField
                    id="speed"
                    label="Speed"
                    min={0.7}
                    max={1.2}
                    value={draft.speed}
                    onChange={(value) => set("speed", value)}
                  />
                  <SliderField
                    id="stability"
                    label="Stability"
                    min={0}
                    max={1}
                    value={draft.stability}
                    onChange={(value) => set("stability", value)}
                  >
                    <FieldDescription>
                      Lower values make each call sound more different; 0.5 is the default.
                    </FieldDescription>
                  </SliderField>
                </div>
              </FieldGroup>
            </CardContent>
          </Card>

          {id && (
            <Card className="gap-0 pb-0">
              <CardHeader className="pb-3">
                <CardTitle>Used by</CardTitle>
                <CardAction className="text-s-400 text-muted-foreground">
                  {scenarios.isSuccess &&
                    `${users.length} ${users.length === 1 ? "scenario" : "scenarios"}`}
                </CardAction>
              </CardHeader>
              {scenarios.isPending ? (
                <CardContent className="pb-5">
                  <Skeleton className="h-10" />
                </CardContent>
              ) : scenarios.isError ? (
                <CardContent className="pb-5">
                  <FieldError>Could not load the scenarios: {scenarios.error.message}</FieldError>
                </CardContent>
              ) : users.length === 0 ? (
                <CardContent className="pb-5 text-muted-foreground">
                  No scenario uses it.
                </CardContent>
              ) : (
                <ul>
                  {users.map((scenario) => (
                    <li key={scenario.id} className="border-t">
                      <Link
                        to={`/agents/${scenario.agent_id}?tab=scenarios&scenario=${scenario.id}`}
                        className="flex justify-between gap-3 px-5 py-2.5 outline-none transition-colors hover:bg-hv1 focus-visible:ring-2 focus-visible:ring-ring/50"
                      >
                        <span className="truncate">{scenario.name}</span>
                        <span className="shrink-0 text-muted-foreground">
                          {scenario.agent_name}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}

          {id && (
            <Card size="sm">
              <CardHeader>
                <CardTitle>Delete this persona</CardTitle>
                <CardDescription>
                  {users.length > 0
                    ? "Give its scenarios another persona first."
                    : "Past and queued conversations are not changed."}
                </CardDescription>
                <CardAction>
                  {users.length === 0 && scenarios.isSuccess && (
                    <DeleteConfirm
                      name={initial.name}
                      description="Past and queued conversations are not changed."
                      pending={remove.isPending}
                      onDelete={(close) =>
                        remove.mutate(id, {
                          onSuccess: () => {
                            leaving.current = true;
                            navigate("/personas");
                          },
                          onSettled: close,
                        })
                      }
                    />
                  )}
                </CardAction>
              </CardHeader>
              {remove.error && (
                <CardContent>
                  <FieldError>{remove.error.message}</FieldError>
                </CardContent>
              )}
            </Card>
          )}
        </div>

        <Card className="xl:sticky xl:top-6">
          <CardHeader>
            <CardTitle>Surroundings</CardTitle>
            <CardDescription>
              What the agent hears behind the caller. 0 dB is as loud as the caller.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <SurroundingsField
              value={draft.surroundings}
              onChange={(surroundings) => set("surroundings", surroundings)}
              voice={hasVoice ? input.voice : null}
              language={input.language}
              sampleLine={input.sample_line}
            />
          </CardContent>
        </Card>
      </div>

      <DiscardConfirm
        subject="persona"
        open={blocker.state === "blocked"}
        onOpenChange={(open) => !open && blocker.state === "blocked" && blocker.reset()}
        onDiscard={() => blocker.state === "blocked" && blocker.proceed()}
      />
    </form>
  );
}
