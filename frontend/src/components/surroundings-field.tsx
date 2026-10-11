import { Play, Plus, Shuffle, Square, X } from "lucide-react";
import { Fragment, useEffect, useState } from "react";

import { Segmented } from "@/components/segmented";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import {
  LOOP_S,
  type PreviewSettings,
  type SurroundingsPreview,
  useSurroundingsPreview,
  voiceStarts,
} from "@/hooks/use-surroundings-preview";
import { decibels } from "@/lib/format";
import { APPEAR, REVEAL } from "@/lib/motion";
import {
  type Language,
  MAX_DB,
  MIN_DB,
  NOISE_SOUND_ITEMS,
  type NoiseSound,
  SPEAKER_KIND_ITEMS,
  type SpeakerKind,
  type Surroundings,
  type VoiceSettings,
} from "@/lib/types";

type NoiseMode = "off" | "sounds" | "auto";

const NOISE_MODES: { value: NoiseMode; label: string }[] = [
  { value: "off", label: "Off" },
  { value: "sounds", label: "Sounds" },
  { value: "auto", label: "Auto" },
];

const NEW_SOUND_DB = -10;
const NEW_SPEAKER = { kind: "talks_to_caller" as SpeakerKind, db: -6, start_s: 5 };

/** A level relative to the caller's voice. */
function DbSlider({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="grid min-w-0 flex-1 gap-1.5">
      <div className="flex items-baseline justify-between">
        <span id={id} className="text-s-500">
          {label}
        </span>
        <span aria-hidden className="text-s-500 tabular-nums">
          {decibels(value)}
        </span>
      </div>
      <Slider
        aria-labelledby={id}
        min={MIN_DB}
        max={MAX_DB}
        step={1}
        value={value}
        onValueChange={(next) => onChange(next as number)}
      />
    </div>
  );
}

function SoundSelect({
  id,
  value,
  taken,
  onChange,
}: {
  id: string;
  value: NoiseSound;
  taken: NoiseSound[];
  onChange: (value: NoiseSound) => void;
}) {
  const items = NOISE_SOUND_ITEMS.filter(
    (item) => item.value === value || !taken.includes(item.value),
  );
  return (
    <Select
      items={items}
      value={value}
      onValueChange={(next) => next && onChange(next as NoiseSound)}
    >
      <SelectTrigger id={id} aria-label="Sound" className="w-32 shrink-0">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

const LANE_COLORS = {
  caller: "bg-foreground",
  noise: "bg-chart-3",
  speaker: "bg-chart-4",
} as const;

const MAX_START_S = 600;

/** Seconds as typed: the field can be empty while the user types, and keeps the last valid value
 * when it loses focus. */
function SecondsInput({
  id,
  value,
  onChange,
}: {
  id: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));
  return (
    <Input
      id={id}
      type="number"
      min={0}
      max={MAX_START_S}
      step={1}
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        const seconds = Number(event.target.value);
        if (event.target.value !== "" && seconds >= 0 && seconds <= MAX_START_S) onChange(seconds);
      }}
      onBlur={() => setText(String(value))}
    />
  );
}

/** A line that crosses the lanes once per loop. A CSS animation counts its delay from when it
 * starts, so the position where the loop is when the line appears is read once. */
function Playhead({ at }: { at: number }) {
  const [start] = useState(at);
  return (
    <div aria-hidden className="pointer-events-none absolute inset-y-0 right-0 left-18">
      <span
        className="absolute inset-0 motion-reduce:hidden"
        style={{ animation: `playhead ${LOOP_S}s linear -${start}s infinite` }}
      >
        <span className="absolute -inset-y-0.5 left-0 w-px bg-foreground" />
      </span>
    </div>
  );
}

/** The preview's play button and a time line of the loop: when the caller speaks, and when
 * each planned noise and the second speaker sound. */
const PREVIEW = "persona";

