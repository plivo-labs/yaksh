import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, apiBlob } from "@/lib/api";
import {
  ACTIVE_STATUSES,
  type Agent,
  type AgentInput,
  type Conversation,
  type ConversationInput,
  type ConversationSummary,
  type Language,
  type Page,
  type Persona,
  type PhoneNumbers,
  type PersonaInput,
  type ProviderVoice,
  type Scenario,
  type ScenarioInput,
  type Voice,
  type VoiceEdit,
  type VoiceInput,
  type VoiceSettings,
} from "@/lib/types";

export const keys = {
  agents: ["agents"] as const,
  agent: (id: string) => ["agents", id] as const,
  conversations: (filters: Record<string, string>) => ["conversations", filters] as const,
  conversation: (id: string) => ["conversations", "one", id] as const,
  personas: ["personas"] as const,
  scenarios: (agentId: string) => ["agents", agentId, "scenarios"] as const,
  voices: ["voices"] as const,
  voicesFor: (language: Language | "all") => ["voices", language] as const,
  phoneNumbers: ["phone-numbers"] as const,
};

const PAGE_SIZE = 100;

async function all<T>(path: string, params: Record<string, string> = {}): Promise<T[]> {
  const items: T[] = [];
  for (let page = 1; ; page++) {
    const search = new URLSearchParams({
      ...params,
      page: String(page),
      page_size: String(PAGE_SIZE),
    });
    const result = await api<Page<T>>(`${path}?${search}`);
    items.push(...result.items);
    if (items.length >= result.total || result.items.length === 0) return items;
  }
}

export function useAgents() {
  return useQuery({ queryKey: keys.agents, queryFn: () => all<Agent>("/agents") });
}

export const AGENTS_PAGE = 25;

/** One page of agents, filtered on the server by `search`. The previous page stays on screen
 * while the next one loads, so typing does not flash the table. */
export function useAgentPage(search: string, sort: string, page: number) {
  const params = new URLSearchParams({ page: String(page), page_size: String(AGENTS_PAGE) });
  if (search) params.set("q", search);
  if (sort) params.set("sort", sort);
  return useQuery({
    queryKey: [...keys.agents, "page", { search, sort, page }],
    queryFn: ({ signal }) => api<Page<Agent>>(`/agents?${params}`, { signal }),
    placeholderData: keepPreviousData,
  });
}

export function usePersonas() {
  return useQuery({ queryKey: keys.personas, queryFn: () => all<Persona>("/personas") });
}

export function useSavePersona(id?: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: PersonaInput) =>
      id
        ? api<Persona>(`/personas/${id}`, { method: "PATCH", json: input })
        : api<Persona>("/personas", { method: "POST", json: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.personas }),
  });
}

export function useDeletePersona() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/personas/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.personas }),
  });
}

export function useScenarios(agentId: string, enabled = true) {
  return useQuery({
    queryKey: keys.scenarios(agentId),
    queryFn: () => all<Scenario>(`/agents/${agentId}/scenarios`),
    enabled: enabled && Boolean(agentId),
  });
}

export function useSaveScenario(agentId: string, id?: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: ScenarioInput) =>
      id
        ? api<Scenario>(`/scenarios/${id}`, { method: "PATCH", json: input })
        : api<Scenario>(`/agents/${agentId}/scenarios`, { method: "POST", json: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.scenarios(agentId) }),
  });
}

export function useDeleteScenario(agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/scenarios/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.scenarios(agentId) }),
  });
}

export function usePreviewVoice() {
  return useMutation({
    mutationFn: (input: { voice: VoiceSettings; language: Language }) =>
      apiBlob("/voices/preview", { method: "POST", json: input }),
  });
}

export function useVoices(language?: Language) {
  return useQuery({
    queryKey: keys.voicesFor(language ?? "all"),
    queryFn: () => all<Voice>("/voices", language ? { language } : {}),
    placeholderData: keepPreviousData,
  });
}

export function useLookupVoice() {
  return useMutation({
    mutationFn: (providerVoiceId: string) =>
      api<ProviderVoice>(
        `/voices/lookup?${new URLSearchParams({
          provider: "elevenlabs",
          provider_voice_id: providerVoiceId,
        })}`,
      ),
  });
}

export function useAddVoice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: VoiceInput) => api<Voice>("/voices", { method: "POST", json: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.voices }),
  });
}

export function useEditVoice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...input }: VoiceEdit & { id: string }) =>
      api<Voice>(`/voices/${id}`, { method: "PATCH", json: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.voices }),
  });
}

export function useDeleteVoice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/voices/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.voices }),
  });
}

