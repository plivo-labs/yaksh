import { type SubmitEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAgent, useDeleteAgent, useSaveAgent } from "@/lib/queries";
import type { Agent, AgentInput } from "@/lib/types";
import { AgentScenarios } from "@/pages/agent-scenarios";

interface Draft {
  name: string;
  external_id: string;
  agent_number: string;
  agent_speaks_first: boolean;
  brief: string;
}

const EMPTY: Draft = {
  name: "",
  external_id: "",
  agent_number: "",
  agent_speaks_first: true,
  brief: "",
};

function toDraft(agent: Agent): Draft {
  return {
    name: agent.name,
    external_id: agent.external_id ?? "",
    agent_number: agent.agent_number,
    agent_speaks_first: agent.agent_speaks_first,
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
    brief: draft.brief.trim() || null,
  };
}

export function AgentFormPage() {
  const { id } = useParams();
  const agent = useAgent(id);
  if (!id) return <AgentForm />;
  if (agent.isPending) return <Skeleton className="h-96 w-full max-w-2xl" />;
  if (agent.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the agent</AlertTitle>
        <AlertDescription>{agent.error.message}</AlertDescription>
      </Alert>
    );
  }
  return (
    <div className="grid gap-12">
      <AgentForm key={agent.data.id} agent={agent.data} />
      <AgentScenarios agentId={agent.data.id} />
    </div>
  );
}

function AgentForm({ agent }: { agent?: Agent }) {
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
    save.mutate(toInput(draft, agent), { onSuccess: () => navigate("/agents") });
  };

  return (
    <form onSubmit={submit} className="max-w-2xl">
      <FieldGroup>
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">
            {id ? draft.name || "Agent" : "New agent"}
          </h1>
          {agent && (
            <p className="text-sm text-muted-foreground">Version {agent.current_version}</p>
          )}
        </div>

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
          {draft.agent_number !== "" && !numberOk ? (
            <FieldError>Use the international format, like +14155550100.</FieldError>
          ) : (
            <FieldDescription>Include the country code, like +14155550100.</FieldDescription>
          )}
        </Field>

        <Field orientation="horizontal" className="rounded-md border px-4 py-3">
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

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending && <Spinner />}
            {id ? "Save changes" : "Register agent"}
          </Button>
          <Button variant="ghost" nativeButton={false} render={<Link to="/agents" />}>
            Cancel
          </Button>
          {id && (
            <AlertDialog>
              <AlertDialogTrigger
                render={
                  <Button type="button" variant="ghost" className="ml-auto text-destructive" />
                }
              >
                Delete
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete {draft.name}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Past conversations keep their copy of its configuration. An agent with an active
                    conversation cannot be deleted.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => remove.mutate(id, { onSuccess: () => navigate("/agents") })}
                  >
                    Delete
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </FieldGroup>
    </form>
  );
}
