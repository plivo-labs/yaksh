import type { Conversation } from "@/lib/types";

/** When the call connected, counted from the dial. The recording starts here; turn and wire
 * times count from the dial. */
export function connectedAt(conversation: Conversation): number | undefined {
  return conversation.wire_events.find((event) => event.kind === "connected")?.at_ms;
}

/** Where a turn starts on the recording, in seconds, by its number counted from 1; null when the
 * call never connected or has no such turn. */
export function turnStart(conversation: Conversation, turn: number): number | null {
  const connectedMs = connectedAt(conversation);
  const found = conversation.transcript[turn - 1];
  if (connectedMs === undefined || !found) return null;
  return Math.max(0, found.started_at_ms - connectedMs) / 1000;
}
