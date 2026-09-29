import { Bot, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { when } from "@/lib/format";
import { useAgents } from "@/lib/queries";

export function AgentsPage() {
  const agents = useAgents();
  const navigate = useNavigate();
  return (
    <div className="grid gap-6">
      <div className="flex items-start justify-between gap-4">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Agents</h1>
        <Button nativeButton={false} render={<Link to="/agents/new" />}>
          <Plus />
          New agent
        </Button>
      </div>
      {agents.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : agents.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load agents</AlertTitle>
          <AlertDescription>{agents.error.message}</AlertDescription>
        </Alert>
      ) : agents.data.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Bot />
            </EmptyMedia>
            <EmptyTitle>No agents yet</EmptyTitle>
          </EmptyHeader>
          <EmptyContent>
            <Button nativeButton={false} render={<Link to="/agents/new" />} variant="outline">
              Register an agent
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Number</TableHead>
              <TableHead>Speaks first</TableHead>
              <TableHead className="text-right">Version</TableHead>
              <TableHead>Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {agents.data.map((agent) => (
              <TableRow
                key={agent.id}
                className="cursor-pointer"
                onClick={() => navigate(`/agents/${agent.id}`)}
              >
                <TableCell className="font-medium">
                  <Link
                    to={`/agents/${agent.id}`}
                    className="rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {agent.name}
                  </Link>
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {agent.agent_number ?? (
                    <span className="font-sans text-muted-foreground">Calls Truman</span>
                  )}
                </TableCell>
                <TableCell>{agent.agent_speaks_first ? "Yes" : "No"}</TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {agent.current_version}
                </TableCell>
                <TableCell className="font-mono text-xs">{when(agent.updated_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
