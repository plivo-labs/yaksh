import {
  type QueryClient,
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ApiError, api, apiBlob } from "@/lib/api";
import { toRules } from "@/lib/rules";
import {
  ACTIVE_RUN_STATUSES,
  ACTIVE_STATUSES,
  type Agent,
  type AgentDraft,
  type AppSettings,
  type AgentInput,
  type StartRequestDraft,
  type AgentRule,
  type AgentSummary,
  type DocumentRead,
  type DocumentSummary,
  type KnowledgeBaseEntry,
  type Conversation,
  type ConversationEvaluation,
  type EvaluationState,
  evaluationPending,
  type Defaults,
  type ConversationSummary,
  type Generation,
  type ImportResult,
  type JudgeAgreement,
  type LabelAnswer,
  type LabelReason,
  type QueuedReview,
  type ReviewConversation,
  type Language,
  type Page,
  type Persona,
  type PhoneNumbers,
  type ProviderTest,
  type PersonaInput,
  type PersonaScenario,
  type ProviderVoice,
  type Run,
  type RunInput,
  type RunMetrics,
  type RunStatus,
  type RunSummary,
  type RuleResults,
  type Scenario,
  type SoundPlan,
  type Surroundings,
  type ScenarioInput,
  type SecretName,
  type SettingsProvider,
  type SettingsValues,
  type Voice,
  type VoiceEdit,
  type VoiceInput,
  type VoiceSettings,
} from "@/lib/types";

export const keys = {
  agents: ["agents"] as const,
  agent: (id: string) => ["agents", id] as const,
  briefDraft: (id: string) => ["brief-draft", id] as const,
  ruleResults: (id: string) => ["agents", id, "rule-results"] as const,
  conversations: (filters: Record<string, string>) => ["conversations", filters] as const,
  conversation: (id: string) => ["conversations", "one", id] as const,
  conversationEvaluation: (id: string, evaluation: EvaluationState | null) =>
    ["conversations", "evaluation", id, evaluation ?? "none"] as const,
  personas: ["personas"] as const,
  persona: (id: string) => ["personas", id] as const,
  personaScenarios: (id: string) => ["personas", id, "scenarios"] as const,
  scenario: (id: string) => ["scenarios", "one", id] as const,
  scenarios: (agentId: string) => ["agents", agentId, "scenarios"] as const,
  scenariosOf: (agentId: string, generationId: string | null) =>
    ["agents", agentId, "scenarios", generationId ?? "all"] as const,
  generations: (agentId: string) => ["agents", agentId, "generations"] as const,
  voices: ["voices"] as const,
  voicesFor: (language: Language | "all") => ["voices", language] as const,
  phoneNumbers: ["phone-numbers"] as const,
  runs: (filters: RunFilters) =>
    [
      "runs",
      "list",
      filters.agentId ?? "all",
      filters.status ?? "any",
      filters.createdFrom ?? "",
      filters.createdBefore ?? "",
      filters.lastHours ?? 0,
    ] as const,
  run: (id: string) => ["runs", "one", id] as const,
  runMetrics: (id: string) => ["runs", "metrics", id] as const,
  document: (id: string) => ["documents", id] as const,
  reviewQueue: ["review", "queue"] as const,
  review: (conversationId: string, seen: boolean) =>
    ["review", "one", conversationId, seen] as const,
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
  return useQuery({ queryKey: keys.agents, queryFn: () => all<AgentSummary>("/agents") });
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
    queryFn: ({ signal }) => api<Page<AgentSummary>>(`/agents?${params}`, { signal }),
    placeholderData: keepPreviousData,
  });
}

/** The server's values for fields a request leaves out; they change with the settings. */
export function useDefaults() {
  return useQuery({
    queryKey: ["defaults"],
    queryFn: () => api<Defaults>("/defaults"),
    staleTime: 5 * 60_000,
  });
}

export function usePersonas() {
  return useQuery({ queryKey: keys.personas, queryFn: () => all<Persona>("/personas") });
}

export function usePersona(id: string | undefined) {
  return useQuery({
    queryKey: keys.persona(id ?? ""),
    queryFn: () => api<Persona>(`/personas/${id}`),
    enabled: Boolean(id),
  });
}

