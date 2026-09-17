import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  ACTIVE_STATUSES,
  type Agent,
  type AgentInput,
  type Conversation,
  type ConversationInput,
  type ConversationSummary,
  type Page,
} from "@/lib/types";

export const keys = {
  agents: ["agents"] as const,
  agent: (id: string) => ["agents", id] as const,
  conversations: (filters: Record<string, string>) => ["conversations", filters] as const,
  conversation: (id: string) => ["conversations", "one", id] as const,
};

const AGENTS_PAGE = 100;

async function allAgents(): Promise<Agent[]> {
  const agents: Agent[] = [];
  for (let page = 1; ; page++) {
    const result = await api<Page<Agent>>(`/agents?page=${page}&page_size=${AGENTS_PAGE}`);
    agents.push(...result.items);
    if (agents.length >= result.total || result.items.length === 0) return agents;
  }
}

export function useAgents() {
  return useQuery({ queryKey: keys.agents, queryFn: allAgents });
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
    onSuccess: () => client.invalidateQueries({ queryKey: keys.agents }),
  });
}

export const CONVERSATIONS_PAGE = 25;

export function useConversations(filters: Record<string, string>, page: number) {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(CONVERSATIONS_PAGE),
    ...filters,
  }).toString();
  return useQuery({
    queryKey: keys.conversations({ ...filters, page: String(page) }),
    queryFn: () => api<Page<ConversationSummary>>(`/conversations?${query}`),
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
