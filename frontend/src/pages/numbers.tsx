import { Dot } from "@/components/status-dot";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { phone } from "@/lib/format";
import { usePhoneNumbers } from "@/lib/queries";
import type { PhoneNumber } from "@/lib/types";

const ROW =
  "grid grid-cols-[minmax(10rem,1fr)_minmax(8rem,1fr)_minmax(8rem,1fr)_minmax(12rem,1.4fr)_9rem] items-center gap-x-4 px-3";

const STATES: Record<PhoneNumber["state"], { label: string; tone: "green" | "amber" | "off" }> = {
  in_use: { label: "In use by a test", tone: "green" },
  resting: { label: "Resting", tone: "amber" },
  free: { label: "Free", tone: "off" },
};

export function NumbersPage() {
  const numbers = usePhoneNumbers();
  return (
    <div className="mx-auto grid max-w-6xl gap-6">
      <h1 className="text-2xl font-semibold tracking-[-0.015em]">Numbers</h1>
      {numbers.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load numbers</AlertTitle>
          <AlertDescription>{numbers.error.message}</AlertDescription>
        </Alert>
      ) : (
        <>
          {numbers.data?.outbound_problem && (
            <Alert>
              <AlertTitle>Outbound tests are off</AlertTitle>
              <AlertDescription>
                <p className="break-words">{numbers.data.outbound_problem}</p>
                <p>
                  The worker reads the Plivo application and its numbers when it starts, so restart
                  it after a change in the Plivo console.
                </p>
              </AlertDescription>
            </Alert>
          )}
          <div>
            <div className={`${ROW} border-b pb-2.5 text-xs text-muted-foreground`}>
              <span>Number</span>
              <span>Name</span>
              <span>Region</span>
              <span>Plivo application</span>
              <span>Status</span>
            </div>
            <ul className="divide-y border-b">
              {numbers.data === undefined ? (
                [0, 1, 2].map((index) => (
                  <li key={index} className={`${ROW} py-3.5`}>
                    <Skeleton className="h-5" />
                  </li>
                ))
              ) : numbers.data.items.length === 0 ? (
                <li className="grid gap-1 px-3 py-8 text-sm">
                  <span>No numbers yet.</span>
                  <span className="text-muted-foreground">
                    The worker loads them from your Plivo account when it starts.
                  </span>
                </li>
              ) : (
                numbers.data.items.map((item) => <NumberRow key={item.number} item={item} />)
              )}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

function NumberRow({ item }: { item: PhoneNumber }) {
  const state = STATES[item.state];
  return (
    <li className={`${ROW} py-3.5 text-sm`}>
      <span className="font-medium">{phone(item.number)}</span>
      <span className="truncate">{item.alias ?? <Muted>None</Muted>}</span>
      <span className="truncate">{item.region ?? <Muted>Unknown</Muted>}</span>
      <span className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="truncate">
          {item.application_name ?? item.application_id ?? <Muted>None</Muted>}
        </span>
        {item.on_outbound_application && <Badge variant="secondary">Outbound application</Badge>}
      </span>
      <span>
        <Badge variant="outline" className="gap-1.5">
          <Dot tone={state.tone} live={item.state === "in_use"} size="sm" />
          {state.label}
        </Badge>
      </span>
    </li>
  );
}

function Muted({ children }: { children: string }) {
  return <span className="text-muted-foreground">{children}</span>;
}
