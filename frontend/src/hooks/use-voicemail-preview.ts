import { useEffect, useRef, useState } from "react";

import { TONE_FILE, voicemailOf } from "@/lib/answering";
import { apiBlob } from "@/lib/api";
import { usePreviewVoice } from "@/lib/queries";
import type { Answering, Language, VoiceSettings } from "@/lib/types";

const TONE_GAP_MS = 300;

/** Plays a persona's voicemail as a call hears it: the greeting, then the tone. The persona's
 * own greeting is spoken in its voice, as a voice preview is; the standard greeting and the tone
 * are the files that calls play. Clips are kept, so playing again makes no new request. */
export function useVoicemailPreview() {
  const speak = usePreviewVoice();
  const clips = useRef(new Map<string, string>());
  const audio = useRef<HTMLAudioElement | null>(null);
  const run = useRef(0);
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const urls = clips.current;
    return () => {
      run.current += 1;
      audio.current?.pause();
      for (const url of urls.values()) URL.revokeObjectURL(url);
      urls.clear();
    };
  }, []);

  const clip = async (key: string, fetch: () => Promise<Blob>) => {
    const kept = clips.current.get(key);
    if (kept) return kept;
    const url = URL.createObjectURL(await fetch());
    clips.current.set(key, url);
    return url;
  };

  const play = (url: string, token: number) =>
    new Promise<void>((resolve, reject) => {
      if (token !== run.current) return resolve();
      const playing = new Audio(url);
      audio.current = playing;
      playing.onended = () => resolve();
      playing.onerror = () => reject(new Error("The browser could not play this audio."));
      playing.play().catch((cause: unknown) => {
        const name = cause instanceof DOMException ? cause.name : "";
        if (name === "AbortError") return resolve();
        reject(
          new Error(
            name === "NotAllowedError"
              ? "The browser blocked playback. Click play again."
              : "The browser could not play this audio.",
          ),
        );
      });
    });

  const stop = () => {
    run.current += 1;
    audio.current?.pause();
    audio.current = null;
    setState("idle");
  };

  const toggle = async (answering: Answering, voice: VoiceSettings, language: Language) => {
    if (state !== "idle") return stop();
    run.current += 1;
    const token = run.current;
    setState("loading");
    setError(null);
    try {
      const kind = voicemailOf(answering.voicemail);
      const own = kind.value === "mailbox_full" ? null : answering.greeting?.trim() || null;
      const greeting = await (own
        ? clip(JSON.stringify([voice, language, own]), () =>
            speak.mutateAsync({ voice, language, sample_line: own }),
          )
        : clip(kind.greeting, () => apiBlob(`/sounds/${kind.greeting}`)));
      const tone = kind.tone ? await clip(TONE_FILE, () => apiBlob(`/sounds/${TONE_FILE}`)) : null;
      if (token !== run.current) return;
      setState("playing");
      await play(greeting, token);
      if (tone) {
        await new Promise((resolve) => setTimeout(resolve, TONE_GAP_MS));
        await play(tone, token);
      }
    } catch (cause) {
      if (token === run.current) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (token === run.current) setState("idle");
    }
  };

  return {
    toggle,
    stop,
    isPlaying: state === "playing",
    isLoading: state === "loading",
    error,
  };
}
