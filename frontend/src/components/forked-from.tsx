import { Link } from "react-router";

import { useAgent, usePersona, useScenario } from "@/lib/queries";

/** "Forked from" with a link to the original, while it still exists. */
export function ForkedFrom({
  kind,
  id,
}: {
  kind: "agent" | "persona" | "scenario";
  id: string | null;
}) {
  const agent = useAgent(kind === "agent" && id ? id : undefined);
  const persona = usePersona(kind === "persona" && id ? id : undefined);
  const scenario = useScenario(kind === "scenario" ? id : null);
  const original =
    kind === "agent"
      ? agent.data && { name: agent.data.name, to: `/agents/${agent.data.id}` }
      : kind === "persona"
        ? persona.data && { name: persona.data.name, to: `/personas/${persona.data.id}` }
        : scenario.data && {
            name: scenario.data.name,
            to: `/agents/${scenario.data.agent_id}?tab=scenarios&scenario=${scenario.data.id}`,
          };
  const gone = agent.isError || persona.isError || scenario.isError;
  if (!id || !original || gone) return null;
  return (
    <span className="text-s-400 text-muted-foreground">
      Forked from{" "}
      <Link to={original.to} className="text-foreground underline-offset-4 hover:underline">
        {original.name}
      </Link>
    </span>
  );
}