export function usePersonaScenarios(id: string | undefined) {
  return useQuery({
    queryKey: keys.personaScenarios(id ?? ""),
    queryFn: () => api<PersonaScenario[]>(`/personas/${id}/scenarios`),
    enabled: Boolean(id),
  });
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

export function useScenarios(agentId: string, enabled = true, generationId: string | null = null) {
  return useQuery({
    queryKey: keys.scenariosOf(agentId, generationId),
    queryFn: () =>
      all<Scenario>(
        `/agents/${agentId}/scenarios`,
        generationId ? { generation_id: generationId } : {},
      ),
    enabled: enabled && Boolean(agentId),
  });
}

/** The scenarios of a run to start, in the order asked. The agent's list gives most of them. An
 * id the list lacks is looked up alone, because a list read in pages can miss a row while
 * scenarios change; a scenario that is gone is left out. Without ids, every scenario of the agent
 * runs. Nothing is ready until every fetch has finished, so cached or partial data never decides
 * what runs. */
export function useRunScenarios(agentId: string, scenarioIds?: string[]) {
  const list = useScenarios(agentId);
  const listed = new Map((list.data ?? []).map((scenario) => [scenario.id, scenario]));
  const listSettled = list.isSuccess && list.fetchStatus === "idle";
  const ids = scenarioIds ?? (listSettled ? [...listed.keys()] : []);
  const unlisted = listSettled ? ids.filter((id) => !listed.has(id)) : [];
  const lookups = useQueries({
    queries: unlisted.map((id) => ({
      queryKey: keys.scenario(id),
      queryFn: async ({ signal }: { signal: AbortSignal }) => {
        try {
          return await api<Scenario>(`/scenarios/${id}`, { signal });
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) return null;
          throw error;
        }
      },
    })),
  });
  const found = new Map(listed);
  for (const lookup of lookups) if (lookup.data) found.set(lookup.data.id, lookup.data);
  const ready =
    listSettled && lookups.every((lookup) => lookup.isSuccess && lookup.fetchStatus === "idle");
  const scenarios = ready ? ids.flatMap((id) => found.get(id) ?? []) : [];
  return {
    scenarios,
    leftOut: ready ? ids.length - scenarios.length : 0,
    ready,
    error: list.error ?? lookups.find((lookup) => lookup.error)?.error ?? null,
  };
}

export function useGenerations(agentId: string) {
  return useQuery({
    queryKey: keys.generations(agentId),
    queryFn: () => all<Generation>(`/agents/${agentId}/scenario-generations`),
  });
}

/** Refreshes what a change to an agent's scenarios can change. */
export function refreshScenarios(client: QueryClient, agentId: string) {
  return Promise.all([
    client.invalidateQueries({ queryKey: keys.scenarios(agentId) }),
    client.invalidateQueries({ queryKey: keys.generations(agentId) }),
  ]);
}

export function useDeleteScenarios(agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) =>
      api<void>(`/agents/${agentId}/scenarios/delete`, {
        method: "POST",
        json: { scenario_ids: ids },
      }),
    onSettled: () => refreshScenarios(client, agentId),
  });
}

export function useAssignPersona(agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { scenario_ids: string[]; persona_id: string }) =>
      api<void>(`/agents/${agentId}/scenarios/persona`, { method: "POST", json: input }),
    onSettled: () => refreshScenarios(client, agentId),
  });
}

export function useSaveScenario(agentId: string, id?: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: ScenarioInput) =>
      id
        ? api<Scenario>(`/scenarios/${id}`, { method: "PATCH", json: input })
        : api<Scenario>(`/agents/${agentId}/scenarios`, { method: "POST", json: input }),
    onSuccess: () => refreshScenarios(client, agentId),
  });
}

