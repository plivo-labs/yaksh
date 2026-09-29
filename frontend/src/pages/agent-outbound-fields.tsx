import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { type OutboundDraft, outboundProblems } from "@/lib/outbound";
import type { Header } from "@/lib/types";

export function OutboundFields({
  draft,
  onChange,
  submitted,
}: {
  draft: OutboundDraft;
  onChange: (next: OutboundDraft) => void;
  submitted: boolean;
}) {
  const problems = submitted ? outboundProblems(draft) : {};
  const set = <K extends keyof OutboundDraft>(key: K, value: OutboundDraft[K]) =>
    onChange({ ...draft, [key]: value });
  const setHeader = (index: number, next: Partial<Header>) =>
    set(
      "headers",
      draft.headers.map((header, at) => (at === index ? { ...header, ...next } : header)),
    );
  const setNumber = (index: number, value: string) =>
    set(
      "calling_numbers",
      draft.calling_numbers.map((number, at) => (at === index ? value : number)),
    );

  return (
    <FieldSet>
      <FieldLegend>Start the call</FieldLegend>
      <FieldDescription>
        Truman sends this POST request to make the agent call one of its numbers.
      </FieldDescription>

      <Field>
        <FieldLabel htmlFor="trigger_url">URL</FieldLabel>
        <Input
          id="trigger_url"
          type="url"
          placeholder="https://api.example.com/calls"
          aria-invalid={Boolean(problems.url)}
          value={draft.url}
          onChange={(e) => set("url", e.target.value)}
        />
        {problems.url && <FieldError>{problems.url}</FieldError>}
      </Field>

      <FieldSet>
        <FieldLegend variant="label">Headers</FieldLegend>
        <div className="grid gap-2">
          {draft.headers.map((header, index) => (
            <div key={index} className="flex items-start gap-2">
              <Input
                aria-label={`Header ${index + 1} name`}
                placeholder="Authorization"
                className="w-2/5"
                value={header.name}
                onChange={(e) => setHeader(index, { name: e.target.value })}
              />
              <Input
                aria-label={`Header ${index + 1} value`}
                placeholder="Bearer {{env.TRUMAN_TRIGGER_KEY}}"
                className="flex-1 font-mono text-xs"
                value={header.value}
                onChange={(e) => setHeader(index, { value: e.target.value })}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove header ${index + 1}`}
                onClick={() =>
                  set(
                    "headers",
                    draft.headers.filter((_, at) => at !== index),
                  )
                }
              >
                <X />
              </Button>
            </div>
          ))}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => set("headers", [...draft.headers, { name: "", value: "" }])}
        >
          <Plus />
          Add header
        </Button>
      </FieldSet>

      <Field>
        <FieldLabel htmlFor="trigger_body">Body (JSON)</FieldLabel>
        <Textarea
          id="trigger_body"
          rows={8}
          className="font-mono text-xs"
          aria-invalid={Boolean(problems.body)}
          value={draft.body}
          onChange={(e) => set("body", e.target.value)}
        />
        {problems.body ? (
          <FieldError>{problems.body}</FieldError>
        ) : (
          <FieldDescription>
            Use these inside string values and header values: <code>{"{{truman.number}}"}</code>{" "}
            (the number to call), <code>{"{{truman.conversation_id}}"}</code>,{" "}
            <code>{"{{agent_data.<name>}}"}</code> (from the scenario) and{" "}
            <code>{"{{env.TRUMAN_TRIGGER_<NAME>}}"}</code> (a secret in Truman's environment).
          </FieldDescription>
        )}
      </Field>

      <FieldSet>
        <FieldLegend variant="label">Calling numbers</FieldLegend>
        <FieldDescription>
          The numbers the agent calls from. Leave empty to accept calls from any number.
        </FieldDescription>
        <div className="grid gap-2">
          {draft.calling_numbers.map((number, index) => (
            <div key={index} className="flex gap-2">
              <Input
                aria-label={`Calling number ${index + 1}`}
                type="tel"
                inputMode="tel"
                placeholder="+1 415 555 0100"
                className="flex-1"
                value={number}
                onChange={(e) => setNumber(index, e.target.value)}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove calling number ${index + 1}`}
                onClick={() =>
                  set(
                    "calling_numbers",
                    draft.calling_numbers.filter((_, at) => at !== index),
                  )
                }
              >
                <X />
              </Button>
            </div>
          ))}
        </div>
        {problems.calling_numbers && <FieldError>{problems.calling_numbers}</FieldError>}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => set("calling_numbers", [...draft.calling_numbers, ""])}
        >
          <Plus />
          Add number
        </Button>
      </FieldSet>

      <Field>
        <FieldLabel htmlFor="dial_window">Dial window</FieldLabel>
        <div className="flex items-center gap-2">
          <Input
            id="dial_window"
            type="number"
            inputMode="numeric"
            min={10}
            max={600}
            className="w-24 tabular-nums"
            aria-invalid={Boolean(problems.dial_window)}
            value={draft.dial_window}
            onChange={(e) => set("dial_window", e.target.value)}
          />
          <span className="text-sm text-muted-foreground">seconds</span>
        </div>
        {problems.dial_window ? (
          <FieldError>{problems.dial_window}</FieldError>
        ) : (
          <FieldDescription>How long Truman waits for the agent to call.</FieldDescription>
        )}
      </Field>
    </FieldSet>
  );
}
