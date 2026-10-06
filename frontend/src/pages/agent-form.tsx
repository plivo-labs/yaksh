import { type ReactNode, type SubmitEvent, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { Panel, PanelHeader } from "@/components/panel";
import { Segmented } from "@/components/segmented";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldContent,
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
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useCloseGuard } from "@/hooks/use-close-guard";
import { useDraftKnowledgeBase } from "@/hooks/use-knowledge-base";
import { revealErrors } from "@/lib/forms";
import { APPEAR } from "@/lib/motion";
import { useDeleteAgent, useSaveAgent } from "@/lib/queries";
import {
  EMPTY_OUTBOUND,
  isPhoneNumber,
  normalizeNumber,
  type OutboundDraft,
  outboundProblems,
  toOutbound,
  toOutboundDraft,
} from "@/lib/outbound";
import {
  type Agent,
  type AgentInput,
  type Direction,
  LANGUAGE_ITEMS,
  type Language,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { ConfigField, MAX_CONFIG_CHARS } from "@/pages/agent-config-field";
import { KnowledgeBasePanel } from "@/pages/agent-knowledge-base";
import { OutboundFields } from "@/pages/agent-outbound-fields";

interface Draft {
  name: string;
  external_id: string;
  direction: Direction;
  agent_number: string;
  outbound: OutboundDraft;
  agent_speaks_first: boolean;
  language: Language;
  brief: string;
  config: string;
}

const EMPTY: Draft = {
  name: "",
  external_id: "",
  direction: "inbound",
  agent_number: "",
  outbound: EMPTY_OUTBOUND,
  agent_speaks_first: true,
  language: "en",
  brief: "",
  config: "",
};

function toDraft(agent: Agent): Draft {
  return {
    name: agent.name,
    external_id: agent.external_id ?? "",
    direction: agent.direction,
    agent_number: agent.agent_number ?? "",
    outbound: agent.outbound ? toOutboundDraft(agent.outbound) : EMPTY_OUTBOUND,
    agent_speaks_first: agent.agent_speaks_first,
    language: agent.language,
    brief: agent.brief ?? "",
    config: agent.config ?? "",
  };
}

const REACH_OPTIONS: { value: Direction; label: string }[] = [
  { value: "inbound", label: "Yaksha" },
  { value: "outbound", label: "The agent" },
];

const REQUEST_NOTE =
  "Yaksha sends this POST request to make the agent call one of Yaksha's numbers.";

const REACH_HINTS: Record<Direction, string> = {
  inbound: "Yaksha dials the agent's phone number and plays the caller.",
  outbound: "Yaksha asks the agent to call, then answers as the caller.",
};

function toInput(draft: Draft): AgentInput {
  const outbound = draft.direction === "outbound";
  return {
    name: draft.name.trim(),
    external_id: draft.external_id.trim() || null,
    direction: draft.direction,
    transport: "phone",
    agent_number: outbound ? null : normalizeNumber(draft.agent_number),
    outbound: outbound ? toOutbound(draft.outbound) : null,
    agent_speaks_first: draft.agent_speaks_first,
    language: draft.language,
    brief: draft.brief.trim() || null,
    config: draft.config.trim() ? draft.config : null,
  };
}

/** An agent being added or edited: the draft, what it still needs, and a check that shows the
 * problems and moves focus to the first one. */
function useAgentDraft(agent?: Agent) {
  const [initial] = useState<Draft>(() => (agent ? toDraft(agent) : EMPTY));
  const [draft, setDraft] = useState(initial);
  const [submitted, setSubmitted] = useState(false);
  const [switched, setSwitched] = useState(false);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    if (key === "direction") setSwitched(true);
    setDraft((current) => ({ ...current, [key]: value }));
  };
  const outbound = draft.direction === "outbound";
  const needs = {
    name: draft.name.trim() === "",
    reach: outbound
      ? Object.keys(outboundProblems(draft.outbound)).length > 0
      : !isPhoneNumber(draft.agent_number),
    config: draft.config.length > MAX_CONFIG_CHARS,
  };
  const ready = !needs.name && !needs.reach && !needs.config;
  const check = (element: HTMLFormElement) =>
    revealErrors(element, () => setSubmitted(true), ready);
  /** Who calls changed, so fields that swap with it may fade in; the first render stays still. */
  const swap = switched ? APPEAR : undefined;
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);
  return { draft, set, submitted, outbound, needs, check, swap, dirty };
}

type AgentDraft = ReturnType<typeof useAgentDraft>;

