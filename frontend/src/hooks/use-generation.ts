import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { refreshScenarios } from "@/lib/queries";
import { openStream, readEvents } from "@/lib/sse";
import type { GenerateInput, GenerationStatus, Scenario } from "@/lib/types";

export interface GenerationRun {
  status: GenerationStatus;
  /** Null until the plan is made. */
  planned: number | null;
  saved: number;
  dropped: string[];
  error: string | null;
}

/** Runs one generation at a time for an agent. The stream is the generation: stopping it, or
 * leaving the page, stops the writing, and what is saved stays. */
export function useGeneration(agentId: string) {
  const client = useQueryClient();
  const [run, setRun] = useState<GenerationRun | null>(null);
  const [newIds, setNewIds] = useState<ReadonlySet<string>>(new Set());
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const patch = (next: Partial<GenerationRun>) =>
    setRun((current) => (current ? { ...current, ...next } : current));

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
    setRun({
      status: "running",
      planned: null,
      saved: 0,
      dropped: [],
      error: null,
    });
    let finished = false;
    void readEvents(response, ({ event, data }) => {
      const payload = JSON.parse(data);
      if (event === "planned") {
        patch({ planned: payload.count });
      } else if (event === "scenario") {
        const scenario = payload as Scenario;
        setNewIds((current) => new Set(current).add(scenario.id));
        setRun((current) => current && { ...current, saved: current.saved + 1 });
        void refreshScenarios(client, agentId);
      } else if (event === "dropped") {
        setRun(
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
            error: abort.signal.aborted ? null : "The connection to Truman was lost.",
          });
        }
        if (controller.current === abort) controller.current = null;
        void refreshScenarios(client, agentId);
      });
  };

  return {
    run,
    newIds,
    running: run?.status === "running",
    start,
    stop: () => controller.current?.abort(),
    dismiss: () => setRun(null),
  };
}