export function useDeleteScenario(agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/scenarios/${id}`, { method: "DELETE" }),
    onSuccess: () => refreshScenarios(client, agentId),
  });
}

export function usePreviewVoice() {
  return useMutation({
    mutationFn: (input: {
      voice: VoiceSettings;
      language: Language;
      sample_line?: string | null;
    }) => apiBlob("/voices/preview", { method: "POST", json: input }),
  });
}

export function usePreviewPlan() {
  return useMutation({
    mutationFn: (input: { surroundings: Surroundings; language: Language; duration_s: number }) =>
      api<SoundPlan>("/sounds/plan", { method: "POST", json: input }),
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

/** Reads a cURL command into a start request. */
export function useStartRequestFromCurl() {
  return useMutation({
    mutationFn: (command: string) =>
      api<StartRequestDraft>("/agents/start-request-from-curl", {
        method: "POST",
        json: { command },
      }),
  });
}

/** A brief written by a model from the agent's config, for the person to check. */
export async function draftBrief(config: string): Promise<string> {
  const { brief } = await api<{ brief: string }>("/agents/draft-brief", {
    method: "POST",
    json: { config },
  });
  return brief;
}

/** Reads an agent file into a draft. A file Yaksha does not read fails with `not_recognized`. */
export function useImportAgentFile() {
  return useMutation({
    mutationFn: (content: string) =>
      api<AgentDraft>("/agents/import", { method: "POST", json: { content } }),
  });
}

/** The agent as the page shows it, for a change made to its latest saved state. */
function cachedAgent(client: QueryClient, agentId: string): Agent {
  const agent = client.getQueryData<Agent>(keys.agent(agentId));
  if (!agent) throw new Error("The agent is not loaded. Reload the page and try again.");
  return agent;
}

export function useRuleResults(agentId: string) {
  return useQuery({
    queryKey: keys.ruleResults(agentId),
    queryFn: () => api<RuleResults[]>(`/agents/${agentId}/rule-results`),
  });
}

/** Saves a change to an agent's rules, applied to the list as it is when the save starts. */
export function useSaveRules(agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (change: (current: AgentRule[]) => AgentRule[]) => {
      return api<Agent>(`/agents/${agentId}`, {
        method: "PATCH",
        json: { rules: toRules(change(cachedAgent(client, agentId).rules)) },
      });
    },
    onSuccess: (agent) => {
      client.setQueryData(keys.agent(agentId), agent);
      return client.invalidateQueries({ queryKey: keys.agents });
    },
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

/** One page of conversations. It refreshes every 3 seconds while a shown row is active or its
 * evaluation is pending, or while `live` says more rows can change, such as during a run;
 * otherwise every 15. */
export function useConversations(
  filters: Record<string, string>,
  page: number,
  { live = false }: { live?: boolean } = {},
) {
  const params = { ...filters, page: String(page), page_size: String(CONVERSATIONS_PAGE) };
  const search = new URLSearchParams(params).toString();
  return useQuery({
    queryKey: keys.conversations(params),
    queryFn: ({ signal }) => api<Page<ConversationSummary>>(`/conversations?${search}`, { signal }),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      live ||
      query.state.data?.items.some(
        (item) => ACTIVE_STATUSES.includes(item.status) || evaluationPending(item.evaluation),
      )
        ? 3_000
        : 15_000,
  });
}

/** One conversation. It refreshes while its evaluation is pending, so the response times
 * arrive without a reload. */
export function useConversation(id: string | undefined) {
  return useQuery({
    queryKey: keys.conversation(id ?? ""),
    queryFn: () => api<Conversation>(`/conversations/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data && evaluationPending(query.state.data.evaluation) ? 2_000 : false,
  });
}

/** The metrics of a finished evaluation, or why it failed; read again when the state
 * changes. */
