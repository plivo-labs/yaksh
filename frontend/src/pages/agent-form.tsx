import { type ReactNode, type SubmitEvent, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { DeleteConfirm } from "@/components/confirm-dialogs";
import { Panel, PanelHeader } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { Field, FieldContent, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
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
import { type Agent, type AgentInput, LANGUAGE_ITEMS, type Language } from "@/lib/types";

interface Draft {
  name: string;
  external_id: string;
  agent_number: string;
  agent_speaks_first: boolean;
  language: Language;
  brief: string;
}

const EMPTY: Draft = {
  name: "",
  external_id: "",
  agent_number: "",
  agent_speaks_first: true,
  language: "en",
  brief: "",
};

function toDraft(agent: Agent): Draft {
  return {
    name: agent.name,
    external_id: agent.external_id ?? "",
    agent_number: agent.agent_number,
    agent_speaks_first: agent.agent_speaks_first,
    language: agent.language,
    brief: agent.brief ?? "",
  };
}

const E164 = /^\+[1-9]\d{6,14}$/;

function normalizeNumber(typed: string): string {
  return typed.replaceAll(/[\s-]/g, "");
}

function toInput(draft: Draft, agent?: Agent): AgentInput {
  return {
    name: draft.name.trim(),
    external_id: draft.external_id.trim() || null,
    direction: agent?.direction ?? "inbound",
    transport: "phone",
    agent_number: normalizeNumber(draft.agent_number),
    agent_speaks_first: draft.agent_speaks_first,
    language: draft.language,
    brief: draft.brief.trim() || null,
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
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const numberOk = E164.test(normalizeNumber(draft.agent_number));

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    if (!numberOk) return;
    save.mutate(toInput(draft, agent), { onSuccess: onSaved });
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
          <FieldLabel htmlFor="agent_number">Phone number</FieldLabel>
          <Input
            id="agent_number"
            required
            type="tel"
            inputMode="tel"
            placeholder="+1 415 555 0100"
            aria-invalid={draft.agent_number !== "" && !numberOk}
            value={draft.agent_number}
            onChange={(e) => set("agent_number", e.target.value)}
          />
          {draft.agent_number !== "" && !numberOk && (
            <FieldError>Use the international format, like +14155550100.</FieldError>
          )}
        </Field>

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
            placeholder="What this agent is supposed to do, in your words."
            value={draft.brief}
            onChange={(e) => set("brief", e.target.value)}
          />
        </Field>

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
