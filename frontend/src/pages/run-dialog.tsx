import { type SubmitEvent, useState } from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { counted } from "@/lib/format";
import { usePersonaNames } from "@/hooks/use-persona-names";
import { useDefaults, usePhoneNumbers, useRunScenarios, useStartRun } from "@/lib/queries";
import type { AgentSummary, RunSummary } from "@/lib/types";

const APPEAR = "transition-opacity duration-150 ease-out starting:opacity-0";

/** A whole number from an input, null when it is empty, NaN when it is not a whole number. */
function whole(value: string): number | null {
  if (value.trim() === "") return null;
  const number = Number(value);
  return Number.isInteger(number) ? number : Number.NaN;
}

/** 128 random bits as hex. crypto.randomUUID exists only in a secure context, which a plain
 * HTTP host other than localhost is not. */
function newRequestKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function text(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/** Starts a run of the scenarios, in the order given. For "Run again", `earlier` fills the
 * fields, and scenarios deleted since are left out. */
export function RunDialog({
  agent,
  scenarioIds,
  earlier,
  onClosed,
}: {
  agent: AgentSummary;
  scenarioIds: string[];
  earlier?: RunSummary;
  onClosed: () => void;
}) {
  const [open, setOpen] = useState(true);
  const [requestKey] = useState(newRequestKey);
  const [name, setName] = useState(earlier?.name ?? "");
  const [repeats, setRepeats] = useState(text(earlier?.repeats ?? 1));
  /** Null until the user types: the field then shows the server's default. */
  const [maxDuration, setMaxDuration] = useState(earlier ? text(earlier.max_duration_s) : null);
  const [maxParallel, setMaxParallel] = useState(text(earlier?.max_parallel));
  const [delay, setDelay] = useState(text(earlier?.start_interval_s));
  const [retries, setRetries] = useState(earlier ? text(earlier.max_retries) : null);
  const [submitted, setSubmitted] = useState(false);
  const { scenarios, leftOut, ready, error: loadError } = useRunScenarios(agent.id, scenarioIds);
  const { personas, name: personaName } = usePersonaNames();
  const defaults = useDefaults();
  const durationText = maxDuration ?? text(defaults.data?.max_duration_s);
  const retriesText = retries ?? text(defaults.data?.max_retries);
  const numbers = usePhoneNumbers();
  const start = useStartRun(requestKey);
  const navigate = useNavigate();

  const repeatCount = whole(repeats);
  const duration = whole(durationText);
  const parallel = whole(maxParallel);
  const interval = whole(delay);
  const retryCount = whole(retriesText);
  const repeatsOk = repeatCount !== null && repeatCount >= 1;
  const durationOk = duration === null || (duration >= 10 && duration <= 1800);
  const parallelOk = parallel === null || parallel >= 1;
  const intervalOk = interval === null || interval >= 1;
  const retriesOk = retryCount === null || retryCount >= 0;
  const valid =
    scenarios.length > 0 && repeatsOk && durationOk && parallelOk && intervalOk && retriesOk;
  const total = scenarios.length * (repeatsOk ? repeatCount : 0);

  const perPersona = new Map<string, number>();
  for (const scenario of scenarios) {
    const persona = personaName(scenario.persona_id);
    perPersona.set(persona, (perPersona.get(persona) ?? 0) + 1);
  }
  const outbound = agent.direction === "outbound";
  const usable = (numbers.data?.items ?? []).filter(
    (number) => !outbound || number.on_outbound_application,
  );

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!valid || repeatCount === null) return;
    start.mutate(
      {
        agent_id: agent.id,
        scenario_ids: scenarios.map((scenario) => scenario.id),
        repeats: repeatCount,
        // Untouched fields go as null, for the defaults they show: a resent request then stays
        // the same whether or not the defaults had loaded when it was first sent.
        max_duration_s: maxDuration === null ? null : duration,
        max_parallel: parallel,
        start_interval_s: interval,
        max_retries: retries === null ? null : retryCount,
        name: name.trim() || null,
      },
      { onSuccess: (run) => navigate(`/runs/${run.id}`) },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && !start.isPending && setOpen(false)}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle>{earlier ? "Run again" : "Run scenarios"}</DialogTitle>
          <DialogDescription>
            Each scenario runs with its own persona, once for each repeat.
          </DialogDescription>
        </DialogHeader>

        <form
          id="run-form"
          noValidate
          onSubmit={submit}
          className="min-h-0 flex-1 overflow-y-auto px-6 py-1"
        >
          <FieldGroup className="pb-6">
            <div className="grid gap-1 rounded-md bg-muted/50 px-3 py-2.5 text-sm">
              {loadError ? (
                <p role="alert" className="text-destructive">
                  Could not load the scenarios: {loadError.message}
                </p>
              ) : !ready ? (
                <p className="text-muted-foreground">Loading the scenarios</p>
              ) : (
                <>
                  <p className="font-medium tabular-nums">
                    {counted(total, "conversation", "conversations")}:{" "}
                    {counted(scenarios.length, "scenario", "scenarios")},{" "}
                    {repeatsOk ? counted(repeatCount, "repeat", "repeats") : "no repeats"}
                  </p>
                  <p className="text-muted-foreground">
                    Personas:{" "}
                    {personas.isError
                      ? `could not load them: ${personas.error.message}`
                      : personas.isPending
                        ? "loading"
                        : [...perPersona]
                            .map(([persona, count]) => `${persona} ${count}`)
                            .join(", ")}
                  </p>
                </>
              )}
              {numbers.data && (
                <p className="text-muted-foreground">
                  {outbound
                    ? `${counted(usable.length, "number receives", "numbers receive")} the agent's calls. Each rests ${numbers.data.rest_s} seconds after a call.`
                    : `Truman calls from ${counted(usable.length, "number", "numbers")}, one call on each at a time.`}
                </p>
              )}
              {leftOut > 0 && (
                <p className="text-muted-foreground">
                  {counted(leftOut, "scenario", "scenarios")}
                  {earlier && " of the earlier run"} no longer {leftOut === 1 ? "exists" : "exist"}{" "}
                  and {leftOut === 1 ? "is" : "are"} left out.
                </p>
              )}
            </div>

            <Field>
              <FieldLabel htmlFor="run-name">Name</FieldLabel>
              <Input
                id="run-name"
                maxLength={80}
                placeholder="The creation time when empty"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>

            <div className="grid grid-cols-2 gap-4">
              <Field>
                <FieldLabel htmlFor="run-repeats">Repeats</FieldLabel>
                <Input
                  id="run-repeats"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  aria-invalid={submitted && !repeatsOk}
                  className="tabular-nums"
                  value={repeats}
                  onChange={(event) => setRepeats(event.target.value)}
                />
                {submitted && !repeatsOk && (
                  <FieldError className={APPEAR}>Enter a whole number from 1.</FieldError>
                )}
              </Field>
              <Field>
                <FieldLabel htmlFor="run-duration">Time limit, seconds</FieldLabel>
                <Input
                  id="run-duration"
                  type="number"
                  inputMode="numeric"
                  min={10}
                  max={1800}
                  placeholder="Default"
                  aria-invalid={submitted && !durationOk}
                  className="tabular-nums"
                  value={durationText}
                  onChange={(event) => setMaxDuration(event.target.value)}
                />
                {submitted && !durationOk && (
                  <FieldError className={APPEAR}>
                    Enter a whole number from 10 to 1800, or none.
                  </FieldError>
                )}
              </Field>
              <Field>
                <FieldLabel htmlFor="run-parallel">Max parallel</FieldLabel>
                <Input
                  id="run-parallel"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  placeholder="No run limit"
                  aria-invalid={submitted && !parallelOk}
                  className="tabular-nums"
                  value={maxParallel}
                  onChange={(event) => setMaxParallel(event.target.value)}
                />
                {submitted && !parallelOk && (
                  <FieldError className={APPEAR}>Enter a whole number from 1, or none.</FieldError>
                )}
              </Field>
              <Field>
                <FieldLabel htmlFor="run-delay">Delay between calls, seconds</FieldLabel>
                <Input
                  id="run-delay"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  placeholder="None"
                  aria-invalid={submitted && !intervalOk}
                  className="tabular-nums"
                  value={delay}
                  onChange={(event) => setDelay(event.target.value)}
                />
                {submitted && !intervalOk && (
                  <FieldError className={APPEAR}>Enter a whole number from 1, or none.</FieldError>
                )}
              </Field>
            </div>
            <FieldDescription>
              Max parallel and the delay protect the agent under test. The workers' limits protect
              Truman's phone account.
            </FieldDescription>

            <Field>
              <FieldLabel htmlFor="run-retries">Retries</FieldLabel>
              <Input
                id="run-retries"
                type="number"
                inputMode="numeric"
                min={0}
                placeholder="Default"
                aria-invalid={submitted && !retriesOk}
                className="w-24 tabular-nums"
                value={retriesText}
                onChange={(event) => setRetries(event.target.value)}
              />
              <FieldDescription>
                A conversation that ends with an error on Truman's side or on the line is tried
                again, up to this many times. Empty uses the server default.
              </FieldDescription>
              {submitted && !retriesOk && (
                <FieldError className={APPEAR}>Enter a whole number from 0, or none.</FieldError>
              )}
            </Field>
          </FieldGroup>
        </form>
        {start.error && <FieldError className="px-6 pb-3">{start.error.message}</FieldError>}
        <DialogFooter className="border-t px-6 py-4">
          <Button
            type="button"
            variant="ghost"
            disabled={start.isPending}
            onClick={() => setOpen(false)}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            form="run-form"
            disabled={start.isPending || scenarios.length === 0}
          >
            {start.isPending && <Spinner />}
            Start run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