export function useConversationEvaluation(id: string, evaluation: EvaluationState | null) {
  return useQuery({
    queryKey: keys.conversationEvaluation(id, evaluation),
    queryFn: ({ signal }) =>
      api<ConversationEvaluation>(`/conversations/${id}/evaluation`, { signal }),
    enabled: evaluation === "done" || evaluation === "failed",
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

export const RUNS_PAGE = 25;

/** Runs of one agent, of one status, or both; every run when neither is set. */
export interface RunFilters {
  agentId?: string;
  status?: RunStatus;
  createdFrom?: string;
  createdBefore?: string;
  /** The runs of the hours up to each fetch. Each refetch moves the window, the query key stays. */
  lastHours?: number;
}

export function useRuns(filters: RunFilters, page: number) {
  const search = new URLSearchParams({ page: String(page), page_size: String(RUNS_PAGE) });
  if (filters.agentId) search.set("agent_id", filters.agentId);
  if (filters.status) search.set("status", filters.status);
  if (filters.createdFrom) search.set("created_from", filters.createdFrom);
  if (filters.createdBefore) search.set("created_before", filters.createdBefore);
  return useQuery({
    queryKey: [...keys.runs(filters), page],
    queryFn: ({ signal }) => {
      if (filters.lastHours) {
        const from = new Date(Date.now() - filters.lastHours * 3_600_000);
        search.set("created_from", from.toISOString());
      }
      return api<Page<RunSummary>>(`/runs?${search}`, { signal });
    },
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => ACTIVE_RUN_STATUSES.includes(run.status))
        ? 3_000
        : 15_000,
  });
}

export function useRun(id: string | undefined) {
  return useQuery({
    queryKey: keys.run(id ?? ""),
    queryFn: ({ signal }) => api<Run>(`/runs/${id}`, { signal }),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data && ACTIVE_RUN_STATUSES.includes(query.state.data.status) ? 3_000 : false,
  });
}

/** The run's numbers. They refresh while the run is active or an evaluation is pending. */
export function useRunMetrics(id: string, active: boolean) {
  return useQuery({
    queryKey: keys.runMetrics(id),
    queryFn: ({ signal }) => api<RunMetrics>(`/runs/${id}/metrics`, { signal }),
    refetchInterval: (query) =>
      active ||
      (query.state.data?.overall.pending ?? 0) > 0 ||
      (query.state.data?.verdicts.pending ?? 0) > 0
        ? 3_000
        : false,
  });
}

/** How often blind audit labels agree with each judge version; it changes only as people
 * label, so it is read once a minute at most. */
export function useJudgeAgreement() {
  return useQuery({
    queryKey: ["judges", "agreement"],
    queryFn: ({ signal }) => api<JudgeAgreement>("/judges/agreement", { signal }),
    staleTime: 60_000,
  });
}

/** The key makes a repeated request, such as a double click, return the run it started. */
export function useStartRun(requestKey: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: RunInput) =>
      api<RunSummary>("/runs", {
        method: "POST",
        json: input,
        headers: { "Idempotency-Key": requestKey },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["runs"] });
      void client.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useCancelRun(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<Run>(`/runs/${id}/cancel`, { method: "POST" }),
    onSuccess: (run) => {
      client.setQueryData(keys.run(id), run);
      void client.invalidateQueries({ queryKey: ["runs"] });
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

/** Saves a change to an agent's knowledge base, applied to the list as it is when the save
 * starts, so an upload that took a while does not undo a change made meanwhile. */
export function useSaveKnowledgeBase(agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (change: (current: KnowledgeBaseEntry[]) => KnowledgeBaseEntry[]) => {
      const current = cachedAgent(client, agentId).knowledge_base.map(({ document_id, name }) => ({
        document_id,
        name,
      }));
      return api<Agent>(`/agents/${agentId}`, {
        method: "PATCH",
        json: { knowledge_base: change(current) },
      });
    },
    onSuccess: (agent) => {
      client.setQueryData(keys.agent(agentId), agent);
      return client.invalidateQueries({ queryKey: keys.agents });
    },
  });
}

export function uploadDocument(file: File): Promise<DocumentSummary> {
  const form = new FormData();
  form.append("file", file);
  return api<DocumentSummary>("/documents/upload", { method: "POST", form });
}

export function createTextDocument(name: string, text: string): Promise<DocumentSummary> {
  return api<DocumentSummary>("/documents", { method: "POST", json: { name, text } });
}

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: keys.document(id ?? ""),
    queryFn: () => api<DocumentRead>(`/documents/${id}`),
    enabled: Boolean(id),
    staleTime: Infinity,
  });
}

export async function downloadDocument(id: string, name: string): Promise<void> {
  const url = URL.createObjectURL(await apiBlob(`/documents/${id}/file`));
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  link.click();
  URL.revokeObjectURL(url);
}

/** The audit calls this labeler still has items to label in. */
export function useReviewQueue() {
  return useQuery({
    queryKey: keys.reviewQueue,
    queryFn: ({ signal }) => api<QueuedReview[]>("/review/queue", { signal }),
  });
}

/** A judged call as this labeler sees it: blind items carry no machine result. `seen`: the
 * labeler came from the machine's results, so the call is ad hoc. */
export function useReview(conversationId: string, seen: boolean) {
  return useQuery({
    queryKey: keys.review(conversationId, seen),
    queryFn: ({ signal }) =>
      api<ReviewConversation>(`/review/conversations/${conversationId}?seen=${seen}`, { signal }),
  });
}

export interface LabelInput {
  answer: LabelAnswer;
  reason: LabelReason | null;
  note: string | null;
}

