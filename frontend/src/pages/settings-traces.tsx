import { useState } from "react";

import { TRACES_DOCS_URL } from "@/app/nav";
import { ConfirmDialog } from "@/components/confirm-dialogs";
import { Panel, PanelHeader } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { copyText } from "@/lib/clipboard";
import { ago, when } from "@/lib/format";
import { APPEAR } from "@/lib/motion";
import { useDeleteTraceToken, useNewTraceToken, useTraceToken } from "@/lib/queries";
import { useNow } from "@/lib/use-now";
import type { TraceToken } from "@/lib/types";
import { SettingRow } from "@/pages/settings-keys";

/** The OTLP endpoint of this install: the console and the API share an origin. */
function endpoint(): string {
  return `${window.location.origin}/api/v1/otlp`;
}

/** The trace token that opens the OTLP endpoint, and how an agent sends its traces there. */
export function TracesPanel() {
  const token = useTraceToken();
  const make = useNewTraceToken();
  const [shown, setShown] = useState<string | null>(null);
  const create = () => make.mutate(undefined, { onSuccess: (made) => setShown(made.token) });
  return (
    <Panel>
      <PanelHeader title="Agent traces" />
      <p className="px-5 py-3 text-s-400 text-muted-foreground">
        An agent that sends its traces to Yaksh gets the parts of each wait on its calls: VAD and
        STT, turn detection, LLM TTFT, TTS TTFB, and network and telephony.
      </p>
      {token.isError ? (
        <p className="px-5 pb-4 text-s-400 text-destructive">{token.error.message}</p>
      ) : token.data === undefined ? (
        <Skeleton className="mx-5 mb-4 h-24" />
      ) : shown ? (
        <NewToken token={shown} onDone={() => setShown(null)} />
      ) : token.data === null ? (
        <SettingRow label="Trace token" help="No token: the endpoint refuses all traces.">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={make.isPending} onClick={create}>
              {make.isPending && <Spinner />}
              Create trace token
            </Button>
            <a
              href={TRACES_DOCS_URL}
              target="_blank"
              rel="noreferrer"
              className="text-s-400 underline"
            >
              How to send traces
            </a>
          </div>
        </SettingRow>
      ) : (
        <SavedToken token={token.data} onReplace={create} replacing={make.isPending} />
      )}
      {make.isError && (
        <p className="px-5 pb-4 text-xs-400 text-destructive">{make.error.message}</p>
      )}
    </Panel>
  );
}

function NewToken({ token, onDone }: { token: string; onDone: () => void }) {
  const settings = `YAKSH_TRACE_ENDPOINT=${endpoint()}\nYAKSH_TRACE_TOKEN=${token}`;
  return (
    <SettingRow label="Trace token created" help="Copy it now. Yaksh shows it only one time.">
      <div className={`grid gap-2 ${APPEAR}`}>
        <span className="text-xs-400 text-muted-foreground">Settings for the agent</span>
        <pre className="overflow-x-auto rounded-sm bg-muted px-3 py-2 font-mono text-xs-400">
          {settings}
        </pre>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => void copyText(settings, "Settings copied")}
          >
            Copy
          </Button>
          <Button size="sm" onClick={onDone}>
            Done
          </Button>
        </div>
      </div>
    </SettingRow>
  );
}

