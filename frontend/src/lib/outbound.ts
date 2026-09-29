import type { Header, OutboundSettings } from "@/lib/types";

export interface OutboundDraft {
  url: string;
  headers: Header[];
  body: string;
  calling_numbers: string[];
  dial_window: string;
}

export const EMPTY_OUTBOUND: OutboundDraft = {
  url: "",
  headers: [],
  body: '{\n  "to": "{{truman.number}}"\n}',
  calling_numbers: [],
  dial_window: "120",
};

const E164 = /^\+[1-9]\d{6,14}$/;

export function normalizeNumber(typed: string): string {
  return typed.replaceAll(/[\s-]/g, "");
}

export function isPhoneNumber(typed: string): boolean {
  return E164.test(normalizeNumber(typed));
}

export function toOutboundDraft(outbound: OutboundSettings): OutboundDraft {
  return {
    url: outbound.trigger.url,
    headers: outbound.trigger.headers,
    body: JSON.stringify(outbound.trigger.body, null, 2),
    calling_numbers: outbound.calling_numbers,
    dial_window: String(outbound.dial_window_s),
  };
}

function parseBody(text: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(text);
    return value !== null && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** Problems that keep the settings from being saved, by field. */
export function outboundProblems(
  draft: OutboundDraft,
): Partial<Record<keyof OutboundDraft, string>> {
  const window = Number(draft.dial_window);
  const numbers = draft.calling_numbers.map(normalizeNumber).filter(Boolean);
  return {
    ...(draft.url.trim() ? {} : { url: "Enter the URL Truman sends the request to." }),
    ...(parseBody(draft.body) ? {} : { body: "The body must be a JSON object." }),
    ...(numbers.every(isPhoneNumber)
      ? {}
      : { calling_numbers: "Use the international format, like +14155550100." }),
    ...(Number.isInteger(window) && window >= 10 && window <= 600
      ? {}
      : { dial_window: "Enter a whole number from 10 to 600." }),
  };
}

export function toOutbound(draft: OutboundDraft): OutboundSettings {
  return {
    trigger: {
      url: draft.url.trim(),
      headers: draft.headers
        .map((header) => ({ name: header.name.trim(), value: header.value }))
        .filter((header) => header.name),
      body: parseBody(draft.body) ?? {},
    },
    calling_numbers: draft.calling_numbers.map(normalizeNumber).filter(Boolean),
    dial_window_s: Number(draft.dial_window),
  };
}