function PreviewStrip({
  preview,
  settings,
}: {
  preview: SurroundingsPreview;
  settings: PreviewSettings | null;
}) {
  const shown = preview.shown(PREVIEW);
  const disabled = settings === null;
  const span = (start: number, end: number | null) => ({
    left: `${(start / LOOP_S) * 100}%`,
    width: `${((Math.min(end ?? LOOP_S, LOOP_S) - start) / LOOP_S) * 100}%`,
  });
  const lanes = shown && [
    {
      name: "Caller",
      color: LANE_COLORS.caller,
      spans: voiceStarts(shown.voiceS).map((at) => span(at, at + shown.voiceS)),
    },
    {
      name: "Noise",
      color: LANE_COLORS.noise,
      spans: shown.plan.layers
        .filter((layer) => layer.sound !== null && layer.start_s < LOOP_S)
        .map((layer) => span(layer.start_s, layer.end_s)),
    },
    {
      name: "Speaker",
      color: LANE_COLORS.speaker,
      spans: shown.plan.layers
        .filter((layer) => layer.speaker !== null && layer.start_s < LOOP_S)
        .map((layer) => span(layer.start_s, layer.end_s)),
    },
  ];
  return (
    <div className="grid gap-3 rounded-md bg-muted p-3">
      <div className="flex items-center gap-3">
        <Button
          type="button"
          size="icon"
          disabled={disabled}
          aria-label={preview.isPlaying(PREVIEW) ? "Stop the preview" : "Play the preview"}
          aria-busy={preview.isLoading(PREVIEW)}
          onClick={() => settings && preview.toggle(PREVIEW, settings)}
        >
          {preview.isLoading(PREVIEW) ? (
            <Spinner />
          ) : preview.isPlaying(PREVIEW) ? (
            <Square />
          ) : (
            <Play />
          )}
        </Button>
        <div className="grid min-w-0 flex-1">
          <span className="text-p-500">Preview</span>
          <span className="text-xs-400 text-muted-foreground">
            {disabled
              ? "Choose a voice to hear the caller with these surroundings."
              : `The caller with these surroundings, in a ${LOOP_S} s loop that follows each change.`}
          </span>
        </div>
      </div>
      {lanes && (
        <div
          className={`relative grid grid-cols-[4rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1.5 text-xs-400 text-muted-foreground ${REVEAL}`}
        >
          {lanes.map((lane) => (
            <Fragment key={lane.name}>
              <span>{lane.name}</span>
              <div className="relative h-1.5 bg-border" aria-hidden>
                {lane.spans.map((style) => (
                  <span
                    key={style.left}
                    className={`absolute inset-y-0 ${lane.color} opacity-80`}
                    style={style}
                  />
                ))}
              </div>
            </Fragment>
          ))}
          <Playhead at={preview.position(PREVIEW) ?? 0} />
        </div>
      )}
      {preview.error(PREVIEW) && <FieldError>{preview.error(PREVIEW)}</FieldError>}
    </div>
  );
}

/** What the agent hears behind the caller: noise and a person who talks, each at a level
 * relative to the caller's voice, with a looping preview that follows every change. */
