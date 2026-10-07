import { ChevronRight, FileJson, Link2, PencilLine } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

/** How to add an agent. Import from a provider comes later. */
export function NewAgentPage() {
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-6">
      <div className="grid gap-1">
        <h1 className="text-h3-500">New agent</h1>
        <p className="text-p-400 text-muted-foreground">
          How do you want to add the agent you want to test?
        </p>
      </div>
      <ul className="grid gap-3">
        <li>
          <Choice
            icon={<Link2 />}
            title="Import from a provider"
            hint="Plivo CX, Vapi, Retell or ElevenLabs. Yaksha reads the agent and fills in what it can."
          />
        </li>
        <li>
          <Choice
            to="/agents/new/json"
            icon={<FileJson />}
            title="Import from a JSON file"
            hint="A Plivo CX agent download. ElevenLabs, Vapi and Retell files are coming soon."
          />
        </li>
        <li>
          <Choice
            to="/agents/new/details"
            icon={<PencilLine />}
            title="Enter the details yourself"
            hint="Tell Yaksha how to reach the agent and what it does."
          />
        </li>
      </ul>
      <div className="border-t pt-5">
        <Button variant="ghost" nativeButton={false} render={<Link to="/agents" />}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/** One way to add an agent: a link to its first page, or a card marked "Coming soon". */
function Choice({
  to,
  icon,
  title,
  hint,
}: {
  to?: string;
  icon: ReactNode;
  title: string;
  hint: string;
}) {
  const body = (
    <>
      <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted [&>svg]:size-4.5">
        {icon}
      </span>
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="flex items-center gap-2 text-p-500">
          {title}
          {!to && <Badge>Coming soon</Badge>}
        </span>
        <span className="text-s-400 text-muted-foreground">{hint}</span>
      </span>
    </>
  );
  const frame = "flex items-start gap-3.5 rounded-lg border bg-card px-4.5 py-4";
  if (!to) {
    return (
      <div aria-disabled="true" className={`${frame} opacity-60`}>
        {body}
      </div>
    );
  }
  return (
    <Link
      to={to}
      className={`${frame} outline-none transition-colors hover:bg-hv1 focus-visible:ring-2 focus-visible:ring-ring/50`}
    >
      {body}
      <ChevronRight aria-hidden className="mt-2 size-4 text-muted-foreground" />
    </Link>
  );
}
