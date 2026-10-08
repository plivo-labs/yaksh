import { useEffect, useRef, useState } from "react";

import { apiBlob } from "@/lib/api";
import { usePreviewPlan, usePreviewVoice } from "@/lib/queries";
import type { Language, SoundPlan, Surroundings, VoiceSettings } from "@/lib/types";

/** The preview loop, in seconds. */
export const LOOP_S = 30;
/** The caller first speaks one second in, as a call has sound before the caller speaks, then
 * says its sample sentence again after each pause, as a caller talks in turns. */
const VOICE_AT_S = 1;
const VOICE_PAUSE_S = 2.5;
/** How many loops are scheduled ahead; a preview stops by itself after them. */
const LOOPS = 20;
const REPLAN_MS = 250;

/** When the caller's sample sentence starts in the loop, each time it fits whole. */
export function voiceStarts(voiceS: number): number[] {
  const starts = [];
  for (let at = VOICE_AT_S; at + voiceS <= LOOP_S; at += voiceS + VOICE_PAUSE_S) starts.push(at);
  return starts;
}

export interface PreviewSettings {
  voice: VoiceSettings;
  language: Language;
  surroundings: Surroundings;
  /** What the caller says; null says the language's sample sentence. */
  sampleLine: string | null;
}

/** Plays a caller's voice with its surroundings in a loop, as a call mixes them: the server
 * plans the sounds, and the browser adds them together. One preview plays at a time; `key`
 * names who asked (a persona card, the persona page). New settings for the playing key ask
 * for a new plan and go on from the same point of the loop. */
export function useSurroundingsPreview() {
  const speak = usePreviewVoice();
  const plan = usePreviewPlan();
  const context = useRef<AudioContext | null>(null);
  const buffers = useRef(new Map<string, Promise<AudioBuffer>>());
  const playing = useRef<{ key: string; started: number; sources: AudioBufferSourceNode[] }>(null);
  const request = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  /** Stops the preview when the audio scheduled ahead runs out. */
  const ending = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [state, setState] = useState<{ key: string; status: "loading" | "playing" } | null>(null);
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(null);
  /** What the loop plays: the plan and the length of the voice sample, for a time line. */
  const [shown, setShown] = useState<{ plan: SoundPlan; voiceS: number } | null>(null);

  const buffer = (key: string, fetch: () => Promise<Blob>) => {
    const ctx = context.current!;
    let found = buffers.current.get(key);
    if (!found) {
      found = fetch().then(async (blob) => ctx.decodeAudioData(await blob.arrayBuffer()));
      found.catch(() => buffers.current.delete(key));
      buffers.current.set(key, found);
    }
    return found;
  };

  const stopSources = () => {
    for (const source of playing.current?.sources ?? []) source.stop();
  };

  /** Plans and schedules the loop for `key` from `started`, unless a later request came first:
   * `token` is this request's number. */
  const schedule = async (
    key: string,
    settings: PreviewSettings,
    started: number,
    token: number,
  ) => {
    const { voice, language, surroundings, sampleLine } = settings;
    const current = await plan.mutateAsync({ surroundings, language, duration_s: LOOP_S });
    const [spoken, ...sounds] = await Promise.all([
      buffer(JSON.stringify(["voice", voice, language, sampleLine]), () =>
        speak.mutateAsync({ voice, language, sample_line: sampleLine }),
      ),
      ...current.layers.map((layer) => buffer(layer.file, () => apiBlob(`/sounds/${layer.file}`))),
    ]);
    if (token !== request.current) return;
    const ctx = context.current!;
    const now = ctx.currentTime;
    const sources: AudioBufferSourceNode[] = [];
    const play = (audio: AudioBuffer, at: number, until: number, gain: number, loop: boolean) => {
      if (until <= now) return;
      const node = ctx.createBufferSource();
      node.buffer = audio;
      node.loop = loop;
      const level = ctx.createGain();
      level.gain.value = gain;
      node.connect(level).connect(ctx.destination);
      const from = Math.max(at, now);
      node.start(from, loop ? (from - at) % audio.duration : from - at);
      node.stop(until);
      sources.push(node);
    };
    for (let n = 0; n < LOOPS; n++) {
      const loopStart = started + n * LOOP_S;
      const loopEnd = loopStart + LOOP_S;
      for (const at of voiceStarts(spoken.duration)) {
        play(spoken, loopStart + at, loopStart + at + spoken.duration, 1, false);
      }
      current.layers.forEach((layer, index) => {
        const at = loopStart + layer.start_s;
        const end = layer.end_s === null ? loopEnd : Math.min(loopEnd, loopStart + layer.end_s);
        const once = layer.loop ? end : Math.min(end, at + sounds[index].duration);
        if (at < loopEnd) play(sounds[index], at, once, layer.gain, layer.loop);
      });
    }
    stopSources();
    playing.current = { key, started, sources };
    clearTimeout(ending.current);
    ending.current = setTimeout(
      () => token === request.current && stop(),
      (started + LOOPS * LOOP_S - now) * 1000,
    );
    setShown({ plan: current, voiceS: spoken.duration });
    setState({ key, status: "playing" });
  };

  const stop = () => {
    request.current++;
    clearTimeout(timer.current);
    clearTimeout(ending.current);
    stopSources();
    playing.current = null;
    setState(null);
  };

  /** Runs a request, and shows its failure only when no later request replaced it. */
  const run = (key: string, settings: PreviewSettings, started: number) => {
    const token = ++request.current;
    schedule(key, settings, started, token).catch((failure: unknown) => {
      if (token === request.current) fail(key, failure);
    });
  };

  const fail = (key: string, failure: unknown) => {
    stop();
    setFailed({ key, message: failure instanceof Error ? failure.message : String(failure) });
  };

  const play = async (key: string, settings: PreviewSettings) => {
    stop();
    context.current ??= new AudioContext({ sampleRate: 8000 });
    await context.current.resume();
    setFailed(null);
    setState({ key, status: "loading" });
    const started = context.current.currentTime + 0.1;
    playing.current = { key, started, sources: [] };
    run(key, settings, started);
  };

  /** New settings for `key`: when it plays, the loop follows them from where it is. */
  const update = (key: string, settings: PreviewSettings) => {
    const current = playing.current;
    if (current?.key !== key) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => run(key, settings, current.started), REPLAN_MS);
  };

  useEffect(
    () => () => {
      clearTimeout(timer.current);
      clearTimeout(ending.current);
      stopSources();
      void context.current?.close();
    },
    [],
  );

  return {
    update,
    toggle: (key: string, settings: PreviewSettings) =>
      state?.key === key ? stop() : void play(key, settings),
    isLoading: (key: string) => state?.key === key && state.status === "loading",
    isPlaying: (key: string) => state?.key === key && state.status === "playing",
    error: (key: string) => (failed?.key === key ? failed.message : null),
    shown: (key: string) => (state?.key === key && state.status === "playing" ? shown : null),
    /** Where the playing loop of `key` is now, in seconds from its start. */
    position: (key: string) => {
      const current = playing.current;
      if (current?.key !== key || !context.current) return null;
      const elapsed = context.current.currentTime - current.started;
      return ((elapsed % LOOP_S) + LOOP_S) % LOOP_S;
    },
  };
}

export type SurroundingsPreview = ReturnType<typeof useSurroundingsPreview>;
