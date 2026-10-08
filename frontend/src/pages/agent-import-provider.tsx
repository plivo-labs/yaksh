import { useQueryClient } from "@tanstack/react-query";
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
import { Spinner } from "@/components/ui/spinner";
import { EMPTY_DRAFT } from "@/lib/agent-draft";
import { counted, phone, when } from "@/lib/format";
import { APPEAR } from "@/lib/motion";
import { startImportedDraft } from "@/lib/new-agent-draft";
import { scenarioFields, withStartRequest } from "@/lib/outbound";
import { draftBrief, keys, useImportPlivoCxFlow, usePlivoCxFlows } from "@/lib/queries";
import { randomKey } from "@/lib/random-key";
import type { PlivoCxAccount, PlivoCxDraft, PlivoCxFlow } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Each provider's own icon, as its website serves it. */
const PROVIDERS = [
  { name: "Plivo CX", logo: plivoCxLogo, ready: true },
  { name: "Vapi", logo: vapiLogo, ready: false },
  { name: "Retell", logo: retellLogo, ready: false },
  { name: "ElevenLabs", logo: elevenLabsLogo, ready: false },
];

/** How each kind of flow that Yaksha lists takes calls; the server leaves out the others. */
const CALL_TYPES: Record<string, string> = {
  incoming_call: "Answers calls",
  api_request: "Calls out on a request",
  omni: "Several channels",
};

/** Reads an agent from a provider into a draft, then opens the new-agent wizard with it. The
 * credentials stay in this page's memory: they are sent with each call and never stored. */
export function AgentImportProviderPage() {
  const [connected, setConnected] = useState<{ account: PlivoCxAccount; id: string } | null>(null);
  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-6">
      <div className="grid gap-1">
        <h1 className="text-h3-500">Import from a provider</h1>
        <p className="text-p-400 text-muted-foreground">
          Choose where the agent runs, and give Yaksha the credentials that can read it.
        </p>
      </div>
      {connected ? (
        <FlowChoice
          account={connected.account}
          connection={connected.id}
          onChange={() => setConnected(null)}
        />
      ) : (
        <Credentials onConnect={(account) => setConnected({ account, id: randomKey() })} />
      )}
    </div>
  );
}

function Credentials({ onConnect }: { onConnect: (account: PlivoCxAccount) => void }) {
  const [authId, setAuthId] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const idProblem = /^[MS]A[A-Z0-9]{18}$/.test(authId.trim())
    ? null
    : "Enter the Auth ID: 20 capital letters and digits, starting with MA.";
  const tokenProblem = authToken.trim() ? null : "Enter the Auth token.";

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (!idProblem && !tokenProblem) {
      onConnect({ auth_id: authId.trim(), auth_token: authToken.trim() });
    }
  };

  return (
    <form noValidate onSubmit={submit} className="flex flex-1 flex-col gap-6">
      <Panel className="px-5 py-5">
        <FieldGroup>
          <FieldSet>
            <FieldLegend variant="label">Provider</FieldLegend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PROVIDERS.map(({ name, logo, ready }) => (
                <div
                  key={name}
                  aria-disabled={!ready}
                  className={cn(
                    "grid gap-2 rounded-md border px-3 py-2.5",
                    ready ? "border-foreground ring-1 ring-foreground" : "opacity-60",
                  )}
                >
                  <span className="flex items-center justify-between gap-2">
                    <img src={logo} alt="" className="size-5 rounded-xs" />
                    {!ready && <Badge>Soon</Badge>}
                  </span>
                  <span className="truncate text-s-500">{name}</span>
                </div>
              ))}
            </div>
          </FieldSet>
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
            From the overview page of the Plivo console. Use the main account: a subaccount cannot
            read agent flows. Yaksha uses them for this import and does not save them, except in the
            start request of a flow that calls out.
          </FieldDescription>
        </FieldGroup>
      </Panel>
      <StepFooter>
        <Button variant="ghost" nativeButton={false} render={<Link to="/agents/new" />}>
          <ArrowLeft />
          Back
        </Button>
        <Button type="submit" className="ml-auto">
          Show agent flows
        </Button>
      </StepFooter>
    </form>
  );
}

