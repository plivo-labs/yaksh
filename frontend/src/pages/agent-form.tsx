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
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAgent, useDeleteAgent, useSaveAgent } from "@/lib/queries";
import type { Agent, AgentInput, Direction, Transport } from "@/lib/types";

interface Draft {
  name: string;
  external_id: string;
  direction: Direction;
  transport: Transport;
  websocket_url: string;
  upgrade_headers: string;
  extra_headers: string;
  agent_speaks_first: boolean;
  brief: string;
}

const DIRECTIONS = [
  { value: "inbound", label: "Inbound" },
  { value: "outbound", label: "Outbound" },
];
const TRANSPORTS = [
  { value: "plivo_websocket", label: "Plivo websocket" },
  { value: "phone", label: "Phone" },
];

const EMPTY: Draft = {
  name: "",
  external_id: "",
  direction: "inbound",
  transport: "plivo_websocket",
  websocket_url: "",
  upgrade_headers: "",
  extra_headers: "",
  agent_speaks_first: true,
  brief: "",
};

function headersToText(headers: Record<string, string>): string {
  return Object.entries(headers)
    .map(([name, value]) => `${name}: ${value}`)
    .join("\n");
}

function textToHeaders(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const colon = line.indexOf(":");
    if (colon > 0) headers[line.slice(0, colon).trim()] = line.slice(colon + 1).trim();
  }
  return headers;
}

function toDraft(agent: Agent): Draft {
  return {
    name: agent.name,
    external_id: agent.external_id ?? "",
    direction: agent.direction,
    transport: agent.transport,
    websocket_url: agent.websocket_url ?? "",
    upgrade_headers: headersToText(agent.upgrade_headers),
    extra_headers: headersToText(agent.extra_headers),
    agent_speaks_first: agent.agent_speaks_first,
    brief: agent.brief ?? "",
  };
}

function toInput(draft: Draft): AgentInput {
  return {
    name: draft.name.trim(),
    external_id: draft.external_id.trim() || null,
    direction: draft.direction,
    transport: draft.transport,
    websocket_url: draft.websocket_url.trim() || null,
    upgrade_headers: textToHeaders(draft.upgrade_headers),
    extra_headers: textToHeaders(draft.extra_headers),
    agent_speaks_first: draft.agent_speaks_first,
    brief: draft.brief.trim() || null,
  };
}

export function AgentFormPage() {
  const { id } = useParams();
  const agent = useAgent(id);
  if (!id) return <AgentForm />;
  if (agent.isPending) return <Skeleton className="h-96 w-full max-w-2xl" />;
  if (agent.isError) return <p className="text-destructive">{agent.error.message}</p>;
  return <AgentForm key={agent.data.id} agent={agent.data} />;
}

function AgentForm({ agent }: { agent?: Agent }) {
  const id = agent?.id;
  const navigate = useNavigate();
  const save = useSaveAgent(id);
  const remove = useDeleteAgent();
  const [draft, setDraft] = useState<Draft>(() => (agent ? toDraft(agent) : EMPTY));

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    save.mutate(toInput(draft), { onSuccess: () => navigate("/agents") });
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

        <div className="grid grid-cols-2 gap-4">
          <Field>
            <FieldLabel htmlFor="direction">Direction</FieldLabel>
            <Select
              items={DIRECTIONS}
              value={draft.direction}
              onValueChange={(value) => set("direction", (value ?? draft.direction) as Direction)}
            >
              <SelectTrigger id="direction" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DIRECTIONS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="transport">Transport</FieldLabel>
            <Select
              items={TRANSPORTS}
              value={draft.transport}
              onValueChange={(value) => set("transport", (value ?? draft.transport) as Transport)}
            >
              <SelectTrigger id="transport" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TRANSPORTS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        </div>

        <Field>
          <FieldLabel htmlFor="websocket_url">Stream endpoint</FieldLabel>
          <Input
            id="websocket_url"
            placeholder="wss://agent.example.com/stream"
            value={draft.websocket_url}
            onChange={(e) => set("websocket_url", e.target.value)}
          />
          <FieldDescription>Where the agent accepts a Plivo audio stream.</FieldDescription>
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field>
            <FieldLabel htmlFor="upgrade_headers">Handshake headers</FieldLabel>
            <Textarea
              id="upgrade_headers"
              rows={3}
              placeholder="Authorization: env:AGENT_TOKEN"
              value={draft.upgrade_headers}
              onChange={(e) => set("upgrade_headers", e.target.value)}
            />
            <FieldDescription>
              One per line. Use env:NAME to read a secret from the worker's environment.
            </FieldDescription>
          </Field>
          <Field>
            <FieldLabel htmlFor="extra_headers">Start event headers</FieldLabel>
            <Textarea
              id="extra_headers"
              rows={3}
              placeholder="X-PH-new_call: true"
              value={draft.extra_headers}
              onChange={(e) => set("extra_headers", e.target.value)}
            />
            <FieldDescription>Sent as extra_headers in the stream's start event.</FieldDescription>
          </Field>
        </div>

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
