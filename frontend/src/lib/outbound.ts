import type {
  Header,
  OutboundSettings,
  QueryParameter,
  StartRequestDraft,
  TriggerMethod,
} from "@/lib/types";

export interface OutboundDraft {
  method: TriggerMethod;
  url: string;
  headers: Header[];
  /** Kept while a GET is chosen, so switching back to POST keeps it. */
  body: string;
  query: QueryParameter[];
  calling_numbers: string[];
  dial_window: string;
}

const EMPTY_BODY = '{\n  "to": "{{yaksha.number}}"\n}';
const EMPTY_QUERY: QueryParameter[] = [{ name: "to", value: "{{yaksha.number}}" }];

export const EMPTY_OUTBOUND: OutboundDraft = {
  method: "POST",
  url: "",
  headers: [],
  body: EMPTY_BODY,
  query: EMPTY_QUERY,
  calling_numbers: [],
  dial_window: "120",
};

/** The draft with the method, URL, headers and body or query of a start request read from a
 * cURL command or an import; the calling numbers and the wait time stay. */
export function withStartRequest(draft: OutboundDraft, request: StartRequestDraft): OutboundDraft {
  return {
    ...draft,
    method: request.method,
    url: request.url,
    headers: request.headers,
    body: request.body ? JSON.stringify(request.body, null, 2) : draft.body,
    query: request.method === "GET" ? request.query : draft.query,
  };
}

/** The fields a start request takes from each scenario: the names in its {{agent_data.<name>}}
 * placeholders, in order, once each. */
export function scenarioFields(request: StartRequestDraft): string[] {
  const text = JSON.stringify([request.body, request.query]);
  return [
    ...new Set(Array.from(text.matchAll(/\{\{agent_data\.([^{}]+)\}\}/g), (found) => found[1])),
  ];
}

const E164 = /^\+[1-9]\d{6,14}$/;

export function normalizeNumber(typed: string): string {
  return typed.replaceAll(/[\s-]/g, "");
}

export function isPhoneNumber(typed: string): boolean {
  return E164.test(normalizeNumber(typed));
}

export function toOutboundDraft(outbound: OutboundSettings): OutboundDraft {
  const { trigger } = outbound;
  return {
    method: trigger.method,
    url: trigger.url,
    headers: trigger.headers,
    body: trigger.body ? JSON.stringify(trigger.body, null, 2) : EMPTY_BODY,
    query: trigger.method === "GET" ? trigger.query : EMPTY_QUERY,
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

/** Why the server would refuse the URL: it takes an absolute http or https URL with no
 * placeholders. */
function urlProblem(typed: string): string | null {
  const url = typed.trim();
  if (!url) return "Enter the URL Yaksha sends the request to.";
  if (url.includes("{{") || url.includes("}}")) {
    return "Put placeholders in the headers, the body or the query parameters, not in the URL.";
  }
  if (url.includes("#")) return "Remove the # part: Yaksha does not send it.";
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:" ? null : "Use an http or https URL.";
  } catch {
    return "Enter a full URL, like https://api.example.com/calls.";
  }
}

/** Problems that keep the settings from being saved, by field. */
export function outboundProblems(
  draft: OutboundDraft,
): Partial<Record<keyof OutboundDraft, string>> {
  const window = Number(draft.dial_window);
  const numbers = draft.calling_numbers.map(normalizeNumber).filter(Boolean);
  const url = urlProblem(draft.url);
  return {
    ...(url ? { url } : {}),
    ...(draft.method === "GET" || parseBody(draft.body)
      ? {}
      : { body: "The body must be a JSON object." }),
    ...(unnamed(draft.headers) ? { headers: "Give each header a name, or remove it." } : {}),
    ...(draft.method === "GET" && unnamed(draft.query)
      ? { query: "Give each parameter a name, or remove it." }
      : {}),
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
      method: draft.method,
      url: draft.url.trim(),
      headers: named(draft.headers),
      query: draft.method === "GET" ? named(draft.query) : [],
      body: draft.method === "POST" ? (parseBody(draft.body) ?? {}) : null,
    },
    calling_numbers: draft.calling_numbers.map(normalizeNumber).filter(Boolean),
    dial_window_s: Number(draft.dial_window),
  };
}

/** Whether a row has a value but no name, which would be dropped. */
function unnamed(pairs: { name: string; value: string }[]): boolean {
  return pairs.some((pair) => !pair.name.trim() && pair.value.trim());
}

/** The pairs with a name, trimmed; a row left empty is dropped. */
function named<T extends { name: string; value: string }>(pairs: T[]): T[] {
  return pairs.map((pair) => ({ ...pair, name: pair.name.trim() })).filter((pair) => pair.name);
}