function SavedToken({
  token,
  onReplace,
  replacing,
}: {
  token: TraceToken;
  onReplace: () => void;
  replacing: boolean;
}) {
  const remove = useDeleteTraceToken();
  const [asking, setAsking] = useState<"replace" | "delete" | null>(null);
  const now = useNow(30_000);
  return (
    <>
      <SettingRow label="Trace token">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-s-400">••••••••{token.hint}</span>
          <Badge variant="success">Saved</Badge>
          <span className="flex-1" />
          <Button
            size="sm"
            variant="outline"
            disabled={replacing}
            onClick={() => setAsking("replace")}
          >
            {replacing && <Spinner />}
            Replace token
          </Button>
          <Button size="sm" variant="outline" onClick={() => setAsking("delete")}>
            Delete
          </Button>
        </div>
      </SettingRow>
      <SettingRow label="Use" help="A quick check of a first setup, before a test call.">
        <div className="grid gap-2">
          <dl className="grid grid-cols-1 gap-3 text-s-400 sm:grid-cols-3">
            <Fact label="Created">{when(token.created_at)}</Fact>
            <Fact label="Last used">
              {token.last_used_at ? ago(token.last_used_at, now) : "Never"}
            </Fact>
            <Fact label="Last span with a Yaksh key">
              {token.last_key_at ? ago(token.last_key_at, now) : "Never"}
            </Fact>
          </dl>
          <p className="text-xs-400 text-muted-foreground">
            A span counts when it has <code>yaksh.conversation_id</code>, or{" "}
            <code>yaksh.number</code> with a Yaksh number.
          </p>
        </div>
      </SettingRow>
      <HowToSend />
      <ConfirmDialog
        title="Replace the trace token?"
        description="The old token stops at once. Every agent that uses it sends no traces until it gets the new one."
        action="Replace token"
        pending={replacing}
        open={asking === "replace"}
        onOpenChange={(open) => setAsking(open ? "replace" : null)}
        onConfirm={(close) => {
          onReplace();
          close();
        }}
      />
      <ConfirmDialog
        title="Delete the trace token?"
        description="The endpoint refuses all traces, and evaluations stop waiting for them."
        action="Delete"
        destructive
        pending={remove.isPending}
        error={remove.error?.message}
        open={asking === "delete"}
        onOpenChange={(open) => setAsking(open ? "delete" : null)}
        onConfirm={(close) => remove.mutate(undefined, { onSuccess: close })}
      />
    </>
  );
}

function HowToSend() {
  return (
    <SettingRow label="How to send traces">
      <div className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs-400 text-muted-foreground">Endpoint</span>
          <code className="font-mono text-s-400">{endpoint()}</code>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void copyText(endpoint(), "Endpoint copied")}
          >
            Copy
          </Button>
        </div>
        <table className="text-s-400">
          <caption className="pb-1 text-left text-xs-400 text-muted-foreground">
            Put one of these attributes on one or more spans of each test call
          </caption>
          <thead className="text-xs-400 text-muted-foreground">
            <tr>
              <th className="py-1 pr-4 text-left font-normal">Attribute</th>
              <th className="py-1 pr-4 text-left font-normal">Value</th>
              <th className="py-1 pr-4 text-left font-normal">When</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-t">
              <td className="py-1.5 pr-4 align-top font-mono">yaksh.conversation_id</td>
              <td className="py-1.5 pr-4 align-top">
                Yaksh's conversation ID. The trigger request sends it with{" "}
                <code>{"{{yaksh.conversation_id}}"}</code>.
              </td>
              <td className="py-1.5 pr-4 align-top">The agent calls Yaksh</td>
            </tr>
            <tr className="border-t">
              <td className="py-1.5 pr-4 align-top font-mono">yaksh.number</td>
              <td className="py-1.5 pr-4 align-top">Yaksh's phone number on the call, in E.164</td>
              <td className="py-1.5 pr-4 align-top">
                Yaksh calls the agent, or the agent calls Yaksh
              </td>
            </tr>
          </tbody>
        </table>
        <p className="text-xs-400 text-muted-foreground">
          Yaksh reads Pipecat 1.14 and LiveKit Agents 1.8. It keeps only span names, times and
          timing values, not transcripts or prompts.{" "}
          <a href={TRACES_DOCS_URL} target="_blank" rel="noreferrer" className="underline">
            Setup for each stack
          </a>
        </p>
      </div>
    </SettingRow>
  );
}

function Fact({ label, children }: { label: string; children: string }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs-400 text-muted-foreground">{label}</dt>
      <dd className="tabular-nums">{children}</dd>
    </div>
  );
}
