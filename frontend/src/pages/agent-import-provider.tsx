import { type UseMutationResult, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Search } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";

import elevenLabsLogo from "@/assets/providers/elevenlabs.svg";
import plivoCxLogo from "@/assets/providers/plivo-cx.svg";
import retellLogo from "@/assets/providers/retell.png";
import vapiLogo from "@/assets/providers/vapi.svg";
import { Panel } from "@/components/panel";
import { StepFooter } from "@/components/step-footer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { EMPTY_DRAFT } from "@/lib/agent-draft";
import { counted, phone, when } from "@/lib/format";
import { APPEAR } from "@/lib/motion";
import { type ImportedFrom, startImportedDraft } from "@/lib/new-agent-draft";
import { scenarioFields, withStartRequest } from "@/lib/outbound";
import {
  draftBrief,
  keys,
  useElevenLabsAgents,
  useImportElevenLabsAgent,
  useImportPlivoCxFlow,
  useImportRetellAgent,
  useImportVapiAssistant,
  usePlivoCxFlows,
  useRetellAgents,
  useVapiAssistants,
} from "@/lib/queries";
import { randomKey } from "@/lib/random-key";
import {
  type ElevenLabsAccount,
  type ElevenLabsRegion,
  languageNames,
  type PlivoCxAccount,
  type ProviderDraft,
  type RetellAccount,
  type VapiAccount,
  type VapiRegion,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type ProviderId = "plivo-cx" | "elevenlabs" | "vapi" | "retell";

/** Each provider's own icon, as its website serves it. */
const PROVIDERS: { id: ProviderId | null; name: string; logo: string }[] = [
  { id: "plivo-cx", name: "Plivo CX", logo: plivoCxLogo },
  { id: "elevenlabs", name: "ElevenLabs", logo: elevenLabsLogo },
  { id: "vapi", name: "Vapi", logo: vapiLogo },
  { id: "retell", name: "Retell", logo: retellLogo },
];

const REGIONS: { value: ElevenLabsRegion; label: string }[] = [
  { value: "global", label: "elevenlabs.io" },
  { value: "eu", label: "EU" },
  { value: "in", label: "India" },
  { value: "sg", label: "Singapore" },
];

const VAPI_REGIONS: { value: VapiRegion; label: string }[] = [
  { value: "us", label: "US" },
  { value: "eu", label: "EU" },
];

/** Where each provider's API key comes from, and what Yaksh does with it. */
const KEY_HELP: Record<Exclude<ProviderId, "plivo-cx">, string> = {
  elevenlabs:
    "An API key with ElevenAgents access, from the developers page of ElevenLabs. Yaksh uses it for this import and does not save it, except in the start request of an agent that calls out.",
  vapi: "The private API key, from the API keys page of the Vapi dashboard. Yaksh uses it for this import and does not save it, except in the start request of an assistant that calls out.",
  retell:
    "An API key from the API keys page of Retell. Yaksh uses it for this import and does not save it, except in the start request of an agent that calls out.",
};

/** How each kind of flow that Yaksh lists takes calls; the server leaves out the others. */
const CALL_TYPES: Record<string, string> = {
  incoming_call: "Answers calls",
  api_request: "Calls out on a request",
  omni: "Several channels",
};

type Connection =
  | { provider: "plivo-cx"; account: PlivoCxAccount; id: string }
  | { provider: "elevenlabs"; account: ElevenLabsAccount; id: string }
  | { provider: "vapi"; account: VapiAccount; id: string }
  | { provider: "retell"; account: RetellAccount; id: string };

/** Reads an agent from a provider into a draft, then opens the new-agent wizard with it. The
 * credentials stay in this page's memory: they are sent with each call and never stored. */
export function AgentImportProviderPage() {
  const [provider, setProvider] = useState<ProviderId>("plivo-cx");
  const [connected, setConnected] = useState<Connection | null>(null);
  const change = () => setConnected(null);
  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-6">
      <div className="grid gap-1">
        <h1 className="text-h3-500">Import from a provider</h1>
        <p className="text-p-400 text-muted-foreground">
          Choose where the agent runs, and give Yaksh the credentials that can read it.
        </p>
      </div>
      {connected?.provider === "plivo-cx" ? (
        <PlivoCxAgents
          key={connected.id}
          account={connected.account}
          connection={connected.id}
          onChange={change}
        />
      ) : connected?.provider === "elevenlabs" ? (
        <ElevenLabsAgents
          key={connected.id}
          account={connected.account}
          connection={connected.id}
          onChange={change}
        />
      ) : connected?.provider === "vapi" ? (
        <VapiAssistants
          key={connected.id}
          account={connected.account}
          connection={connected.id}
          onChange={change}
        />
      ) : connected?.provider === "retell" ? (
        <RetellAgents
          key={connected.id}
          account={connected.account}
          connection={connected.id}
          onChange={change}
        />
      ) : (
        <Credentials provider={provider} onProvider={setProvider} onConnect={setConnected} />
      )}
    </div>
  );
}

