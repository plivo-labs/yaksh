import { useEffect, useRef, useState } from "react";

import { usePreviewVoice } from "@/lib/queries";
import type { Language, VoiceSettings } from "@/lib/types";

/** Plays ElevenLabs speech generated with the settings a call uses, one clip at a time. `key`
 * names who asked (a persona card, the form) so each can show its own state. Clips are kept by
 * settings, so the same voice, speed, stability and language play again without a new
 * request. */
export function useVoicePreview() {
  const generate = usePreviewVoice();
  const clips = useRef(new Map<string, string>());
  const player = useRef<HTMLAudioElement | null>(null);
  const request = useRef(0);
  const [playing, setPlaying] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(null);

  useEffect(() => {
    const urls = clips.current;
    return () => {
      player.current?.pause();
      for (const url of urls.values()) URL.revokeObjectURL(url);
      urls.clear();
    };
  }, []);

  const start = (key: string, url: string) => {
    player.current?.pause();
    const audio = new Audio(url);
    audio.onended = () => setPlaying((current) => (current === key ? null : current));
    player.current = audio;
    setFailed(null);
    setPlaying(key);
    audio.play().catch((error: unknown) => {
      if (player.current !== audio) return;
      const name = error instanceof DOMException ? error.name : "";
      if (name === "AbortError") return;
      setPlaying((current) => (current === key ? null : current));
      setFailed({
        key,
        message:
          name === "NotAllowedError"
            ? "The browser blocked playback. Click play again."
            : "The browser could not play this audio.",
      });
    });
  };

  const stop = () => {
    player.current?.pause();
    player.current = null;
    setPlaying(null);
  };

  const toggle = (
    key: string,
    voice: VoiceSettings,
    language: Language,
    sampleLine: string | null = null,
  ) => {
    if (loading === key) return;
    if (playing === key) {
      stop();
      return;
    }
    const settings = JSON.stringify([voice, language, sampleLine]);
    const clip = clips.current.get(settings);
    if (clip) {
      start(key, clip);
      return;
    }
    const token = ++request.current;
    setLoading(key);
    setFailed(null);
    generate.mutate(
      { voice, language, sample_line: sampleLine },
      {
        onSuccess: (audio) => {
          const url = URL.createObjectURL(audio);
          clips.current.set(settings, url);
          if (token === request.current) start(key, url);
        },
        onError: (error) => {
          if (token === request.current) setFailed({ key, message: error.message });
        },
        onSettled: () => setLoading((current) => (current === key ? null : current)),
      },
    );
  };

  /** Forgets everything `key` asked for: stops its clip, drops its error, and keeps a pending
   * request from playing when it arrives. */
  const reset = (key: string) => {
    if (loading === key) request.current++;
    if (playing === key) stop();
    setLoading((current) => (current === key ? null : current));
    setFailed((current) => (current?.key === key ? null : current));
  };

  return {
    toggle,
    reset,
    isPlaying: (key: string) => playing === key,
    isLoading: (key: string) => loading === key,
    error: (key: string) => (failed?.key === key ? failed.message : null),
  };
}

export type VoicePreview = ReturnType<typeof useVoicePreview>;
