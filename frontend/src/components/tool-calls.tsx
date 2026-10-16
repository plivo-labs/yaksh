import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import { useState } from "react";

import { copyText } from "@/lib/clipboard";
import type { ToolItem } from "@/lib/types";

const LONG = 160;

/** The tools a text agent called in one turn: one row each, opened to its arguments. */
export function ToolCalls({ tools }: { tools: ToolItem[] }) {
  return (
    <ul className="w-full max-w-[600px] overflow-hidden rounded-lg border">
      {tools.map((tool) => (
        <ToolCall key={tool.id} tool={tool} />
      ))}
    </ul>
  );
}

function ToolCall({ tool }: { tool: ToolItem }) {
  const [open, setOpen] = useState(false);
  const [raw, setRaw] = useState(false);
  const args = parsed(tool.arguments);
  const entries = args === null ? [] : Object.entries(args);
  const filled = entries.filter(([, value]) => !empty(value));
  return (
    <li className="border-b text-xs-400 last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex min-h-11 w-full items-center gap-2.5 px-3 text-left outline-none hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        <Wrench className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span
          className="max-w-[45%] min-w-0 shrink-0 truncate font-mono font-medium text-foreground"
          title={tool.name}
        >
          {tool.name}
        </span>
        <span className="min-w-0 flex-1 truncate text-muted-foreground">
          {args === null
            ? tool.arguments
            : entries.length === 0
              ? "no arguments"
              : summary(filled, entries.length - filled.length)}
        </span>
        <span className="shrink-0 text-muted-foreground">
          {tool.output === null ? "No result" : "Result"}
        </span>
        {open ? (
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        ) : (
          <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        )}
      </button>
      {open && (
        <div className="grid gap-3 bg-muted/30 px-3 pt-1 pb-3 pl-9">
          <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3.5 gap-y-2">
            {args === null && <Value name="arguments" value={tool.arguments} />}
            {entries.map(([name, value]) => (
              <Value key={name} name={name} value={value} />
            ))}
            <dt className="font-mono text-muted-foreground">result</dt>
            <dd className="min-w-0">
              {tool.output === null ? (
                <span className="text-muted-foreground">
                  The agent returned no result for this call.
                </span>
              ) : (
                <Text text={pretty(tool.output)} mono />
              )}
            </dd>
          </dl>
          <div className="flex gap-4">
            <button
              type="button"
              onClick={() => setRaw(!raw)}
              className="text-primary hover:underline"
            >
              {raw ? "Hide raw JSON" : "View raw JSON"}
            </button>
            <button
              type="button"
              onClick={() => void copyText(tool.arguments, "Arguments copied")}
              className="text-primary hover:underline"
            >
              Copy arguments
            </button>
          </div>
          {raw && (
            <pre className="overflow-x-auto rounded-md bg-muted p-2 font-mono whitespace-pre-wrap break-words">
              {JSON.stringify(
                {
                  id: tool.id,
                  name: tool.name,
                  arguments: args ?? tool.arguments,
                  output: tool.output,
                },
                null,
                2,
              )}
            </pre>
          )}
        </div>
      )}
    </li>
  );
}

function Value({ name, value }: { name: string; value: unknown }) {
  return (
    <>
      <dt className="truncate font-mono text-muted-foreground" title={name}>
        {name}
      </dt>
      <dd className="min-w-0">
        {empty(value) ? (
          <span className="text-muted-foreground">empty</span>
        ) : typeof value === "string" ? (
          <Text text={value} />
        ) : (
          <Text text={JSON.stringify(value, null, 2)} mono />
        )}
      </dd>
    </>
  );
}

function Text({ text, mono = false }: { text: string; mono?: boolean }) {
  const [all, setAll] = useState(false);
  const cut = !all && text.length > LONG;
  return (
    <span className={`break-words whitespace-pre-wrap ${mono ? "font-mono" : ""}`}>
      {cut ? `${text.slice(0, LONG)}…` : text}
      {text.length > LONG && (
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="ml-1.5 text-primary hover:underline"
        >
          {all ? "Show less" : "Show all"}
        </button>
      )}
    </span>
  );
}

function summary(filled: [string, unknown][], blank: number): string {
  const shown = filled.map(
    ([name, value]) => `${name} ${typeof value === "string" ? value : JSON.stringify(value)}`,
  );
  return [...shown, ...(blank > 0 ? [`${blank} empty`] : [])].join(" · ");
}

/** The arguments as an object, or null when they are not a JSON object. */
function parsed(text: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(text);
    return value !== null && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function pretty(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

const empty = (value: unknown) => value === null || value === "";