function Credentials({
  provider,
  onProvider,
  onConnect,
}: {
  provider: ProviderId;
  onProvider: (provider: ProviderId) => void;
  onConnect: (connection: Connection) => void;
}) {
  const [authId, setAuthId] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [region, setRegion] = useState<ElevenLabsRegion>("global");
  const [vapiRegion, setVapiRegion] = useState<VapiRegion>("us");
  const [submitted, setSubmitted] = useState(false);
  const idProblem = /^[MS]A[A-Z0-9]{18}$/.test(authId.trim())
    ? null
    : "Enter the Auth ID: 20 capital letters and digits, starting with MA.";
  const tokenProblem = authToken.trim() ? null : "Enter the Auth token.";
  const keyProblem = apiKey.trim() ? null : "Enter the API key.";

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    const id = randomKey();
    if (provider === "plivo-cx" && !idProblem && !tokenProblem) {
      onConnect({
        provider,
        account: { auth_id: authId.trim(), auth_token: authToken.trim() },
        id,
      });
    }
    if (provider === "elevenlabs" && !keyProblem) {
      onConnect({ provider, account: { api_key: apiKey.trim(), region }, id });
    }
    if (provider === "vapi" && !keyProblem) {
      onConnect({ provider, account: { api_key: apiKey.trim(), region: vapiRegion }, id });
    }
    if (provider === "retell" && !keyProblem) {
      onConnect({ provider, account: { api_key: apiKey.trim() }, id });
    }
  };

  return (
    <form noValidate onSubmit={submit} className="flex flex-1 flex-col gap-6">
      <Panel className="px-5 py-5">
        <FieldGroup>
          <FieldSet>
            <FieldLegend variant="label">Provider</FieldLegend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PROVIDERS.map(({ id, name, logo }) => (
                <label
                  key={name}
                  aria-disabled={id === null}
                  className={cn(
                    "grid gap-2 rounded-md border px-3 py-2.5 transition-colors",
                    id === null
                      ? "opacity-60"
                      : "cursor-pointer hover:bg-hv1 has-checked:border-foreground has-checked:ring-1 has-checked:ring-foreground has-focus-visible:ring-2 has-focus-visible:ring-ring/50",
                  )}
                >
                  <input
                    type="radio"
                    name="provider"
                    className="sr-only"
                    disabled={id === null}
                    checked={provider === id}
                    onChange={() => id && onProvider(id)}
                  />
                  <span className="flex items-center justify-between gap-2">
                    <img src={logo} alt="" className="size-5 rounded-xs" />
                    {id === null && <Badge>Soon</Badge>}
                  </span>
                  <span className="truncate text-s-500">{name}</span>
                </label>
              ))}
            </div>
          </FieldSet>
          {provider === "plivo-cx" ? (
            <>
              <div className="grid gap-5 sm:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="auth_id">Auth ID</FieldLabel>
                  <Input
                    id="auth_id"
                    autoComplete="off"
                    spellCheck={false}
                    className="font-mono"
                    aria-invalid={submitted && Boolean(idProblem)}
                    value={authId}
                    onChange={(e) => setAuthId(e.target.value)}
                  />
                  {submitted && idProblem && <FieldError>{idProblem}</FieldError>}
                </Field>
                <Field>
                  <FieldLabel htmlFor="auth_token">Auth token</FieldLabel>
                  <Input
                    id="auth_token"
                    type="password"
                    autoComplete="off"
                    aria-invalid={submitted && Boolean(tokenProblem)}
                    value={authToken}
                    onChange={(e) => setAuthToken(e.target.value)}
                  />
                  {submitted && tokenProblem && <FieldError>{tokenProblem}</FieldError>}
                </Field>
              </div>
              <FieldDescription>
                From the overview page of the Plivo console. Use the main account: a subaccount
                cannot read agent flows. Yaksh uses them for this import and does not save them,
                except in the start request of a flow that calls out.
              </FieldDescription>
            </>
          ) : (
            <>
              <div
                className={cn(
                  "grid gap-5",
                  provider !== "retell" && "sm:grid-cols-[minmax(0,1fr)_12rem]",
                )}
              >
                <Field>
                  <FieldLabel htmlFor="api_key">API key</FieldLabel>
                  <Input
                    id="api_key"
                    type="password"
                    autoComplete="off"
                    aria-invalid={submitted && Boolean(keyProblem)}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                  />
                  {submitted && keyProblem && <FieldError>{keyProblem}</FieldError>}
                </Field>
                {provider === "vapi" && (
                  <RegionField
                    label="Organization"
                    items={VAPI_REGIONS}
                    value={vapiRegion}
                    onChange={setVapiRegion}
                  />
                )}
                {provider === "elevenlabs" && (
                  <RegionField
                    label="Workspace"
                    items={REGIONS}
                    value={region}
                    onChange={setRegion}
                  />
                )}
              </div>
              <FieldDescription>{KEY_HELP[provider]}</FieldDescription>
            </>
          )}
        </FieldGroup>
      </Panel>
      <StepFooter>
        <Button variant="ghost" nativeButton={false} render={<Link to="/agents/new" />}>
          <ArrowLeft />
          Back
        </Button>
        <Button type="submit" className="ml-auto">
          {provider === "plivo-cx"
            ? "Show agent flows"
            : provider === "vapi"
              ? "Show assistants"
              : "Show agents"}
        </Button>
      </StepFooter>
    </form>
  );
}