function FlowChoice({
  account,
  connection,
  onChange,
}: {
  account: PlivoCxAccount;
  connection: string;
  onChange: () => void;
}) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [typed, setTyped] = useState("");
  const [name, setName] = useState("");
  const flows = usePlivoCxFlows(account, connection, name);
  const read = useImportPlivoCxFlow();
  const [chosen, setChosen] = useState<PlivoCxFlow | null>(null);
  const [number, setNumber] = useState<string | null>(null);
  const [briefDraftId, setBriefDraftId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const listed = flows.data?.pages.flatMap((page) => page.items) ?? [];

  /** Once a flow is read, its panel comes into view: the list can push it below the fold. */
  const fills = useRef<HTMLElement>(null);
  const readFlow = read.data;
  useEffect(() => {
    if (!readFlow) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // After the next frame, when the panel has its final height: started at commit, the smooth
    // scroll stopped short of it.
    const frame = requestAnimationFrame(() =>
      fills.current?.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" }),
    );
    return () => cancelAnimationFrame(frame);
  }, [readFlow]);

  const choose = (flow: PlivoCxFlow) => {
    setChosen(flow);
    setNumber(null);
    setProblem(null);
    read.mutate(
      { account, flowId: flow.id },
      {
        onSuccess: (draft) => {
          setNumber(draft.agent_numbers[0] ?? null);
          // The brief is drafted while the person checks the flow, so it is ready sooner.
          const id = randomKey();
          void client.prefetchQuery({
            queryKey: keys.briefDraft(id),
            queryFn: () => draftBrief(draft.config),
            staleTime: Infinity,
            retry: false,
          });
          setBriefDraftId(id);
        },
      },
    );
  };

  const open = (draft: PlivoCxDraft) => {
    if (!chosen || briefDraftId === null) return;
    const outbound = draft.start_request
      ? withStartRequest(EMPTY_DRAFT.outbound, draft.start_request)
      : EMPTY_DRAFT.outbound;
    const started = startImportedDraft(
      {
        name: draft.name ?? "",
        external_id: draft.external_id,
        language: draft.language,
        config: draft.config,
        direction: draft.direction,
        agent_number: number ?? "",
        outbound,
      },
      { source: `the Plivo CX flow ${chosen.name}`, kind: "plivo-cx" },
      briefDraftId,
    );
    if (started) navigate("/agents/new/details?step=1");
    else
      setProblem(
        "The browser blocks the storage that takes the flow to the next step. Allow site data for Yaksha, then try again.",
      );
  };

  const search = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setName(typed.trim());
  };

  return (
    <div className="flex flex-1 flex-col gap-6">
      <Panel className="grid gap-4 px-5 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-p-400">
            Plivo CX, Auth ID <code className="font-mono">{account.auth_id}</code>
          </span>
          <Button variant="ghost" size="sm" onClick={onChange}>
            Change
          </Button>
        </div>
        <form onSubmit={search} role="search" className="flex gap-2">
          <Input
            aria-label="Search agent flows by name"
            placeholder="Search by name"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          <Button type="submit" variant="outline" aria-label="Search">
            <Search />
          </Button>
        </form>

        {flows.isPending ? (
          <p className="flex items-center gap-2 text-p-400 text-muted-foreground">
            <Spinner />
            Reading the agent flows
          </p>
        ) : flows.error ? (
          <FieldError>{flows.error.message}</FieldError>
        ) : listed.length === 0 && !flows.hasNextPage ? (
          <p className="text-p-400 text-muted-foreground">
            {name
              ? `No active call flow has "${name}" in its name.`
              : "This account has no active flows that take calls. A draft flow takes no calls: publish it in Plivo CX first."}
          </p>
        ) : (
          <fieldset className="grid gap-2">
            <legend className="sr-only">Agent flow</legend>
            {listed.map((flow) => {
              const reading = read.isPending && chosen?.id === flow.id;
              return (
                <label
                  key={flow.id}
                  aria-busy={reading}
                  className="grid cursor-pointer grid-cols-[1fr_auto] items-center gap-x-4 rounded-md border px-4 py-3 transition-colors hover:bg-hv1 has-checked:border-foreground has-checked:ring-1 has-checked:ring-foreground has-focus-visible:ring-2 has-focus-visible:ring-ring/50"
                >
                  <input
                    type="radio"
                    name="flow"
                    className="sr-only"
                    checked={chosen?.id === flow.id}
                    onChange={() => choose(flow)}
                  />
                  <span className="grid min-w-0">
                    <span className="truncate text-p-500">{flow.name}</span>
                    <span className="truncate text-s-400 text-muted-foreground">
                      {(flow.type && CALL_TYPES[flow.type]) ?? "Takes calls"}
                    </span>
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
                    flow.updated_at && (
                      <span className="text-s-400 text-muted-foreground tabular-nums">
                        {when(flow.updated_at)}
                      </span>
                    )
                  )}
                </label>
              );
            })}
            <div className="flex items-center justify-between gap-3 pt-1">
              <span className="text-s-400 text-muted-foreground tabular-nums">
                Showing {counted(listed.length, "active call flow", "active call flows")}
              </span>
              {flows.hasNextPage && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={flows.isFetchingNextPage}
                  onClick={() => void flows.fetchNextPage()}
                >
                  {flows.isFetchingNextPage && <Spinner />}
                  Load more
                </Button>
              )}
            </div>
          </fieldset>
        )}
      </Panel>

      {chosen && (
        <Panel ref={fills} className={cn("grid scroll-mb-24 gap-3 px-5 py-5", APPEAR)}>
          <h2 className="text-p-500">What Yaksha fills in</h2>
          {read.isPending ? (
            <p className="flex items-center gap-2 text-p-400 text-muted-foreground">
              <Spinner />
              Reading {chosen.name}
            </p>
          ) : read.error ? (
            <FieldError>
              Yaksha could not read {chosen.name}: {read.error.message}
            </FieldError>
          ) : (
            read.data && <Fills draft={read.data} number={number} onNumber={setNumber} />
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
          {read.isPending ? "Reading the flow" : "Import"}
        </Button>
      </StepFooter>
    </div>
  );
}

/** What the chosen flow fills, one fact a row. */
function Fills({
  draft,
  number,
  onNumber,
}: {
  draft: PlivoCxDraft;
  number: string | null;
  onNumber: (number: string) => void;
}) {
  const numbers = draft.agent_numbers;
  const request = draft.start_request;
  return (
    <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-p-400">
      <Fact term="Name">{draft.name ?? "Not in the flow"}</Fact>
      {request ? (
        <>
          <Fact term="Calls">The agent calls Yaksha</Fact>
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
            "Enter it in the next step"
          ) : numbers.length === 1 ? (
            <span className="font-mono tabular-nums">{phone(numbers[0])}</span>
          ) : (
            <fieldset className="grid gap-1.5">
              <legend className="sr-only">The number Yaksha calls</legend>
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
      <Fact term="Config">The flow</Fact>
      <Fact term="Brief">Drafted from the flow</Fact>
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
