import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { refreshScenarios, useGenerations, useScenarios } from "@/lib/queries";
import { openStream, readEvents } from "@/lib/sse";
import type { GenerateInput, GenerationStatus, Scenario } from "@/lib/types";

export interface GenerationProgress {
  status: GenerationStatus;
  /** Null until the plan is made. */
  planned: number | null;
  saved: number;
  dropped: string[];
  error: string | null;
}

/** Runs one generation at a time for an agent. The stream is the generation: stopping it, or
 * leaving the page, stops the writing, and what is saved stays. It also follows a generation
 * that runs without a stream, such as a new agent's first scenarios, from the time this page
 * sees it running. */
export function useGeneration(agentId: string) {
  const client = useQueryClient();
  const [progress, setProgress] = useState<GenerationProgress | null>(null);
  const [newIds, setNewIds] = useState<ReadonlySet<string>>(new Set());
  const [streamedId, setStreamedId] = useState<string | null>(null);
  const generations = useGenerations(agentId);
  const [followed, setFollowed] = useState<string | null>(null);
  const running = generations.data?.find((item) => item.status === "running");
  if (running && !progress && followed !== running.id) setFollowed(running.id);
  const background = progress ? undefined : generations.data?.find((item) => item.id === followed);
  /** The generation the notice is about, and its scenarios whatever the list's filters. */
  const shownId = progress ? streamedId : (background?.id ?? null);
  const batch = useScenarios(agentId, Boolean(shownId), shownId);
  const backgroundState = background && `${background.status}:${background.scenarios}`;

  useEffect(() => {
    if (backgroundState) void refreshScenarios(client, agentId);
  }, [client, agentId, backgroundState]);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const patch = (next: Partial<GenerationProgress>) =>
    setProgress((current) => (current ? { ...current, ...next } : current));

  /** Resolves when the stream opens, and rejects with the API's reason if it is refused. */
  const start = async (input: GenerateInput): Promise<void> => {
    if (controller.current) throw new Error("A generation is already running.");
    const abort = new AbortController();
    controller.current = abort;
    let response: Response;
    try {
      response = await openStream(`/agents/${agentId}/scenarios/generate`, abort.signal, input);
    } catch (failure) {
      controller.current = null;
      throw failure;
    }
    setProgress({
      status: "running",
      planned: null,
      saved: 0,
      dropped: [],
      error: null,
    });
    let finished = false;
    void readEvents(response, ({ event, data }) => {
      const payload = JSON.parse(data);
      if (event === "started") {
        setStreamedId(payload.generation_id);
      } else if (event === "planned") {
        patch({ planned: payload.count });
      } else if (event === "scenario") {
        const scenario = payload as Scenario;
        setNewIds((current) => new Set(current).add(scenario.id));
        setProgress((current) => current && { ...current, saved: current.saved + 1 });
        void refreshScenarios(client, agentId);
      } else if (event === "dropped") {
        setProgress(
          (current) => current && { ...current, dropped: [...current.dropped, payload.reason] },
        );
      } else if (event === "finished") {
        finished = true;
        patch({ status: payload.status, saved: payload.saved, error: payload.error });
      }
    })
      .catch(() => undefined)
      .finally(() => {
        if (!finished) {
          patch({
            status: abort.signal.aborted ? "stopped" : "failed",
            error: abort.signal.aborted ? null : "The connection to Yaksh was lost.",
          });
        }
        if (controller.current === abort) controller.current = null;
        void refreshScenarios(client, agentId);
      });
  };

  const shown: GenerationProgress | null =
    progress ??
    (background
      ? {
          status: background.status,
          planned: background.count,
          saved: background.scenarios,
          dropped: [],
          error: background.error,
        }
      : null);
  const written = shownId ? (batch.data ?? []).map((item) => item.id) : [];

  return {
    progress: shown,
    newIds: new Set([...newIds, ...written]),
    /** The generation in the notice, and its scenarios that still exist. */
    id: shownId,
    written,
    running: shown?.status === "running",
    start,
    stop: () => {
      if (controller.current) controller.current.abort();
      else if (background)
        void api<void>(`/scenario-generations/${background.id}/stop`, { method: "POST" })
          .catch((error: Error) =>
            toast.error("Could not stop the generation", { description: error.message }),
          )
          .finally(() => refreshScenarios(client, agentId));
    },
    dismiss: () => {
      setProgress(null);
      setFollowed(null);
    },
  };
}
