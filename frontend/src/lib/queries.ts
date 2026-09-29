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
    queryFn: () => api<Page<ConversationSummary>>(`/conversations?${search}`),
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
