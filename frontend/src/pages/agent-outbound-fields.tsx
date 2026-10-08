import { Plus, X } from "lucide-react";
import { type ClipboardEvent, useEffect, useRef, useState } from "react";

import { PhoneInput } from "@/components/phone-input";
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
import { Textarea } from "@/components/ui/textarea";
import { APPEAR, REVEAL } from "@/lib/motion";
import {
  type OutboundDraft,
  outboundProblems,
  scenarioFields,
  withStartRequest,
} from "@/lib/outbound";
import { useStartRequestFromCurl } from "@/lib/queries";
import type { Header, TriggerMethod } from "@/lib/types";
import { cn } from "@/lib/utils";

const PLACEHOLDERS: { name: string; meaning: string }[] = [
  { name: "{{yaksha.conversation_id}}", meaning: "the test call's ID" },
  { name: "{{agent_data.<name>}}", meaning: "a value from the scenario's data sent to the agent" },
  { name: "{{secrets.<NAME>}}", meaning: "a trigger secret from Settings" },
];

const METHODS: { value: TriggerMethod; label: string }[] = [
  { value: "POST", label: "POST" },
  { value: "GET", label: "GET" },
];

/** The start request: where Yaksha sends it and what it sends first, and the details most agents
 * leave as they are folded below. The details open when one of them has a problem. */
