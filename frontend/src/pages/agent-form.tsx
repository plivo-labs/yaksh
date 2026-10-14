import { MessageSquareText, PhoneIncoming, PhoneOutgoing, Sparkles } from "lucide-react";
import { type ReactNode, type SubmitEvent, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { LanguageChips } from "@/components/language-chips";
import { PhoneInput } from "@/components/phone-input";
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
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useCloseGuard } from "@/hooks/use-close-guard";
import { type AgentDraft, useAgentDraft } from "@/hooks/use-agent-draft";
import { type BriefDrafter, useBriefDraft } from "@/hooks/use-brief-draft";
import {
  CONTEXT_NOTE,
  MAX_BRIEF_CHARS,
  MIN_BRIEF_CHARS,
  toDraft,
  toInput,
} from "@/lib/agent-draft";
import { useDeleteAgent, useSaveAgent } from "@/lib/queries";
import { endpointProblems } from "@/lib/outbound";
import type { Agent, Direction, Transport } from "@/lib/types";
import { ConfigField } from "@/pages/agent-config-field";
import { OutboundFields, Pairs } from "@/pages/agent-outbound-fields";

const REACH_CHOICES: {
  key: string;
  direction: Direction;
  transport: Transport;
  label: string;
  hint: string;
  icon: typeof PhoneOutgoing;
}[] = [
  {
    key: "inbound",
    direction: "inbound",
    transport: "phone",
    label: "Yaksh calls the agent",
    hint: "Yaksh dials the agent's phone number and plays the caller.",
    icon: PhoneOutgoing,
  },
  {
    key: "outbound",
    direction: "outbound",
    transport: "phone",
    label: "The agent calls Yaksh",
    hint: "Yaksh asks the agent to call, then answers as the caller.",
    icon: PhoneIncoming,
  },
  {
    key: "text",
    direction: "inbound",
    transport: "text",
    label: "Yaksh texts the agent",
    hint: "No phone call: Yaksh sends each turn to the agent's URL as text.",
    icon: MessageSquareText,
  },
];

const TEXT_NOTE =
  "Yaksh sends each turn of the test to this URL. Put tokens in a header as {{secrets.<NAME>}}, from Settings.";

const REQUEST_NOTE = "Yaksh sends this request to make the agent call one of Yaksh's numbers.";

export function NameField({ form }: { form: AgentDraft }) {
  const { draft, set, submitted, needs } = form;
  return (
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
  );
}

/** Who calls whom, as two cards; each card is a radio button. */
export function ReachChoice({ form }: { form: AgentDraft }) {
  const { draft, set, submitted, needs } = form;
  const missing = submitted && needs.direction;
  return (
    <FieldSet>
      <FieldLegend variant="label">How does Yaksh reach the agent?</FieldLegend>
      <div className="grid gap-3 sm:grid-cols-3">
        {REACH_CHOICES.map(({ key, direction, transport, label, hint, icon: Icon }) => (
          <label
            key={key}
            className="grid cursor-pointer content-start gap-1.5 rounded-md border bg-background px-4 py-3.5 transition-colors hover:bg-hv1 has-checked:border-foreground has-checked:ring-1 has-checked:ring-foreground has-focus-visible:ring-2 has-focus-visible:ring-ring/50"
          >
            <input
              type="radio"
              name="direction"
              value={key}
              className="sr-only"
              checked={draft.direction === direction && draft.transport === transport}
              aria-invalid={missing}
              aria-describedby={missing ? "direction-error" : undefined}
              onChange={() => {
                set("direction", direction);
                set("transport", transport);
              }}
            />
            <Icon aria-hidden className="size-4.5" />
            <span className="text-p-500">{label}</span>
            <span className="text-s-400 text-muted-foreground">{hint}</span>
          </label>
        ))}
      </div>
      {missing && <FieldError id="direction-error">Choose how Yaksh reaches the agent.</FieldError>}
    </FieldSet>
  );
}

/** The fields for the chosen way: the agent's number, the request that makes it call, or the
 * URL Yaksh texts. */
export function ReachFields({ form }: { form: AgentDraft }) {
  const { draft, set, submitted, needs, swap } = form;
  if (draft.direction === null) return null;
  if (draft.transport === "text") {
    const problems = submitted ? endpointProblems(draft.endpoint) : {};
    return (
      <FieldSet className={swap}>
        <FieldLegend variant="label">The agent's text endpoint</FieldLegend>
        <FieldDescription>{TEXT_NOTE}</FieldDescription>
        <Field>
          <FieldLabel htmlFor="endpoint_url">URL</FieldLabel>
          <Input
            id="endpoint_url"
            required
            placeholder="https://agents.example.com/v1/agent/123/text-test"
            className="font-mono text-xs-400"
            aria-invalid={Boolean(problems.url)}
            aria-describedby={problems.url ? "endpoint_url-error" : undefined}
            value={draft.endpoint.url}
            onChange={(e) => set("endpoint", { ...draft.endpoint, url: e.target.value })}
          />
          {problems.url && <FieldError id="endpoint_url-error">{problems.url}</FieldError>}
        </Field>
        <Field>
          <FieldLabel>Headers</FieldLabel>
          <Pairs
            pairs={draft.endpoint.headers}
            noun="Header"
            namePlaceholder="Authorization"
            valuePlaceholder="Bearer {{secrets.AGENT_TOKEN}}"
            onChange={(headers) => set("endpoint", { ...draft.endpoint, headers })}
          />
          {problems.headers && <FieldError>{problems.headers}</FieldError>}
        </Field>
      </FieldSet>
    );
  }
  if (draft.direction === "outbound") {
    return (
      <FieldSet className={swap}>
        <FieldLegend variant="label">Start request</FieldLegend>
        <FieldDescription>{REQUEST_NOTE}</FieldDescription>
        <OutboundFields
          draft={draft.outbound}
          onChange={(next) => set("outbound", next)}
          submitted={submitted}
        />
      </FieldSet>
    );
  }
  const numberProblem = (submitted || draft.agent_number !== "") && needs.reach;
  return (
    <Field className={swap}>
      <FieldLabel htmlFor="agent_number">The agent's phone number</FieldLabel>
      <PhoneInput
        id="agent_number"
        required
        aria-invalid={numberProblem}
        aria-describedby={numberProblem ? "agent_number-error" : undefined}
        value={draft.agent_number}
        onChange={(value) => set("agent_number", value)}
      />
      {numberProblem && (
        <FieldError id="agent_number-error">
          Use the international format, like +14155550100.
        </FieldError>
      )}
    </Field>
  );
}

