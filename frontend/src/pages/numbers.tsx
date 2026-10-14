import { ChevronRight } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Link } from "react-router";

import { ConfirmDialog } from "@/components/confirm-dialogs";
import { Panel } from "@/components/panel";
import { StatusLabel } from "@/components/status-label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ago, counted, phone, region, upperFirst } from "@/lib/format";
import {
  useCheckNumbers,
  usePhoneAccount,
  usePhoneNumbers,
  useStopNumber,
  useUseNumber,
} from "@/lib/queries";
import type { Tone } from "@/lib/status";
import type { PhoneNumber, PhoneNumbers } from "@/lib/types";

const ROW =
  "grid grid-cols-[minmax(10rem,1.2fr)_minmax(8rem,1.4fr)_minmax(8rem,1.3fr)_9rem] items-center gap-x-4 px-5";

const PHONE_SETTINGS = "/settings?tab=phone";

const STATES: Record<NonNullable<PhoneNumber["state"]>, { label: string; tone: Tone }> = {
  in_use: { label: "In a test", tone: "green" },
  resting: { label: "Resting", tone: "amber" },
  ready: { label: "Ready", tone: "off" },
};

const LOCKED: Partial<Record<NonNullable<PhoneNumber["state"]>, string>> = {
  in_use: "This number is in a running test.",
  resting: "This number rests after a test, so a late call does not reach the next test.",
};

/** The phone account's numbers by who receives their calls: test numbers, free numbers that
 * can become test numbers, and numbers that other applications receive. */
export function NumbersPage() {
  const numbers = usePhoneNumbers();
  const account = usePhoneAccount();
  const data = numbers.data;
  const applicationName =
    account.data?.application?.name ?? account.data?.application?.id ?? data?.application_id;
  return (
    <div className="grid max-w-5xl gap-6">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <div className="grid min-w-0 flex-[1_1_20rem] gap-1">
          <h1 className="text-h3-500">Numbers</h1>
          {data && (
            <p className="text-p-400 text-muted-foreground">
              {data.application_id
                ? `Plivo account, receiving application ${applicationName}.`
                : "Plivo account, no receiving application yet."}{" "}
              <Link to={PHONE_SETTINGS} className="text-foreground underline underline-offset-2">
                Phone settings
              </Link>
            </p>
          )}
        </div>
        {data && <CheckNow numbers={data} />}
      </div>
      {numbers.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load numbers</AlertTitle>
          <AlertDescription>{numbers.error.message}</AlertDescription>
        </Alert>
      ) : data === undefined ? (
        [0, 1, 2].map((index) => <Skeleton key={index} className="h-32" />)
      ) : (
        <Groups numbers={data} applicationName={applicationName ?? null} />
      )}
    </div>
  );
}

function Groups({
  numbers,
  applicationName,
}: {
  numbers: PhoneNumbers;
  applicationName: string | null;
}) {
  const tests = numbers.items.filter((item) => item.owner === "test");
  const free = numbers.items.filter((item) => item.owner === "free");
  const elsewhere = numbers.items.filter((item) => item.owner !== "test" && item.owner !== "free");
  // With a receiving application and no test numbers, the empty Test numbers group says what to
  // do, so the same problem does not show twice.
  const firstSetup = numbers.application_id !== null && tests.length === 0;
  return (
    <>
      {numbers.check_error && (
        <Alert variant="destructive">
          <AlertTitle>Could not check the numbers with Plivo</AlertTitle>
          <AlertDescription>
            <p className="break-words">{upperFirst(numbers.check_error)}</p>
            <p>The numbers below are from the last good check.</p>
          </AlertDescription>
        </Alert>
      )}
      {numbers.problem && !firstSetup && (
        <ProblemAlert title="Tests can't get a number" problem={numbers.problem} />
      )}
      {numbers.outbound_problem && numbers.outbound_problem !== numbers.problem && (
        <ProblemAlert title="Outbound tests are off" problem={numbers.outbound_problem} />
      )}
      {tests.length === 0 ? (
        <Panel className="grid justify-items-start gap-1.5 px-5 py-7">
          <h2 className="text-h4-500">
            {numbers.application_id ? "No test numbers yet" : "No receiving application yet"}
          </h2>
          <p className="max-w-xl text-p-400 text-muted-foreground">
            {numbers.application_id ? (
              "Yaksh needs numbers to call agents from, and for agents to call in outbound tests. Choose free numbers below. Each test uses one number for the length of its call."
            ) : (
              <>
                A Plivo application sends the calls of your test numbers to Yaksh. Choose it in{" "}
                <Link to={PHONE_SETTINGS} className="text-foreground underline underline-offset-2">
                  Phone settings
                </Link>
                , then choose test numbers here.
              </>
            )}
          </p>
        </Panel>
      ) : (
        <Panel>
          <GroupHeader
            title="Test numbers"
            count={tests.length}
            description="Yaksh calls agents from these numbers, and agents call them in outbound tests."
          />
          <NumberTable third="Status">
            {tests.map((item) => (
              <TestRow key={item.number} item={item} applicationName={applicationName} />
            ))}
          </NumberTable>
        </Panel>
      )}
      <Panel>
        <GroupHeader
          title="Free numbers"
          count={free.length}
          description={
            free.length === 0
              ? "No free numbers on this Plivo account. A number is free when no application receives its calls. Remove a number's application in the Plivo console, or buy a number there, then select Check now."
              : "On your Plivo account, and no application receives their calls."
          }
        />
        {free.length > 0 && (
          <NumberTable third="Name in Plivo">
            {free.map((item) => (
              <FreeRow
                key={item.number}
                item={item}
                applicationName={numbers.application_id ? applicationName : null}
              />
            ))}
          </NumberTable>
        )}
      </Panel>
      {elsewhere.length > 0 && <Elsewhere items={elsewhere} />}
    </>
  );
}

