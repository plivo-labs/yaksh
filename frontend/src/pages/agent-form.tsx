import { type ReactNode, type SubmitEvent, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { DeleteConfirm } from "@/components/confirm-dialogs";
import { Panel, PanelHeader } from "@/components/panel";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
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
import { OutboundFields } from "@/pages/agent-outbound-fields";
import { ConfigField, MAX_CONFIG_CHARS } from "@/pages/agent-config-field";

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

const DIRECTION_ITEMS: { value: Direction; label: string }[] = [
  { value: "inbound", label: "Inbound: Truman calls the agent" },
  { value: "outbound", label: "Outbound: the agent calls Truman" },
];

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

export function NewAgentPage() {
  const navigate = useNavigate();
  return (
    <div className="mx-auto grid max-w-2xl gap-6">
      <h1 className="text-2xl font-semibold tracking-[-0.015em]">New agent</h1>
      <Panel>
        <PanelHeader title="Settings" />
        <div className="px-5 py-5">
          <AgentForm
            onSaved={(agent) => navigate(`/agents/${agent.id}`)}
            cancel={
              <Button variant="ghost" nativeButton={false} render={<Link to="/agents" />}>
                Cancel
              </Button>
            }
          />
        </div>
      </Panel>
    </div>
  );
}

/** Creates an agent, or edits one when `agent` is given. */
export function AgentForm({
  agent,
  onSaved,
  cancel,
}: {
  agent?: Agent;
  onSaved: (agent: Agent) => void;
  cancel: ReactNode;
}) {
  const id = agent?.id;
  const navigate = useNavigate();
  const save = useSaveAgent(id);
  const remove = useDeleteAgent();
  const [draft, setDraft] = useState<Draft>(() => (agent ? toDraft(agent) : EMPTY));
  const [submitted, setSubmitted] = useState(false);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const outbound = draft.direction === "outbound";
  const numberOk = isPhoneNumber(draft.agent_number);
  const ready =
    (outbound ? Object.keys(outboundProblems(draft.outbound)).length === 0 : numberOk) &&
    draft.config.length <= MAX_CONFIG_CHARS;

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!ready) return;
    save.mutate(toInput(draft), { onSuccess: onSaved });
  };

  return (
    <form onSubmit={submit}>
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="name">Name</FieldLabel>
          <Input
            id="name"
            required
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </Field>

        <Field>
          <FieldLabel htmlFor="direction">Direction</FieldLabel>
          <Select
            items={DIRECTION_ITEMS}
            value={draft.direction}
            onValueChange={(value) => value && set("direction", value as Direction)}
          >
            <SelectTrigger id="direction" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {DIRECTION_ITEMS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>

        {outbound ? (
          <OutboundFields
            draft={draft.outbound}
            onChange={(next) => set("outbound", next)}
            submitted={submitted}
          />
        ) : (
          <Field>
            <FieldLabel htmlFor="agent_number">Phone number</FieldLabel>
            <Input
              id="agent_number"
              type="tel"
              inputMode="tel"
              placeholder="+1 415 555 0100"
              aria-invalid={draft.agent_number !== "" && !numberOk}
              value={draft.agent_number}
              onChange={(e) => set("agent_number", e.target.value)}
            />
            {(submitted || draft.agent_number !== "") && !numberOk && (
              <FieldError>Use the international format, like +14155550100.</FieldError>
            )}
          </Field>
        )}

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

        <Field orientation="horizontal" className="rounded-md border bg-muted/40 px-3.5 py-3">
          <FieldContent>
            <FieldLabel htmlFor="agent_speaks_first">Agent speaks first</FieldLabel>
            {outbound && (
              <FieldDescription>
                When off, the caller says a short hello on pickup.
              </FieldDescription>
            )}
          </FieldContent>
          <Switch
            id="agent_speaks_first"
            checked={draft.agent_speaks_first}
            onCheckedChange={(checked) => set("agent_speaks_first", checked)}
          />
        </Field>

        <Field>
          <FieldLabel htmlFor="external_id">External id</FieldLabel>
          <Input
            id="external_id"
            placeholder="Your own identifier for this agent"
            value={draft.external_id}
            onChange={(e) => set("external_id", e.target.value)}
          />
        </Field>

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

        {(save.error || remove.error) && (
          <FieldError>{(save.error ?? remove.error)?.message}</FieldError>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending && <Spinner />}
            {id ? "Save changes" : "Add agent"}
          </Button>
          {cancel}
          {id && (
            <div className="ml-auto">
              <DeleteConfirm
                name={draft.name}
                description="Past conversations keep their copy of its configuration. An agent with an active conversation cannot be deleted."
                pending={remove.isPending}
                onDelete={(close) =>
                  remove.mutate(id, {
                    onSuccess: () => {
                      toast.success(`Deleted ${draft.name}`);
                      navigate("/agents");
                    },
                    onSettled: close,
                  })
                }
              />
            </div>
          )}
        </div>
      </FieldGroup>
    </form>
  );
}
