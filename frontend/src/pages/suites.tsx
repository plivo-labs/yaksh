import { Layers, Plus } from "lucide-react";
import { type SubmitEvent, useState } from "react";
import { Link, useNavigate } from "react-router";

import { Pager } from "@/components/pager";
import { ResultLabel } from "@/components/status-label";
import { Timestamp } from "@/components/timestamp";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { usePageParam } from "@/hooks/use-page-param";
import { revealErrors } from "@/lib/forms";
import { SUITES_PAGE, useCreateSuite, useSuites } from "@/lib/queries";
import { passPercentOk } from "@/lib/suites";
import type { Suite, SuiteSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const COLUMNS =
  "grid grid-cols-1 items-center gap-x-4 gap-y-1 px-3 md:grid-cols-[minmax(0,1.2fr)_minmax(0,2fr)_5rem_8rem_12rem]";

/** Suites by name, each with its agents, its calls and its last result. */
export function SuitesPage() {
  const page = usePageParam();
  const suites = useSuites(page);
  const [creating, setCreating] = useState(false);
  const empty = page === 1 && suites.data?.total === 0;

  return (
    <div className="grid gap-6">
      <div className="flex min-h-[30px] items-center justify-between gap-4">
        <div className="grid gap-1">
          <h1 className="text-h3-500">Suites</h1>
          <p className="text-s-400 text-muted-foreground">Run several agents with one action.</p>
        </div>
        {!empty && (
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus />
            New suite
          </Button>
        )}
      </div>

      {suites.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load the suites</AlertTitle>
          <AlertDescription>{suites.error.message}</AlertDescription>
        </Alert>
      ) : empty ? (
        <Empty className="border border-dashed">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Layers />
            </EmptyMedia>
            <EmptyTitle>No suites yet</EmptyTitle>
            <EmptyDescription>
              Put the agents you test together in one suite, then run them all after a change.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setCreating(true)}>
              <Plus />
              New suite
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <div>
          <div className={cn(COLUMNS, "hidden border-b py-3 text-label text-secondary md:grid")}>
            <span>Suite</span>
            <span>Agents</span>
            <span>Calls</span>
            <span>Required pass rate</span>
            <span>Last run</span>
          </div>
          <ul className="divide-y border-b">
            {suites.data === undefined
              ? [0, 1, 2].map((index) => (
                  <li key={index} className={cn(COLUMNS, "py-3.5")}>
                    <Skeleton className="col-span-full h-10" />
                  </li>
                ))
              : suites.data.items.map((suite) => <SuiteRow key={suite.id} suite={suite} />)}
          </ul>
          <Pager className="mt-4" query={suites} pageSize={SUITES_PAGE} />
        </div>
      )}

      {creating && <NewSuiteDialog onClosed={() => setCreating(false)} />}
    </div>
  );
}

function SuiteRow({ suite }: { suite: SuiteSummary }) {
  const shown = suite.agent_names.slice(0, 2);
  const more = suite.agent_names.length - shown.length;
  return (
    <li
      className={cn(
        COLUMNS,
        "relative py-3.5 transition-colors duration-150 hover:bg-hv1 has-[a:focus-visible]:bg-hv1 has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring/50 has-[a:focus-visible]:ring-inset",
      )}
    >
      <Link
        to={`/suites/${suite.id}`}
        className="truncate text-s-500 outline-none after:absolute after:inset-0"
      >
        {suite.name}
      </Link>
      <span className="truncate text-s-400 text-muted-foreground">
        {shown.length === 0
          ? "No agents yet"
          : `${shown.join(", ")}${more > 0 ? ` and ${more} more` : ""}`}
      </span>
      <span className="text-s-400 tabular-nums">{suite.calls}</span>
      <span className="text-s-400 tabular-nums">{suite.required_pass_percent}%</span>
      <span className="flex items-center gap-3 text-s-400">
        {suite.last_run ? (
          <>
            <ResultLabel result={suite.last_run.result} />
            <span className="text-muted-foreground">
              <Timestamp iso={suite.last_run.created_at} />
            </span>
          </>
        ) : (
          <span className="text-muted-foreground">Never run</span>
        )}
      </span>
    </li>
  );
}

/** A suite's name and required pass rate, as a new suite and an edit ask for them. */
export function SuiteFields({
  name,
  percent,
  submitted,
  onNameChange,
  onPercentChange,
}: {
  name: string;
  percent: string;
  submitted: boolean;
  onNameChange: (name: string) => void;
  onPercentChange: (percent: string) => void;
}) {
  const rateOk = passPercentOk(percent);
  return (
    <>
      <Field>
        <FieldLabel htmlFor="suite-name">Name</FieldLabel>
        <Input
          id="suite-name"
          required
          maxLength={80}
          autoFocus
          aria-invalid={submitted && !name.trim()}
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
        />
        {submitted && !name.trim() && <FieldError>Enter a name.</FieldError>}
      </Field>
      <Field>
        <FieldLabel htmlFor="suite-rate">Required pass rate</FieldLabel>
        <div className="flex w-32 items-center gap-2">
          <Input
            id="suite-rate"
            type="number"
            inputMode="numeric"
            min={1}
            max={100}
            aria-invalid={submitted && !rateOk}
            className="tabular-nums"
            value={percent}
            onChange={(event) => onPercentChange(event.target.value)}
          />
          <span className="text-s-400 text-muted-foreground">%</span>
        </div>
        <FieldDescription>Each agent's run is checked against this rate.</FieldDescription>
        {submitted && !rateOk && <FieldError>Enter a whole number from 1 to 100.</FieldError>}
      </Field>
    </>
  );
}

/** Asks for a name and a required pass rate. The suite page adds the agents. `onCreated` gets
 * the new suite; without it, the suite page opens. */
export function NewSuiteDialog({
  onClosed,
  onCreated,
}: {
  onClosed: () => void;
  onCreated?: (suite: Suite) => void;
}) {
  const [open, setOpen] = useState(true);
  const [name, setName] = useState("");
  const [percent, setPercent] = useState("80");
  const [submitted, setSubmitted] = useState(false);
  const create = useCreateSuite();
  const navigate = useNavigate();

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !revealErrors(
        event.currentTarget,
        () => setSubmitted(true),
        Boolean(name.trim()) && passPercentOk(percent),
      )
    )
      return;
    create.mutate(
      { name: name.trim(), required_pass_percent: Number(percent) },
      {
        onSuccess: (suite) => {
          setOpen(false);
          if (onCreated) onCreated(suite);
          else navigate(`/suites/${suite.id}`);
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && !create.isPending && setOpen(false)}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="sm:max-w-md">
        <form noValidate onSubmit={submit} className="grid gap-6">
          <DialogHeader>
            <DialogTitle>New suite</DialogTitle>
            <DialogDescription>Add its agents on the next page.</DialogDescription>
          </DialogHeader>
          <SuiteFields
            name={name}
            percent={percent}
            submitted={submitted}
            onNameChange={setName}
            onPercentChange={setPercent}
          />
          {create.isError && <FieldError>{create.error.message}</FieldError>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending && <Spinner />}
              Create suite
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