function PlivoCxAgents({
  account,
  connection,
  onChange,
}: {
  account: PlivoCxAccount;
  connection: string;
  onChange: () => void;
}) {
  const [name, setName] = useState("");
  const flows = usePlivoCxFlows(account, connection, name);
  const read = useImportPlivoCxFlow(account);
  return (
    <AgentChoice
      account={
        <>
          Plivo CX, Auth ID <code className="font-mono">{account.auth_id}</code>
        </>
      }
      words={{
        one: "agent flow",
        reading: "Reading the agent flows",
        shown: ["active call flow", "active call flows"],
        none: "This account has no active flows that take calls. A draft flow takes no calls: publish it in Plivo CX first.",
        noMatch: (search) => `No active call flow has "${search}" in its name.`,
        source: (title) => `the Plivo CX flow ${title}`,
      }}
      kind="plivo-cx"
      list={flows}
      rows={(flows.data?.pages ?? []).flatMap((page) =>
        page.items.map((flow) => ({
          id: flow.id,
          name: flow.name,
          detail: (flow.type && CALL_TYPES[flow.type]) ?? "Takes calls",
          when: flow.updated_at ? `Updated ${when(flow.updated_at)}` : null,
        })),
      )}
      read={read}
      onSearch={setName}
      onChange={onChange}
    />
  );
}

function ElevenLabsAgents({
  account,
  connection,
  onChange,
}: {
  account: ElevenLabsAccount;
  connection: string;
  onChange: () => void;
}) {
  const [name, setName] = useState("");
  const agents = useElevenLabsAgents(account, connection, name);
  const read = useImportElevenLabsAgent(account);
  const region = REGIONS.find(({ value }) => value === account.region)?.label;
  return (
    <AgentChoice
      account={<>ElevenLabs, {region}</>}
      words={{
        one: "agent",
        reading: "Reading the agents",
        shown: ["agent", "agents"],
        none: "This workspace has no agents.",
        noMatch: (search) => `No agent has "${search}" in its name.`,
        source: (title) => `the ElevenLabs agent ${title}`,
      }}
      kind="elevenlabs"
      list={agents}
      rows={(agents.data?.pages ?? []).flatMap((page) =>
        page.items.map((agent) => ({
          id: agent.id,
          name: agent.name,
          detail: null,
          when: agent.last_call_at ? `Last call ${when(agent.last_call_at)}` : "No calls yet",
        })),
      )}
      read={read}
      onSearch={setName}
      onChange={onChange}
    />
  );
}

