import { useState } from "react";

import { briefLength, type Draft, MIN_BRIEF_CHARS } from "@/lib/agent-draft";
import { revealErrors } from "@/lib/forms";
import { APPEAR } from "@/lib/motion";
import { isPhoneNumber, outboundProblems } from "@/lib/outbound";
import { MAX_CONFIG_CHARS } from "@/pages/agent-config-field";

/** An agent being added or edited: the draft, what it still needs, and a check that shows the
 * problems and moves focus to the first one. `baseline` is the draft with no changes. */
export function useAgentDraft(baseline: Draft, start: Draft = baseline) {
  const [draft, setDraft] = useState(start);
  const [submitted, setSubmitted] = useState(false);
  const [switched, setSwitched] = useState(false);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    if (key === "direction") setSwitched(true);
    setDraft((current) => ({ ...current, [key]: value }));
  };
  const outbound = draft.direction === "outbound";
  const needs = {
    name: draft.name.trim() === "",
    direction: draft.direction === null,
    reach:
      draft.direction !== null &&
      (outbound
        ? Object.keys(outboundProblems(draft.outbound)).length > 0
        : !isPhoneNumber(draft.agent_number)),
    brief: briefLength(draft.brief) < MIN_BRIEF_CHARS,
    config: draft.config.length > MAX_CONFIG_CHARS,
  };
  const ready = !Object.values(needs).some(Boolean);
  /** Shows the problems; `valid` narrows the check to the fields in view. */
  const check = (element: HTMLFormElement, valid = ready) =>
    revealErrors(element, () => setSubmitted(true), valid);
  /** Who calls changed, so fields that swap with it may fade in; the first render stays still. */
  const swap = switched ? APPEAR : undefined;
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  return {
    draft,
    set,
    submitted,
    hideErrors: () => setSubmitted(false),
    outbound,
    needs,
    ready,
    check,
    swap,
    dirty,
  };
}

export type AgentDraft = ReturnType<typeof useAgentDraft>;