/** The time now, again every `every` ms, for times that age while the page is open. */
function useNow(every: number): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), every);
    return () => clearInterval(tick);
  }, [every]);
  return now;
}

/** "Resting, 3 min left", rounded up to whole minutes. */
function restingLabel(until: string | null, now: number): string {
  if (until === null) return STATES.resting.label;
  const minutes = Math.ceil((new Date(until).getTime() - now) / 60_000);
  return minutes <= 1 ? "Resting, under a minute" : `Resting, ${minutes} min left`;
}

/** The last check's time, which ages while the page is open, and a button to check again. */
function CheckNow({ numbers }: { numbers: PhoneNumbers }) {
  const check = useCheckNumbers();
  const now = useNow(30_000);
  return (
    <div className="grid justify-items-end gap-1">
      <div className="flex items-center gap-3">
        <span className="text-s-400 text-muted-foreground">
          {numbers.checked_at
            ? `Checked with Plivo ${ago(numbers.checked_at, now)}`
            : "Not checked with Plivo yet"}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={check.isPending}
          onClick={() => check.mutate()}
        >
          {check.isPending && <Spinner />}
          Check now
        </Button>
      </div>
      {check.isError && <p className="text-xs-400 text-destructive">{check.error.message}</p>}
    </div>
  );
}

function ProblemAlert({ title, problem }: { title: string; problem: string }) {
  return (
    <Alert>
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="break-words">{upperFirst(problem)}.</AlertDescription>
    </Alert>
  );
}

function GroupHeader({
  title,
  count,
  description,
}: {
  title: string;
  count: number;
  description: string;
}) {
  return (
    <div className="grid gap-0.5 px-5 pt-4 pb-3">
      <h2 className="text-h4-500">
        {title} <span className="text-muted-foreground">{count}</span>
      </h2>
      <p className="text-p-400 text-muted-foreground">{description}</p>
    </div>
  );
}

function NumberTable({ third, children }: { third: string; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[40rem]">
        <div className={`${ROW} border-y py-2 text-label text-secondary`}>
          <span>Number</span>
          <span>Region</span>
          <span>{third}</span>
          <span />
        </div>
        <ul className="divide-y">{children}</ul>
      </div>
    </div>
  );
}

function NumberCells({ item }: { item: PhoneNumber }) {
  return (
    <>
      <span className="font-mono text-xs-400">{phone(item.number)}</span>
      <span className="truncate" title={item.region ? region(item.region) : undefined}>
        {item.region && region(item.region)}
      </span>
    </>
  );
}

function TestRow({ item, applicationName }: { item: PhoneNumber; applicationName: string | null }) {
  const [open, setOpen] = useState(false);
  const stop = useStopNumber();
  const now = useNow(15_000);
  const state = STATES[item.state ?? "ready"];
  const locked = item.state ? LOCKED[item.state] : undefined;
  return (
    <li className={`${ROW} py-3 text-s-400`}>
      <NumberCells item={item} />
      <span>
        <StatusLabel tone={state.tone} live={item.state === "in_use"}>
          {item.state === "resting" ? restingLabel(item.rests_until, now) : state.label}
        </StatusLabel>
      </span>
      <span className="flex justify-end">
        {locked ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <span
                  tabIndex={0}
                  className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                />
              }
            >
              <Button variant="outline" size="sm" disabled>
                Stop using
              </Button>
            </TooltipTrigger>
            <TooltipContent side="left">{locked}</TooltipContent>
          </Tooltip>
        ) : (
          <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
            Stop using
          </Button>
        )}
      </span>
      <ConfirmDialog
        title={
          <>
            Stop using <span className="font-mono">{phone(item.number)}</span> for tests?
          </>
        }
        description={`Yaksh removes the Plivo application ${applicationName ?? ""} from this number. Tests no longer use it.`}
        note="The number stays on your Plivo account. You can use it for tests again later."
        action="Stop using"
        pending={stop.isPending}
        error={stop.error?.message}
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) stop.reset();
        }}
        onConfirm={(close) => stop.mutate(item.number, { onSuccess: close })}
      />
    </li>
  );
}

