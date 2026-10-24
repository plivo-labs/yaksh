import type { RecordProvider, RecordSource } from "@/lib/types";

/** What the console shows for each provider of agent records. The only file here that knows a
 * provider. */
export const RECORD_PROVIDERS: Record<
  RecordProvider,
  { label: string; urlPlaceholder: string; headerPlaceholder: string }
> = {
  plivo_cx: {
    label: "Plivo CX",
    urlPlaceholder: "https://api.plivo.com/v1/Account/<Auth ID>/AgentFlow/<agent ID>/",
    headerPlaceholder: "Basic {{secrets.PLIVO_CX_AUTH}}",
  },
};

export const EMPTY_RECORD_SOURCE: RecordSource = { provider: "plivo_cx", url: "", headers: [] };