export function useAgent(id: string | undefined) {
  return useQuery({
    queryKey: keys.agent(id ?? ""),
    queryFn: () => api<Agent>(`/agents/${id}`),
    enabled: Boolean(id),
  });
}

export function useSaveAgent(id?: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: AgentInput) =>
      id
        ? api<Agent>(`/agents/${id}`, { method: "PATCH", json: input })
        : api<Agent>("/agents", { method: "POST", json: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.agents }),
  });
}

export function useDuplicateAgent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<Agent>(`/agents/${id}/duplicate`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.agents }),
  });
}

export function useDeleteAgent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/agents/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => {
      client.removeQueries({ queryKey: keys.agent(id) });
      return client.invalidateQueries({ queryKey: keys.agents });
    },
  });
}

export const CONVERSATIONS_PAGE = 25;

export function useConversations(filters: Record<string, string>, page: number) {
  const search = new URLSearchParams({
    page: String(page),
    page_size: String(CONVERSATIONS_PAGE),
    ...filters,
  }).toString();
  return useQuery({
    queryKey: keys.conversations({ ...filters, page: String(page) }),
    queryFn: ({ signal }) => api<Page<ConversationSummary>>(`/conversations?${search}`, { signal }),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => ACTIVE_STATUSES.includes(item.status))
        ? 3_000
        : 15_000,
  });
}

export function useConversation(id: string | undefined) {
  return useQuery({
    queryKey: keys.conversation(id ?? ""),
    queryFn: () => api<Conversation>(`/conversations/${id}`),
    enabled: Boolean(id),
  });
}

export function useStartConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: ConversationInput) =>
      api<ConversationSummary>("/conversations", { method: "POST", json: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

export function useEndConversation(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<Conversation>(`/conversations/${id}/end`, { method: "POST" }),
    onSuccess: (conversation) => {
      client.setQueryData(keys.conversation(id), conversation);
      void client.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

/** The agent's most recent conversation, or null when it has never been called. */
export function useLastCall(agentId: string) {
  const search = new URLSearchParams({ agent_id: agentId, page_size: "1" });
  return useQuery({
    queryKey: keys.conversations({ agent_id: agentId, last: "1" }),
    queryFn: async () =>
      (await api<Page<ConversationSummary>>(`/conversations?${search}`)).items[0] ?? null,
    refetchInterval: (query) =>
      query.state.data && ACTIVE_STATUSES.includes(query.state.data.status) ? 3_000 : 15_000,
  });
}

export function useScenarioCount(agentId: string) {
  return useQuery({
    queryKey: [...keys.scenarios(agentId), "count"],
    queryFn: async () =>
      (await api<Page<Scenario>>(`/agents/${agentId}/scenarios?page_size=1`)).total,
  });
}

export interface Recording {
  src: string;
  duration: number;
  /** Peak level of each 10 ms of the call for each channel, 0 to 1 against the loudest moment. */
  lanes: Float32Array[];
}

const BUCKET_S = 0.01;

/** Loads a recording with the API token and measures its waveform. The object URL lives as
 * long as the page. */
// ponytail: object URLs are not revoked; revoke on cache removal if pages stay open for hours.
export function useRecording(url: string | null) {
  return useQuery({
    queryKey: ["recording", url],
    enabled: url !== null,
    staleTime: Infinity,
    queryFn: async ({ signal }): Promise<Recording> => {
      const blob = await apiBlob(url!.replace(/^\/api\/v1/, ""), { signal });
      const decoded = await new OfflineAudioContext(1, 1, 8000).decodeAudioData(
        await blob.arrayBuffer(),
      );
      const size = Math.max(1, Math.round(decoded.sampleRate * BUCKET_S));
      const lanes = Array.from({ length: decoded.numberOfChannels }, (_, index) =>
        peaks(decoded.getChannelData(index), size),
      );
      const loudest = Math.max(
        1e-6,
        ...lanes.map((lane) => lane.reduce((a, b) => Math.max(a, b), 0)),
      );
      for (const lane of lanes) {
        for (let i = 0; i < lane.length; i++) lane[i] /= loudest;
      }
      return { src: URL.createObjectURL(blob), duration: decoded.duration, lanes };
    },
  });
}

function peaks(samples: Float32Array, size: number): Float32Array {
  const out = new Float32Array(Math.ceil(samples.length / size));
  for (let i = 0; i < samples.length; i++) {
    const slot = Math.floor(i / size);
    const level = Math.abs(samples[i]);
    if (level > out[slot]) out[slot] = level;
  }
  return out;
}

export function usePhoneNumbers() {
  return useQuery({
    queryKey: keys.phoneNumbers,
    queryFn: () => api<PhoneNumbers>("/phone-numbers"),
  });
}