/** Labels one item; the call comes back with what the label reveals. */
export function useSaveLabel(conversationId: string, seen: boolean) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, label }: { itemId: string; label: LabelInput }) =>
      api<ReviewConversation>(`/review/items/${itemId}/labels`, {
        method: "POST",
        json: { ...label, seen },
      }),
    onSuccess: (found) => {
      client.setQueryData(keys.review(conversationId, seen), found);
      void client.invalidateQueries({ queryKey: keys.reviewQueue });
    },
  });
}

const settingsKey = ["settings"] as const;

export function useSettings() {
  return useQuery({ queryKey: settingsKey, queryFn: () => api<AppSettings>("/settings") });
}

/** After a change of the settings: what the server reads from them may change too. */
function settingsChanged(client: QueryClient, settings: AppSettings) {
  client.setQueryData(settingsKey, settings);
  // A new key or base URL can change the provider's models and what each takes.
  void client.invalidateQueries({ queryKey: [...settingsKey, "models"] });
  void client.invalidateQueries({ queryKey: [...settingsKey, "efforts"] });
  void client.invalidateQueries({ queryKey: ["defaults"] });
  void client.invalidateQueries({ queryKey: keys.phoneNumbers });
}

export function useSaveSettingsValues() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: SettingsValues) =>
      api<AppSettings>("/settings/values", { method: "PUT", json: values }),
    onSuccess: (settings) => settingsChanged(client, settings),
  });
}

/** Saves a key after its provider accepted it; a refused key is an error and is not saved. */
export function useSaveSecret() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ name, value }: { name: SecretName; value: string }) =>
      api<AppSettings>(`/settings/secrets/${name}`, { method: "PUT", json: { value } }),
    onSuccess: (settings) => settingsChanged(client, settings),
  });
}

/** Saves a Plivo account's Auth ID and Auth token together, after Plivo accepts them. */
export function useSavePlivoAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (account: { auth_id: string; auth_token: string }) =>
      api<AppSettings>("/settings/plivo", { method: "PUT", json: account }),
    onSuccess: (settings) => settingsChanged(client, settings),
  });
}

export function useRemoveSecret() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: SecretName) =>
      api<AppSettings>(`/settings/secrets/${name}`, { method: "DELETE" }),
    onSuccess: (settings) => settingsChanged(client, settings),
  });
}

export function useSaveTriggerSecret() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ name, value }: { name: string; value: string }) =>
      api<AppSettings>(`/settings/trigger-secrets/${encodeURIComponent(name)}`, {
        method: "PUT",
        json: { value },
      }),
    onSuccess: (settings) => settingsChanged(client, settings),
  });
}

export function useRemoveTriggerSecret() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api<AppSettings>(`/settings/trigger-secrets/${encodeURIComponent(name)}`, {
        method: "DELETE",
      }),
    onSuccess: (settings) => settingsChanged(client, settings),
  });
}

/** Makes a new signing key; the response is the only time it is shown. */
export function useNewSigningKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ key: string }>("/settings/signing-key", { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: settingsKey }),
  });
}

export function useTestProvider() {
  return useMutation({
    mutationFn: (provider: SettingsProvider) =>
      api<ProviderTest>(`/settings/providers/${provider}/test`, { method: "POST" }),
  });
}

/** The models the LLM provider lists; fetched when asked, and again with refetch(). */
export function useProviderModels(enabled: boolean) {
  return useQuery({
    queryKey: [...settingsKey, "models"],
    queryFn: () => api<{ models: string[] }>("/settings/models"),
    enabled,
    staleTime: Infinity,
    retry: false,
  });
}

/** The reasoning efforts a model takes; one short request per effort, so it is kept. */
export function useModelEfforts(model: string | null) {
  return useQuery({
    queryKey: [...settingsKey, "efforts", model],
    queryFn: () =>
      api<{ model: string; efforts: string[] }>(
        `/settings/models/${encodeURIComponent(model ?? "")}/efforts`,
      ),
    enabled: Boolean(model),
    staleTime: Infinity,
    retry: false,
  });
}

export async function exportSettings(): Promise<string> {
  return (await apiBlob("/settings/export")).text();
}

export function useImportSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ document, dryRun }: { document: string; dryRun: boolean }) =>
      api<ImportResult>("/settings/import", {
        method: "POST",
        json: { document, dry_run: dryRun },
      }),
    onSuccess: (result, { dryRun }) => {
      if (!dryRun) settingsChanged(client, result.settings);
    },
  });
}