function RegionField<Region extends string>({
  label,
  items,
  value,
  onChange,
}: {
  label: string;
  items: { value: Region; label: string }[];
  value: Region;
  onChange: (region: Region) => void;
}) {
  return (
    <Field>
      <FieldLabel htmlFor="region">{label}</FieldLabel>
      <Select
        items={items}
        value={value}
        onValueChange={(next) => {
          const found = items.find((item) => item.value === next);
          if (found) onChange(found.value);
        }}
      >
        <SelectTrigger id="region" className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            {items.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  );
}

function VapiAssistants({
  account,
  connection,
  onChange,
}: {
  account: VapiAccount;
  connection: string;
  onChange: () => void;
}) {
  const [name, setName] = useState("");
  const assistants = useVapiAssistants(account, connection, name);
  const read = useImportVapiAssistant(account);
  const region = VAPI_REGIONS.find(({ value }) => value === account.region)?.label;
  return (
    <AgentChoice
      account={<>Vapi, {region}</>}
      words={{
        one: "assistant",
        reading: "Reading the assistants",
        shown: ["assistant", "assistants"],
        none: "This organization has no assistants.",
        noMatch: (search) => `No assistant has "${search}" in its name.`,
        source: (title) => `the Vapi assistant ${title}`,
      }}
      kind="vapi"
      list={assistants}
      rows={(assistants.data?.pages ?? []).flatMap((page) =>
        page.items.map((assistant) => ({
          id: assistant.id,
          name: assistant.name,
          detail:
            assistant.numbers.length > 0
              ? `Answers ${assistant.numbers.map(phone).join(", ")}`
              : "No number: calls out",
          when: assistant.updated_at ? `Updated ${when(assistant.updated_at)}` : null,
        })),
      )}
      read={read}
      onSearch={setName}
      onChange={onChange}
    />
  );
}

function RetellAgents({
  account,
  connection,
  onChange,
}: {
  account: RetellAccount;
  connection: string;
  onChange: () => void;
}) {
  const [name, setName] = useState("");
  const agents = useRetellAgents(account, connection, name);
  const read = useImportRetellAgent(account);
  return (
    <AgentChoice
      account={<>Retell</>}
      words={{
        one: "agent",
        reading: "Reading the agents",
        shown: ["voice agent", "voice agents"],
        none: "This workspace has no voice agents.",
        noMatch: (search) => `No voice agent has "${search}" in its name.`,
        source: (title) => `the Retell agent ${title}`,
      }}
      kind="retell"
      list={agents}
      rows={(agents.data?.pages ?? []).flatMap((page) =>
        page.items.map((agent) => ({
          id: agent.id,
          name: agent.name,
          detail:
            agent.numbers.length > 0
              ? `Answers ${agent.numbers.map(phone).join(", ")}`
              : "No number: calls out",
          when: agent.updated_at ? `Updated ${when(agent.updated_at)}` : null,
        })),
      )}
      read={read}
      onSearch={setName}
      onChange={onChange}
    />
  );
}

interface Row {
  id: string;
  name: string;
  detail: string | null;
  /** The row's time with what it is, such as "Updated Oct 9, 12:28 PM". */
  when: string | null;
}

/** The parts of a provider's agent list that the choice shows. */
interface AgentList {
  isPending: boolean;
  error: Error | null;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => Promise<unknown>;
}

function AgentChoice({
  account,
  words,
  kind,
  list,
  rows,
  read,
  onSearch,
  onChange,
}: {
  account: ReactNode;
  words: {
    one: string;
    reading: string;
    shown: [string, string];
    none: string;
    noMatch: (search: string) => string;
    source: (title: string) => string;
  };
  kind: ImportedFrom["kind"];
  list: AgentList;
  rows: Row[];
  read: UseMutationResult<ProviderDraft, Error, string>;
  onSearch: (name: string) => void;
  onChange: () => void;
}) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [typed, setTyped] = useState("");
  const [searched, setSearched] = useState("");
  const [chosen, setChosen] = useState<Row | null>(null);
  const [number, setNumber] = useState<string | null>(null);
  const [briefDraftId, setBriefDraftId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  /** Once an agent is read, its panel comes into view: the list can push it below the fold. */
  const fills = useRef<HTMLElement>(null);
  const readAgent = read.data;
  useEffect(() => {
    if (!readAgent) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // After the next frame, when the panel has its final height: started at commit, the smooth
    // scroll stopped short of it.
    const frame = requestAnimationFrame(() =>
      fills.current?.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" }),
    );
    return () => cancelAnimationFrame(frame);
  }, [readAgent]);

  const choose = (row: Row) => {
    setChosen(row);
    setNumber(null);
    setProblem(null);
    read.mutate(row.id, {
      onSuccess: (draft) => {
        setNumber(draft.agent_numbers[0] ?? null);
        // The brief is drafted while the person checks the agent, so it is ready sooner.
        const id = randomKey();
        void client.prefetchQuery({
          queryKey: keys.briefDraft(id),
          queryFn: () => draftBrief(draft.config),
          staleTime: Infinity,
          retry: false,
        });
        setBriefDraftId(id);
      },
    });
  };

  const open = (draft: ProviderDraft) => {
    if (!chosen || briefDraftId === null) return;
    const outbound = draft.start_request
      ? withStartRequest(EMPTY_DRAFT.outbound, draft.start_request)
      : EMPTY_DRAFT.outbound;
    const started = startImportedDraft(
      {
        name: draft.name ?? "",
        external_id: draft.external_id,
        languages: draft.languages,
        config: draft.config,
        direction: draft.direction,
        // An inbound agent that no number reaches can still be tested over text.
        phone: Boolean(draft.start_request || number || !draft.endpoint),
        text: draft.endpoint !== null,
        agent_number: number ?? "",
        agent_speaks_first: draft.agent_speaks_first,
        outbound,
        endpoint: draft.endpoint ?? EMPTY_DRAFT.endpoint,
        record: draft.record_source !== null,
        record_source: draft.record_source ?? EMPTY_DRAFT.record_source,
      },
      { source: words.source(chosen.name), kind },
      briefDraftId,
    );
    if (started) navigate("/agents/new/details?step=1");
    else
      setProblem(
        `The browser blocks the storage that takes the ${words.one} to the next step. Allow site data for Yaksh, then try again.`,
      );
  };

  const search = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSearched(typed.trim());
    onSearch(typed.trim());
  };

  return (
    <div className="flex flex-1 flex-col gap-6">
      <Panel className="grid gap-4 px-5 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-p-400">{account}</span>
          <Button variant="ghost" size="sm" onClick={onChange}>
            Change
          </Button>
        </div>
        <form onSubmit={search} role="search" className="flex gap-2">
          <Input
            aria-label={`Search ${words.shown[1]} by name`}
            placeholder="Search by name"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          <Button type="submit" variant="outline" aria-label="Search">
            <Search />
          </Button>
        </form>

        {list.isPending ? (
          <p className="flex items-center gap-2 text-p-400 text-muted-foreground">
            <Spinner />
            {words.reading}
          </p>
        ) : list.error ? (
          <FieldError>{list.error.message}</FieldError>
        ) : rows.length === 0 && !list.hasNextPage ? (
          <p className="text-p-400 text-muted-foreground">
            {searched ? words.noMatch(searched) : words.none}
          </p>
        ) : (
          <fieldset className="grid gap-2">
            <legend className="sr-only">{words.one}</legend>
            {rows.map((row) => {
              const reading = read.isPending && chosen?.id === row.id;
              return (
                <label
                  key={row.id}
                  aria-busy={reading}
                  className="grid cursor-pointer grid-cols-[1fr_auto] items-center gap-x-4 rounded-md border px-4 py-3 transition-colors hover:bg-hv1 has-checked:border-foreground has-checked:ring-1 has-checked:ring-foreground has-focus-visible:ring-2 has-focus-visible:ring-ring/50"
                >
                  <input
                    type="radio"
                    name="agent"
                    className="sr-only"
                    checked={chosen?.id === row.id}
                    onChange={() => choose(row)}
                  />
                  <span className="grid min-w-0">
                    <span className="truncate text-p-500">{row.name}</span>
                    {row.detail && (
                      <span className="truncate text-s-400 text-muted-foreground">
                        {row.detail}
                      </span>
                    )}
                  </span>
                  {reading ? (
                    <span
                      className={cn(
                        "flex items-center gap-2 text-s-400 text-muted-foreground",
                        APPEAR,
                      )}
                    >
                      <Spinner />
                      Reading
                    </span>
                  ) : (
                    row.when && (
                      <span className="text-s-400 text-muted-foreground tabular-nums">
                        {row.when}
                      </span>
                    )
                  )}
                </label>
              );
            })}
            <div className="flex items-center justify-between gap-3 pt-1">
              <span className="text-s-400 text-muted-foreground tabular-nums">
                Showing {counted(rows.length, ...words.shown)}
              </span>
              {list.hasNextPage && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={list.isFetchingNextPage}
                  onClick={() => void list.fetchNextPage()}
                >
                  {list.isFetchingNextPage && <Spinner />}
                  Load more
                </Button>
              )}
            </div>
          </fieldset>
        )}
      </Panel>

      {chosen && (
        <Panel ref={fills} className={cn("grid scroll-mb-24 gap-3 px-5 py-5", APPEAR)}>
          <h2 className="text-p-500">What Yaksh fills in</h2>
          {read.isPending ? (
            <p className="flex items-center gap-2 text-p-400 text-muted-foreground">
              <Spinner />
              Reading {chosen.name}
            </p>
          ) : read.error ? (
            <FieldError>
              Yaksh could not read {chosen.name}: {read.error.message}
            </FieldError>
          ) : (
            read.data && (
              <Fills draft={read.data} source={words.one} number={number} onNumber={setNumber} />
            )
          )}
        </Panel>
      )}
      <p role="status" className="sr-only">
        {read.data && chosen ? `${chosen.name} is read. Import is ready.` : ""}
      </p>

      <StepFooter>
        <Button variant="ghost" onClick={onChange}>
          <ArrowLeft />
          Back
        </Button>
        {problem && <FieldError className="ml-auto">{problem}</FieldError>}
        <Button
          className="ml-auto"
          disabled={!read.data || read.isPending}
          onClick={() => read.data && open(read.data)}
        >
          {read.isPending && <Spinner />}
          {read.isPending ? `Reading the ${words.one}` : "Import"}
        </Button>
      </StepFooter>
    </div>
  );
}