function BasicsFields({ form }: { form: AgentDraft }) {
  const { draft, set, submitted, needs } = form;
  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor="name">Name</FieldLabel>
        <Input
          id="name"
          required
          placeholder="Front desk"
          aria-invalid={submitted && needs.name}
          aria-describedby={submitted && needs.name ? "name-error" : undefined}
          value={draft.name}
          onChange={(e) => set("name", e.target.value)}
        />
        {submitted && needs.name && <FieldError id="name-error">Enter a name.</FieldError>}
      </Field>
      <div className="grid gap-7 @md/field-group:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="language">Language</FieldLabel>
          <Select
            items={LANGUAGE_ITEMS}
            value={draft.language}
            onValueChange={(value) => value && set("language", value as Language)}
          >
            <SelectTrigger id="language" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {LANGUAGE_ITEMS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel htmlFor="external_id">External id</FieldLabel>
          <Input
            id="external_id"
            placeholder="Optional"
            value={draft.external_id}
            onChange={(e) => set("external_id", e.target.value)}
          />
          <FieldDescription>Your own id for this agent, for the API.</FieldDescription>
        </Field>
      </div>
    </FieldGroup>
  );
}

function ReachFields({ form }: { form: AgentDraft }) {
  const { draft, set, submitted, outbound, needs, swap } = form;
  const numberProblem = (submitted || draft.agent_number !== "") && needs.reach;
  return (
    <FieldGroup>
      <div className="grid gap-2">
        <Segmented
          label="Who calls"
          value={draft.direction}
          options={REACH_OPTIONS}
          onChange={(value) => set("direction", value)}
        />
        <p className="text-p-400 text-muted-foreground">{REACH_HINTS[draft.direction]}</p>
      </div>
      {!outbound && (
        <Field className={swap}>
          <FieldLabel htmlFor="agent_number">Phone number</FieldLabel>
          <Input
            id="agent_number"
            type="tel"
            inputMode="tel"
            required
            placeholder="+1 415 555 0100"
            aria-invalid={numberProblem}
            aria-describedby={numberProblem ? "agent_number-error" : undefined}
            value={draft.agent_number}
            onChange={(e) => set("agent_number", e.target.value)}
          />
          {numberProblem && (
            <FieldError id="agent_number-error">
              Use the international format, like +14155550100.
            </FieldError>
          )}
        </Field>
      )}
      <Field orientation="horizontal" className="rounded-md border bg-muted/40 px-3.5 py-3">
        <FieldContent>
          <FieldLabel htmlFor="agent_speaks_first">Agent speaks first</FieldLabel>
          {outbound && (
            <FieldDescription className={swap}>
              When off, the caller speaks first, from its goal.
            </FieldDescription>
          )}
        </FieldContent>
        <Switch
          id="agent_speaks_first"
          checked={draft.agent_speaks_first}
          onCheckedChange={(checked) => set("agent_speaks_first", checked)}
        />
      </Field>
    </FieldGroup>
  );
}

function RequestFields({ form }: { form: AgentDraft }) {
  const { draft, set, submitted } = form;
  return (
    <OutboundFields
      draft={draft.outbound}
      onChange={(next) => set("outbound", next)}
      submitted={submitted}
    />
  );
}

function ContextFields({ form }: { form: AgentDraft }) {
  const { draft, set } = form;
  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor="brief">Brief</FieldLabel>
        <Textarea
          id="brief"
          rows={4}
          maxLength={10_000}
          placeholder="What this agent is supposed to do, in your words."
          value={draft.brief}
          onChange={(e) => set("brief", e.target.value)}
        />
      </Field>
      <ConfigField value={draft.config} onChange={(value) => set("config", value)} />
    </FieldGroup>
  );
}

const CONTEXT_NOTE =
  "Optional. Yaksha reads these and the knowledge base to write test scenarios. The judges read the config to check that the agent kept to its instructions, and the knowledge base to find statements it contradicts.";

function Section({
  title,
  description,
  className,
  children,
}: {
  title: string;
  description?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Panel className={className}>
      <PanelHeader title={title} />
      <div className="grid gap-5 px-5 py-5">
        {description && <p className="text-p-400 text-muted-foreground">{description}</p>}
        {children}
      </div>
    </Panel>
  );
}