/** `applicationName` is null while no receiving application is chosen: a number cannot become a
 * test number then. */
function FreeRow({ item, applicationName }: { item: PhoneNumber; applicationName: string | null }) {
  const [open, setOpen] = useState(false);
  const use = useUseNumber();
  return (
    <li className={`${ROW} py-3 text-s-400`}>
      <NumberCells item={item} />
      <span className="truncate text-muted-foreground" title={item.alias ?? undefined}>
        {item.alias}
      </span>
      <span className="flex justify-end">
        {applicationName === null ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <span
                  tabIndex={0}
                  className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                />
              }
            >
              <Button size="sm" disabled>
                Use for tests
              </Button>
            </TooltipTrigger>
            <TooltipContent side="left">
              Choose the receiving application in Phone settings first.
            </TooltipContent>
          </Tooltip>
        ) : (
          <Button size="sm" onClick={() => setOpen(true)}>
            Use for tests
          </Button>
        )}
      </span>
      <ConfirmDialog
        title={
          <>
            Use <span className="font-mono">{phone(item.number)}</span> for tests?
          </>
        }
        description={`Yaksh links this number to the Plivo application ${applicationName ?? ""}. Calls to this number then come to Yaksh, and Yaksh can call agents from it.`}
        note="You can stop using it at any time. The number stays on your Plivo account."
        action="Use for tests"
        pending={use.isPending}
        error={use.error?.message}
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) use.reset();
        }}
        onConfirm={(close) => use.mutate(item.number, { onSuccess: close })}
      />
    </li>
  );
}

interface Owner {
  key: string;
  name: string;
  kind: string;
  numbers: string[];
}

/** The numbers other applications receive, one group per application; Plivo CX agents share
 * one group. */
function owners(items: PhoneNumber[]): Owner[] {
  const agents = items.filter((item) => item.owner === "cx_agent");
  const groups: Owner[] = [];
  if (agents.length > 0) {
    const count = new Set(agents.map((item) => item.application_id)).size;
    groups.push({
      key: "cx_agent",
      name: "Plivo CX agents",
      kind: counted(count, "agent", "agents"),
      numbers: agents.map((item) => item.number),
    });
  }
  const others = new Map<string, Owner>();
  for (const item of items.filter((each) => each.owner === "other")) {
    const key = item.application_id ?? "";
    const group = others.get(key) ?? {
      key: `other-${key}`,
      name: item.application_name ?? item.application_id ?? "Unnamed application",
      kind: "Another application",
      numbers: [],
    };
    group.numbers.push(item.number);
    others.set(key, group);
  }
  groups.push(...[...others.values()].sort((a, b) => a.name.localeCompare(b.name)));
  const silent = items.filter((item) => item.owner === "no_voice");
  if (silent.length > 0) {
    groups.push({
      key: "no_voice",
      name: "No voice",
      kind: "Plivo numbers that cannot take calls",
      numbers: silent.map((item) => item.number),
    });
  }
  return groups;
}

function Elsewhere({ items }: { items: PhoneNumber[] }) {
  const [open, setOpen] = useState(false);
  return (
    <Panel>
      <button
        type="button"
        aria-expanded={open}
        aria-controls="numbers-elsewhere"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 rounded-lg px-5 py-4 text-left outline-none transition-colors hover:bg-hv1 focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        <span className="grid flex-1 gap-0.5">
          <span className="text-h4-500">
            Used elsewhere <span className="text-muted-foreground">{items.length}</span>
          </span>
          <span className="text-p-400 text-muted-foreground">
            Other applications receive the calls of these numbers. Yaksh does not use them.
          </span>
        </span>
        <span className="flex items-center gap-1 text-s-400 text-muted-foreground">
          {open ? "Hide" : "Show"}
          <ChevronRight
            aria-hidden
            className={`size-4 transition-transform duration-150 ease-out motion-reduce:transition-none ${open ? "rotate-90" : ""}`}
          />
        </span>
      </button>
      {open && (
        <ul id="numbers-elsewhere" className="divide-y border-t">
          {owners(items).map((group) => (
            <li
              key={group.key}
              className="grid grid-cols-[minmax(11rem,1fr)_minmax(0,3fr)] gap-4 px-5 py-3.5"
            >
              <span className="grid content-start gap-0.5">
                <span className="text-s-500">{group.name}</span>
                <span className="text-xs-400 text-muted-foreground">{group.kind}</span>
              </span>
              <span className="flex flex-wrap content-center gap-x-3.5 gap-y-1.5 font-mono text-xs-400 text-secondary">
                {group.numbers.map((number) => (
                  <span key={number}>{phone(number)}</span>
                ))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