/** The agent's own ID, for finding it through the API. */
export function AgentIdField({ form }: { form: AgentDraft }) {
  const { draft, set } = form;
  return (
    <Field>
      <FieldLabel htmlFor="external_id">Agent ID</FieldLabel>
      <Input
        id="external_id"
        placeholder="Optional"
        value={draft.external_id}
        onChange={(e) => set("external_id", e.target.value)}
      />
      <FieldDescription>
        The agent's ID at its provider or in your own system. Use it to find this agent through the
        API.
      </FieldDescription>
    </Field>
  );
}

/** The agent's languages and who speaks first. */
export function CallOptionsFields({ form }: { form: AgentDraft }) {
  const { draft, set, submitted, needs } = form;
  return (
    <>
      <Field>
        <FieldLabel htmlFor="languages">Languages</FieldLabel>
        <LanguageChips
          id="languages"
          value={draft.languages}
          invalid={submitted && needs.languages}
          onValueChange={(languages) => set("languages", languages)}
        />
        <FieldDescription>The first is the main language.</FieldDescription>
        {submitted && needs.languages && <FieldError>Choose a language.</FieldError>}
      </Field>
      <Field orientation="horizontal" className="rounded-md border bg-muted/40 px-3.5 py-3">
        <FieldContent>
          <FieldLabel htmlFor="agent_speaks_first">Agent speaks first</FieldLabel>
          <FieldDescription>
            When off, the caller speaks first, from its instructions.
          </FieldDescription>
        </FieldContent>
        <Switch
          id="agent_speaks_first"
          checked={draft.agent_speaks_first}
          onCheckedChange={(checked) => set("agent_speaks_first", checked)}
        />
      </Field>
    </>
  );
}

/** The brief, which every agent needs, and the config. */
export function ContextFields({ form, brief }: { form: AgentDraft; brief: BriefDrafter }) {
  const { draft, set, submitted, needs } = form;
  const briefProblem = submitted && needs.brief && !brief.drafting;
  return (
    <FieldGroup>
      <Field>
        <div className="flex items-center justify-between gap-3">
          <FieldLabel htmlFor="brief">Brief</FieldLabel>
          {brief.canDraft && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={brief.drafting}
              onClick={brief.draft}
            >
              {brief.drafting ? <Spinner /> : <Sparkles />}
              Draft from config
            </Button>
          )}
        </div>
        <Textarea
          id="brief"
          rows={4}
          required
          readOnly={brief.drafting}
          maxLength={MAX_BRIEF_CHARS}
          placeholder={
            brief.drafting
              ? "Yaksh is drafting the brief from the config."
              : "What this agent is supposed to do, in your words."
          }
          aria-busy={brief.drafting}
          aria-invalid={briefProblem}
          aria-describedby={briefProblem ? "brief-error" : "brief-hint"}
          value={draft.brief}
          onChange={(e) => set("brief", e.target.value)}
        />
        {briefProblem ? (
          <FieldError id="brief-error">
            Write at least {MIN_BRIEF_CHARS} characters about what the agent does.
          </FieldError>
        ) : brief.error ? (
          <FieldError id="brief-hint">Yaksh could not draft the brief: {brief.error}</FieldError>
        ) : (
          <FieldDescription id="brief-hint">
            At least {MIN_BRIEF_CHARS} characters. Check a drafted brief: it should say what the
            agent is for, in your words.
          </FieldDescription>
        )}
      </Field>
      <ConfigField value={draft.config} onChange={(value) => set("config", value)} />
    </FieldGroup>
  );
}

/** The agent's settings in a sheet. It asks before it throws away unsaved changes, and calls
 * `onClosed` once it has closed. Its knowledge base and rules are edited in their own panels. */
export function EditAgentSheet({ agent, onClosed }: { agent: Agent; onClosed: () => void }) {
  const [baseline] = useState(() => toDraft(agent));
  const form = useAgentDraft(baseline);
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
  const brief = useBriefDraft(form);
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
        <FieldDescription>{CONTEXT_NOTE}</FieldDescription>
        <FieldGroup>
          <NameField form={form} />
          <ContextFields form={form} brief={brief} />
          <AgentIdField form={form} />
        </FieldGroup>
      </FieldSet>
      <FieldSet>
        <FieldLegend>Calls</FieldLegend>
        <FieldGroup>
          <ReachChoice form={form} />
          <ReachFields form={form} />
          <CallOptionsFields form={form} />
        </FieldGroup>
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
        <Button type="submit" disabled={save.isPending || brief.drafting}>
          {save.isPending && <Spinner />}
          Save changes
        </Button>
      </div>
    </form>
  );
}