/** What the chosen agent fills, one fact a row. */
function Fills({
  draft,
  source,
  number,
  onNumber,
}: {
  draft: ProviderDraft;
  source: string;
  number: string | null;
  onNumber: (number: string) => void;
}) {
  const numbers = draft.agent_numbers;
  const request = draft.start_request;
  return (
    <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-p-400">
      <Fact term="Name">{draft.name ?? `Not in the ${source}`}</Fact>
      <Fact term="Languages">
        <span className="grid gap-0.5 whitespace-normal">
          <span>
            {draft.languages.length > 0
              ? languageNames(draft.languages)
              : "Choose them in the next step"}
          </span>
          {draft.language_note && (
            <span className="text-s-400 break-words text-muted-foreground">
              {draft.language_note}
            </span>
          )}
        </span>
      </Fact>
      {request ? (
        <>
          <Fact term="Calls">The agent calls Yaksh</Fact>
          <Fact term="Number field">
            {request.number_field ? (
              <code className="font-mono">{request.number_field}</code>
            ) : (
              "Choose it in the next step"
            )}
          </Fact>
          {scenarioFields(request).length > 0 && (
            <Fact term="Scenario data">
              <span className="font-mono whitespace-normal">
                {scenarioFields(request).join(", ")}
              </span>
            </Fact>
          )}
        </>
      ) : (
        <Fact term="Number">
          {numbers.length === 0 ? (
            <span className="grid gap-0.5 whitespace-normal">
              <span>Enter it in the next step</span>
              {draft.number_note && (
                <span className="text-s-400 break-words text-muted-foreground">
                  {draft.number_note}
                </span>
              )}
            </span>
          ) : numbers.length === 1 ? (
            <span className="font-mono tabular-nums">{phone(numbers[0])}</span>
          ) : (
            <fieldset className="grid gap-1.5">
              <legend className="sr-only">The number Yaksh calls</legend>
              {numbers.map((candidate) => (
                <label key={candidate} className="flex cursor-pointer items-center gap-2">
                  <input
                    type="radio"
                    name="agent_number"
                    checked={number === candidate}
                    onChange={() => onNumber(candidate)}
                  />
                  <span className="font-mono tabular-nums">{phone(candidate)}</span>
                </label>
              ))}
            </fieldset>
          )}
        </Fact>
      )}
      {draft.endpoint && (
        <Fact term="Text">
          <span className="font-mono" title={draft.endpoint.url}>
            {draft.endpoint.url}
          </span>
        </Fact>
      )}
      {draft.record_source && (
        <Fact term="Agent record">
          <span className="font-mono" title={draft.record_source.url}>
            {draft.record_source.url}
          </span>
        </Fact>
      )}
      <Fact term="Config">The {source}</Fact>
      <Fact term="Brief">Drafted from the {source}</Fact>
    </dl>
  );
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="min-w-0 truncate">{children}</dd>
    </>
  );
}