export function NewAgentPage() {
  const navigate = useNavigate();
  const form = useAgentDraft();
  const save = useSaveAgent();
  const knowledgeBase = useDraftKnowledgeBase(save.isPending);
  const uploading = knowledgeBase.progress !== null;

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.check(event.currentTarget) || uploading || save.isPending) return;
    const entries = knowledgeBase.documents.map(({ document_id, name }) => ({ document_id, name }));
    save.mutate(
      { ...toInput(form.draft), knowledge_base: entries },
      { onSuccess: (agent) => navigate(`/agents/${agent.id}`, { replace: true }) },
    );
  };

  return (
    <div className="grid gap-6">
      <div className="grid gap-1">
        <h1 className="text-h3-500">New agent</h1>
        <p className="text-p-400 text-muted-foreground">
          Tell Yaksha how to reach the agent and what it does.
        </p>
      </div>
      <form noValidate onSubmit={submit} className="grid gap-6">
        <div className="grid gap-6 lg:grid-cols-2">
          <Section title="Agent">
            <BasicsFields form={form} />
          </Section>
          <Section title="Calls">
            <ReachFields form={form} />
          </Section>
          {form.outbound && (
            <Section
              title="Start request"
              description={REQUEST_NOTE}
              className={cn("lg:col-span-2", form.swap)}
            >
              <RequestFields form={form} />
            </Section>
          )}
          <Section title="What it does" description={CONTEXT_NOTE}>
            <ContextFields form={form} />
          </Section>
          <KnowledgeBasePanel source={knowledgeBase} />
        </div>
        <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
          {save.error && <FieldError className="mr-auto">{save.error.message}</FieldError>}
          {uploading && (
            <FieldDescription className={`mr-auto ${APPEAR}`}>
              Wait for the documents to finish uploading.
            </FieldDescription>
          )}
          <Button variant="ghost" nativeButton={false} render={<Link to="/agents" />}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending || uploading}>
            {save.isPending && <Spinner />}
            Add agent
          </Button>
        </div>
      </form>
    </div>
  );
}

/** Edits an agent. Its knowledge base is edited in its own panel, which saves at once. */
/** The agent's settings in a sheet. It asks before it throws away unsaved changes, and calls
 * `onClosed` once it has closed. */
export function EditAgentSheet({ agent, onClosed }: { agent: Agent; onClosed: () => void }) {
  const form = useAgentDraft(agent);
  const guard = useCloseGuard(form.dirty);
  return (
    <Sheet
      open={guard.open}
      onOpenChange={(next) => !next && guard.requestClose()}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <SheetContent size="lg" className="overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Edit {agent.name}</SheetTitle>
        </SheetHeader>
        <div className="px-6 pb-6">
          <AgentForm
            agent={agent}
            form={form}
            onSaved={() => {
              guard.close();
              toast.success("Settings saved");
            }}
            cancel={
              <Button type="button" variant="ghost" onClick={guard.requestClose}>
                Cancel
              </Button>
            }
          />
        </div>
      </SheetContent>
      <DiscardConfirm subject="agent" {...guard.discard} />
    </Sheet>
  );
}

function AgentForm({
  agent,
  form,
  onSaved,
  cancel,
}: {
  agent: Agent;
  form: AgentDraft;
  onSaved: (agent: Agent) => void;
  cancel: ReactNode;
}) {
  const navigate = useNavigate();
  const save = useSaveAgent(agent.id);
  const remove = useDeleteAgent();

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.check(event.currentTarget)) return;
    save.mutate(toInput(form.draft), { onSuccess: onSaved });
  };

  return (
    <form noValidate onSubmit={submit} className="grid gap-10">
      <FieldSet>
        <FieldLegend>Agent</FieldLegend>
        <BasicsFields form={form} />
      </FieldSet>
      <FieldSet>
        <FieldLegend>Calls</FieldLegend>
        <ReachFields form={form} />
      </FieldSet>
      {form.outbound && (
        <FieldSet className={form.swap}>
          <FieldLegend>Start request</FieldLegend>
          <FieldDescription>{REQUEST_NOTE}</FieldDescription>
          <RequestFields form={form} />
        </FieldSet>
      )}
      <FieldSet>
        <FieldLegend>What it does</FieldLegend>
        <FieldDescription>{CONTEXT_NOTE}</FieldDescription>
        <ContextFields form={form} />
      </FieldSet>

      {(save.error || remove.error) && (
        <FieldError>{(save.error ?? remove.error)?.message}</FieldError>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2">
        <DeleteConfirm
          name={form.draft.name}
          description="Past conversations keep their copy of its configuration. An agent with an active conversation cannot be deleted."
          pending={remove.isPending}
          onDelete={(close) =>
            remove.mutate(agent.id, {
              onSuccess: () => {
                toast.success(`Deleted ${form.draft.name}`);
                navigate("/agents", { replace: true });
              },
              onSettled: close,
            })
          }
        />
        {cancel}
        <Button type="submit" disabled={save.isPending}>
          {save.isPending && <Spinner />}
          Save changes
        </Button>
      </div>
    </form>
  );
}
