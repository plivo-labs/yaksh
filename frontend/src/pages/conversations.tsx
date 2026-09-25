import { PhoneCall, Plus } from "lucide-react";
import { type SubmitEvent, type MouseEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { duration, when } from "@/lib/format";
import {
  CONVERSATIONS_PAGE,
  useAgents,
  useConversations,
  usePersonas,
  useStartConversation,
} from "@/lib/queries";
import { END_REASON_LABELS, type Agent, type ConversationStatus } from "@/lib/types";

const STATUSES: ConversationStatus[] = [
  "queued",
  "running",
  "ending",
  "completed",
  "failed",
  "invalid",
  "cancelled",
];

const ANY = "any";

export function ConversationsPage() {
  const [params, setParams] = useSearchParams();
  const agentId = params.get("agent_id") ?? ANY;
  const status = params.get("status") ?? ANY;
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const filters: Record<string, string> = {};
  if (agentId !== ANY) filters.agent_id = agentId;
  if (status !== ANY) filters.status = status;
  const agents = useAgents();
  const conversations = useConversations(filters, page);
  const navigate = useNavigate();
  const agentItems = [
    { value: ANY, label: "All agents" },
    ...(agents.data?.map((agent) => ({ value: agent.id, label: agent.name })) ?? []),
  ];
  const statusItems = [
    { value: ANY, label: "All statuses" },
    ...STATUSES.map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) })),
  ];

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value === ANY) next.delete(key);
    else next.set(key, value);
    next.delete("page");
    setParams(next, { replace: true });
  };
  const pageParams = (next: number) => {
    const target = new URLSearchParams(params);
    if (next <= 1) target.delete("page");
    else target.set("page", String(next));
    return target;
  };
  const goTo = (next: number) => (event: MouseEvent) => {
    event.preventDefault();
    setParams(pageParams(next));
  };
  const total = conversations.data?.total ?? 0;
  const last = Math.max(1, Math.ceil(total / CONVERSATIONS_PAGE));

  return (
    <div className="grid gap-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Conversations</h1>
        </div>
        <StartDialog agents={agents.data ?? []} />
      </div>

      <div className="flex flex-wrap gap-3">
        <Select
          items={agentItems}
          value={agentId}
          onValueChange={(value) => setFilter("agent_id", value ?? ANY)}
        >
          <SelectTrigger className="w-56" aria-label="Filter by agent">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {agentItems.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          items={statusItems}
          value={status}
          onValueChange={(value) => setFilter("status", value ?? ANY)}
        >
          <SelectTrigger className="w-44" aria-label="Filter by status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {statusItems.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>

      {conversations.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : conversations.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load conversations</AlertTitle>
          <AlertDescription>{conversations.error.message}</AlertDescription>
        </Alert>
      ) : conversations.data.items.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <PhoneCall />
            </EmptyMedia>
            <EmptyTitle>No conversations yet</EmptyTitle>
          </EmptyHeader>
        </Empty>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Agent</TableHead>
              <TableHead>Persona</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>End</TableHead>
              <TableHead className="text-right">Length</TableHead>
              <TableHead>Started</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {conversations.data.items.map((conversation) => (
              <TableRow
                key={conversation.id}
                className="cursor-pointer"
                onClick={() => navigate(`/conversations/${conversation.id}`)}
              >
                <TableCell className="font-medium">
                  <Link
                    to={`/conversations/${conversation.id}`}
                    className="rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {conversation.agent_name}
                  </Link>
                  <span className="ml-1.5 font-mono text-xs text-muted-foreground">
                    v{conversation.agent_version}
                  </span>
                </TableCell>
                <TableCell className="max-w-96 truncate">
                  {conversation.persona_name}
                  <span className="ml-2 text-muted-foreground">{conversation.goal}</span>
                </TableCell>
                <TableCell>
                  <StatusBadge status={conversation.status} />
                </TableCell>
                <TableCell>
                  {conversation.end_reason ? END_REASON_LABELS[conversation.end_reason] : ""}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {duration(conversation.duration_ms)}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {when(conversation.started_at ?? conversation.created_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {total > CONVERSATIONS_PAGE && (
        <Pagination className="justify-between">
          <span className="font-mono text-xs text-muted-foreground">
            {(page - 1) * CONVERSATIONS_PAGE + 1}–{Math.min(page * CONVERSATIONS_PAGE, total)} of{" "}
            {total}
          </span>
          <PaginationContent>
            <PaginationItem>
              <PaginationPrevious
                href={`?${pageParams(page - 1)}`}
                onClick={goTo(page - 1)}
                aria-disabled={page <= 1}
                className={page <= 1 ? "pointer-events-none opacity-50" : ""}
              />
            </PaginationItem>
            <PaginationItem>
              <PaginationNext
                href={`?${pageParams(page + 1)}`}
                onClick={goTo(page + 1)}
                aria-disabled={page >= last}
                className={page >= last ? "pointer-events-none opacity-50" : ""}
              />
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      )}
    </div>
  );
}

function StartDialog({ agents }: { agents: Agent[] }) {
  const [open, setOpen] = useState(false);
  const [agentId, setAgentId] = useState("");
  const [personaId, setPersonaId] = useState("");
  const [goal, setGoal] = useState("");
  const [maxDuration, setMaxDuration] = useState("300");
  const personas = usePersonas();
  const start = useStartConversation();
  const navigate = useNavigate();
  const chosen = agentId || agents[0]?.id || "";
  const chosenPersona = personaId || personas.data?.[0]?.id || "";
  const agentItems = agents.map((agent) => ({ value: agent.id, label: agent.name }));
  const personaItems = (personas.data ?? []).map((persona) => ({
    value: persona.id,
    label: persona.name,
  }));
  const duration = Number(maxDuration);
  const durationOk = Number.isInteger(duration) && duration >= 10 && duration <= 1800;

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    start.mutate(
      {
        agent_id: chosen,
        persona_id: chosenPersona,
        goal: goal.trim(),
        max_duration_s: duration,
      },
      { onSuccess: (conversation) => navigate(`/conversations/${conversation.id}`) },
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={<Button disabled={agents.length === 0 || personas.data?.length === 0} />}
      >
        <Plus />
        Start conversation
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="grid gap-5">
          <DialogHeader>
            <DialogTitle>Start a conversation</DialogTitle>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="agent">Agent</FieldLabel>
              <Select
                items={agentItems}
                value={chosen}
                onValueChange={(value) => setAgentId(value ?? "")}
              >
                <SelectTrigger id="agent" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {agentItems.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor="persona">Persona</FieldLabel>
              <Select
                items={personaItems}
                value={chosenPersona}
                onValueChange={(value) => setPersonaId(value ?? "")}
              >
                <SelectTrigger id="persona" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {personaItems.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor="goal">Goal</FieldLabel>
              <Textarea
                id="goal"
                rows={4}
                required
                maxLength={2000}
                placeholder="Book a teeth cleaning for next Tuesday morning. Your name is Priya Raman."
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="max_duration">Hang up after (seconds)</FieldLabel>
              <Input
                id="max_duration"
                type="number"
                min={10}
                max={1800}
                value={maxDuration}
                onChange={(event) => setMaxDuration(event.target.value)}
                className="w-40"
              />
            </Field>
          </FieldGroup>
          {start.error && <p className="text-sm text-destructive">{start.error.message}</p>}
          <DialogFooter>
            <Button
              type="submit"
              disabled={start.isPending || !goal.trim() || !chosen || !chosenPersona || !durationOk}
            >
              {start.isPending && <Spinner />}
              Call
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