export function OutboundFields({
  draft,
  onChange,
  submitted,
}: {
  draft: OutboundDraft;
  onChange: (next: OutboundDraft) => void;
  submitted: boolean;
}) {
  const [detailsOpen, setDetailsOpen] = useState(
    draft.headers.length > 0 || draft.calling_numbers.length > 0,
  );
  const problems = submitted ? outboundProblems(draft) : {};
  // Opened by a problem, the details stay open while it is fixed: typing the fix must not hide them.
  if (!detailsOpen && (problems.headers || problems.calling_numbers || problems.dial_window)) {
    setDetailsOpen(true);
  }
  const set = <K extends keyof OutboundDraft>(key: K, value: OutboundDraft[K]) =>
    onChange({ ...draft, [key]: value });
  const curl = useStartRequestFromCurl();
  /** The draft as it is when a pasted command's answer arrives, not as it was at the paste. */
  const latest = useRef(draft);
  useEffect(() => {
    latest.current = draft;
  }, [draft]);
  /** After a cURL paste: the field that now holds the number to call, and whether other fields
   * now come from each scenario. */
  const [fromCurl, setFromCurl] = useState<{
    numberField: string | null;
    fromScenarios: boolean;
  } | null>(null);
  /** A cURL command pasted into the URL fills the method, the URL, the headers and the body. */
  const pasteCurl = (event: ClipboardEvent<HTMLInputElement>) => {
    const text = event.clipboardData.getData("text");
    if (!/^\s*curl\s/.test(text)) return;
    event.preventDefault();
    setFromCurl(null);
    curl.mutate(text, {
      onSuccess: (request) => {
        onChange(withStartRequest(latest.current, request));
        setFromCurl({
          numberField: request.number_field,
          fromScenarios: scenarioFields(request).length > 0,
        });
      },
    });
  };
  const urlNote = curl.error
    ? "error"
    : problems.url
      ? "problem"
      : curl.isPending || fromCurl
        ? "curl"
        : "hint";
  const setNumber = (index: number, value: string) =>
    set(
      "calling_numbers",
      draft.calling_numbers.map((number, at) => (at === index ? value : number)),
    );
  const headerCount = draft.headers.length;
  const numberCount = draft.calling_numbers.length;
  const summary = [
    headerCount === 0 ? "No headers" : `${headerCount} header${headerCount === 1 ? "" : "s"}`,
    numberCount === 0
      ? "any calling number"
      : `${numberCount} calling number${numberCount === 1 ? "" : "s"}`,
    `waits ${draft.dial_window || "?"} seconds`,
  ].join(", ");

  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor="trigger_url">URL</FieldLabel>
        <div className="flex">
          <Select
            items={METHODS}
            value={draft.method}
            onValueChange={(value) => value && set("method", value as TriggerMethod)}
          >
            <SelectTrigger
              aria-label="Method"
              className="w-24 rounded-r-none border-r-0 bg-muted font-mono text-xs-500"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {METHODS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Input
            id="trigger_url"
            type="url"
            required
            placeholder="https://api.example.com/calls, or paste a cURL command"
            className="rounded-l-none"
            readOnly={curl.isPending}
            aria-invalid={Boolean(problems.url || curl.error)}
            aria-describedby="trigger_url-note"
            value={draft.url}
            onPaste={pasteCurl}
            onChange={(e) => {
              curl.reset();
              set("url", e.target.value);
            }}
          />
        </div>
        <p role="status" className="sr-only">
          {fromCurl ? "Yaksha filled the start request from the cURL command." : ""}
        </p>
        {urlNote === "error" && (
          <FieldError id="trigger_url-note">
            Yaksha could not read the cURL command: {curl.error?.message}
          </FieldError>
        )}
        {urlNote === "problem" && <FieldError id="trigger_url-note">{problems.url}</FieldError>}
        {urlNote === "curl" && (
          <FieldDescription id="trigger_url-note" className={APPEAR}>
            {curl.isPending ? (
              <span className="flex items-center gap-2">
                <Spinner />
                Reading the cURL command
              </span>
            ) : fromCurl?.numberField ? (
              <>
                Filled from the cURL command.{" "}
                <code className="font-mono text-foreground">{"{{yaksha.number}}"}</code> is now in{" "}
                <code className="font-mono text-foreground">{fromCurl.numberField}</code>.
                {fromCurl.fromScenarios && " The other fields come from each scenario."}
              </>
            ) : (
              <>
                Filled from the cURL command. No field looked like the number to call: put{" "}
                <code className="font-mono text-foreground">{"{{yaksha.number}}"}</code> where your
                API takes it.
              </>
            )}
          </FieldDescription>
        )}
        {urlNote === "hint" && (
          <FieldDescription id="trigger_url-note">
            Or paste the cURL command that your agent platform shows. Yaksha fills the request from
            it and keeps the headers as they are, credentials too.
          </FieldDescription>
        )}
      </Field>

      {draft.method === "POST" ? (
        <Field>
          <FieldLabel htmlFor="trigger_body">Body (JSON)</FieldLabel>
          <Textarea
            id="trigger_body"
            rows={5}
            className="font-mono text-xs-400"
            aria-invalid={Boolean(problems.body)}
            aria-describedby={problems.body ? "trigger_body-error" : "placeholder-hint"}
            value={draft.body}
            onChange={(e) => set("body", e.target.value)}
          />
          {problems.body ? (
            <FieldError id="trigger_body-error">{problems.body}</FieldError>
          ) : (
            <PlaceholderHint where="string values" />
          )}
        </Field>
      ) : (
        <FieldSet>
          <FieldLegend variant="label">Query parameters</FieldLegend>
          <Pairs
            pairs={draft.query}
            noun="Parameter"
            namePlaceholder="to"
            valuePlaceholder="{{yaksha.number}}"
            onChange={(next) => set("query", next)}
          />
          {problems.query && <FieldError>{problems.query}</FieldError>}
          <PlaceholderHint where="parameter values" />
        </FieldSet>
      )}

      <div className="rounded-md border">
        <button
          type="button"
          aria-expanded={detailsOpen}
          aria-controls="request-details"
          className="flex w-full items-center justify-between gap-4 rounded-md px-4 py-3 text-left transition-colors hover:bg-hv1"
          onClick={() => setDetailsOpen(!detailsOpen)}
        >
          <span className="grid gap-0.5">
            <span className="text-s-500">Headers, calling numbers and wait time</span>
            <span className="text-xs-400 text-muted-foreground">{summary}</span>
          </span>
          <span className="text-s-500">{detailsOpen ? "Hide" : "Show"}</span>
        </button>
        {detailsOpen && (
          <div id="request-details" className={cn("grid gap-6 border-t px-4 py-4", REVEAL)}>
            <FieldSet>
              <FieldLegend variant="label">Headers</FieldLegend>
              <Pairs
                pairs={draft.headers}
                noun="Header"
                namePlaceholder="Authorization"
                valuePlaceholder="Bearer {{secrets.API_KEY}}"
                onChange={(next) => set("headers", next)}
              />
              {problems.headers && <FieldError>{problems.headers}</FieldError>}
            </FieldSet>

            <FieldSet>
              <FieldLegend variant="label">Calling numbers</FieldLegend>
              <FieldDescription>
                The numbers the agent calls from. Leave empty to accept a call from any number.
              </FieldDescription>
              {draft.calling_numbers.map((number, index) => (
                <div key={index} className="flex gap-2">
                  <PhoneInput
                    aria-label={`Calling number ${index + 1}`}
                    className="flex-1"
                    value={number}
                    onChange={(value) => setNumber(index, value)}
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
              <FieldLabel htmlFor="dial_window">Wait for the agent's call</FieldLabel>
              <div className="flex items-center gap-2">
                <Input
                  id="dial_window"
                  type="number"
                  inputMode="numeric"
                  min={10}
                  max={600}
                  className="w-24 tabular-nums"
                  aria-invalid={Boolean(problems.dial_window)}
                  aria-describedby={problems.dial_window ? "dial_window-error" : undefined}
                  value={draft.dial_window}
                  onChange={(e) => set("dial_window", e.target.value)}
                />
                <span className="text-p-400 text-muted-foreground">seconds</span>
              </div>
              {problems.dial_window && (
                <FieldError id="dial_window-error">{problems.dial_window}</FieldError>
              )}
            </Field>
          </div>
        )}
      </div>
    </FieldGroup>
  );
}

/** Name and value rows, for headers or query parameters; values may hold placeholders. */
function Pairs({
  pairs,
  noun,
  namePlaceholder,
  valuePlaceholder,
  onChange,
}: {
  pairs: Header[];
  noun: string;
  namePlaceholder: string;
  valuePlaceholder: string;
  onChange: (pairs: Header[]) => void;
}) {
  const setPair = (index: number, next: Partial<Header>) =>
    onChange(pairs.map((pair, at) => (at === index ? { ...pair, ...next } : pair)));
  return (
    <>
      {pairs.map((pair, index) => (
        <div key={index} className="flex items-start gap-2">
          <Input
            aria-label={`${noun} ${index + 1} name`}
            placeholder={namePlaceholder}
            className="w-2/5"
            value={pair.name}
            onChange={(e) => setPair(index, { name: e.target.value })}
          />
          <Input
            aria-label={`${noun} ${index + 1} value`}
            placeholder={valuePlaceholder}
            className="flex-1 font-mono text-xs-400"
            value={pair.value}
            onChange={(e) => setPair(index, { value: e.target.value })}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove ${noun.toLowerCase()} ${index + 1}`}
            onClick={() => onChange(pairs.filter((_, at) => at !== index))}
          >
            <X />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => onChange([...pairs, { name: "", value: "" }])}
      >
        <Plus />
        Add {noun.toLowerCase()}
      </Button>
    </>
  );
}

/** Where the number to call goes, and the other placeholders folded below. */
function PlaceholderHint({ where }: { where: string }) {
  return (
    <div id="placeholder-hint" className="grid gap-1.5 text-s-400 text-muted-foreground">
      <p>
        Put <code className="font-mono text-foreground">{"{{yaksha.number}}"}</code> where your API
        takes the number to call.
      </p>
      <details>
        <summary className="w-fit cursor-pointer rounded-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
          Other placeholders
        </summary>
        <dl className="mt-1.5 grid gap-1">
          {PLACEHOLDERS.map((placeholder) => (
            <div key={placeholder.name} className="flex flex-wrap gap-x-2">
              <dt className="font-mono text-foreground">{placeholder.name}</dt>
              <dd>{placeholder.meaning}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-1.5">They work in {where} and in header values.</p>
      </details>
    </div>
  );
}
