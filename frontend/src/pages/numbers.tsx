import { Phone } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePhoneNumbers } from "@/lib/queries";
import type { PhoneNumber } from "@/lib/types";

const STATE_LABELS: Record<PhoneNumber["state"], string> = {
  in_use: "In a call",
  resting: "Resting after a call",
  free: "Free",
};

export function NumbersPage() {
  const numbers = usePhoneNumbers();
  return (
    <div className="grid gap-6">
      <div className="grid gap-1">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Numbers</h1>
        <p className="text-sm text-muted-foreground">
          The Plivo numbers Truman calls from and receives calls on.
        </p>
      </div>
      {numbers.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : numbers.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load numbers</AlertTitle>
          <AlertDescription>{numbers.error.message}</AlertDescription>
        </Alert>
      ) : (
        <>
          {numbers.data.outbound_application_id === null && (
            <Alert>
              <AlertTitle>Outbound tests are off</AlertTitle>
              <AlertDescription>
                Set TRUMAN_PLIVO_APP_ID to the Plivo application that sends calls to Truman, then
                link numbers to it in the Plivo console.
              </AlertDescription>
            </Alert>
          )}
          {numbers.data.items.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Phone />
                </EmptyMedia>
                <EmptyTitle>No numbers yet</EmptyTitle>
                <EmptyDescription>
                  The worker reads the numbers from your Plivo account when it starts.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Number</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Region</TableHead>
                  <TableHead>Plivo application</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {numbers.data.items.map((item) => (
                  <TableRow key={item.number}>
                    <TableCell className="font-mono text-xs">{item.number}</TableCell>
                    <TableCell>{item.alias}</TableCell>
                    <TableCell>{item.region}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-2">
                        {item.application_name ?? item.application_id}
                        {item.on_outbound_application && (
                          <Badge variant="secondary">Outbound application</Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>{STATE_LABELS[item.state]}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </>
      )}
    </div>
  );
}