export function SurroundingsField({
  value,
  onChange,
  voice,
  language,
  sampleLine,
}: {
  value: Surroundings;
  onChange: (value: Surroundings) => void;
  voice: VoiceSettings | null;
  language: Language;
  sampleLine: string | null;
}) {
  const preview = useSurroundingsPreview();
  const settings = voice ? { voice, language, surroundings: value, sampleLine } : null;
  const key = JSON.stringify(settings);
  useEffect(() => {
    if (settings) preview.update(PREVIEW, settings);
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- a new plan only on a new setting
  }, [key]);
  const mode: NoiseMode = value.auto ? "auto" : value.sounds.length > 0 ? "sounds" : "off";
  const taken = value.sounds.map((sound) => sound.sound);
  const free = NOISE_SOUND_ITEMS.find((item) => !taken.includes(item.value));

  const setMode = (next: NoiseMode) => {
    if (next === mode) return;
    if (next === "off") onChange({ ...value, sounds: [], auto: null });
    else if (next === "auto") onChange({ ...value, sounds: [], auto: { db: -10, seed: 1 } });
    else onChange({ ...value, auto: null, sounds: [{ sound: "cafe", db: NEW_SOUND_DB }] });
  };

  return (
    <Field>
      <PreviewStrip preview={preview} settings={settings} />
      <Segmented label="Noise" value={mode} options={NOISE_MODES} onChange={setMode} />

      {mode === "sounds" && (
        <div className={`grid gap-3 ${APPEAR}`}>
          {value.sounds.map((sound, index) => (
            <div key={sound.sound} className="flex items-end gap-3">
              <SoundSelect
                id={`sound-${index}`}
                value={sound.sound}
                taken={taken}
                onChange={(next) =>
                  onChange({
                    ...value,
                    sounds: value.sounds.map((s, i) => (i === index ? { ...s, sound: next } : s)),
                  })
                }
              />
              <DbSlider
                id={`sound-${index}-db`}
                label="Volume"
                value={sound.db}
                onChange={(db) =>
                  onChange({
                    ...value,
                    sounds: value.sounds.map((s, i) => (i === index ? { ...s, db } : s)),
                  })
                }
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Remove sound"
                onClick={() =>
                  onChange({ ...value, sounds: value.sounds.filter((_, i) => i !== index) })
                }
              >
                <X />
              </Button>
            </div>
          ))}
          {free && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-fit"
              onClick={() =>
                onChange({
                  ...value,
                  sounds: [...value.sounds, { sound: free.value, db: NEW_SOUND_DB }],
                })
              }
            >
              <Plus />
              Add a sound
            </Button>
          )}
        </div>
      )}

      {value.auto && (
        <div className={`flex items-end gap-3 ${APPEAR}`}>
          <DbSlider
            id="auto-db"
            label="Volume"
            value={value.auto.db}
            onChange={(db) => onChange({ ...value, auto: { ...value.auto!, db } })}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              onChange({ ...value, auto: { ...value.auto!, seed: value.auto!.seed + 1 } })
            }
          >
            <Shuffle />
            New mix
          </Button>
        </div>
      )}
      {value.auto && (
        <FieldDescription>
          One sound plays under the whole call, and others come and go. Each call of a scenario gets
          its own mix, and running the scenario again plays the same one.
        </FieldDescription>
      )}

      <div className="flex items-center justify-between gap-2 pt-2">
        <span id="speaker-label" className="text-s-500">
          Second speaker
        </span>
        <Switch
          aria-labelledby="speaker-label"
          checked={value.speaker !== null}
          onCheckedChange={(on) => onChange({ ...value, speaker: on ? NEW_SPEAKER : null })}
        />
      </div>
      {value.speaker && (
        <div className={`grid gap-3 ${APPEAR}`}>
          <Select
            items={SPEAKER_KIND_ITEMS}
            value={value.speaker.kind}
            onValueChange={(kind) =>
              kind &&
              onChange({ ...value, speaker: { ...value.speaker!, kind: kind as SpeakerKind } })
            }
          >
            <SelectTrigger aria-label="Who talks" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {SPEAKER_KIND_ITEMS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <div className="flex items-end gap-3">
            <DbSlider
              id="speaker-db"
              label="Volume"
              value={value.speaker.db}
              onChange={(db) => onChange({ ...value, speaker: { ...value.speaker!, db } })}
            />
            <div className="grid w-28 shrink-0 gap-1.5">
              <label htmlFor="speaker-start" className="text-s-500">
                Starts at (s)
              </label>
              <SecondsInput
                id="speaker-start"
                value={value.speaker.start_s}
                onChange={(start_s) =>
                  onChange({ ...value, speaker: { ...value.speaker!, start_s } })
                }
              />
            </div>
          </div>
          <FieldDescription>
            Speaks English, or Hindi for a Hindi persona, with short pauses, until the call ends.
            {value.speaker.start_s >= LOOP_S &&
              ` The preview loops ${LOOP_S} s, so it does not reach this start; calls do.`}
          </FieldDescription>
        </div>
      )}
    </Field>
  );
}
