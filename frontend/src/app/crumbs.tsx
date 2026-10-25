import { Fragment } from "react";
import { Link, useParams } from "react-router";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Skeleton } from "@/components/ui/skeleton";
import { runTitle, when } from "@/lib/format";
import {
  useAgent,
  useConversation,
  usePersona,
  useRun,
  useSuite,
  useSuiteRun,
} from "@/lib/queries";

/** One step of the trail. The last step is the current page; a step before it links to `to`. A
 * name that is still loading is undefined. */
interface Step {
  label: string | undefined;
  to?: string;
}

function Trail({ steps }: { steps: Step[] }) {
  return (
    <Breadcrumb className="min-w-0">
      <BreadcrumbList className="flex-nowrap">
        {steps.map((step, index) => {
          const current = index === steps.length - 1;
          return (
            // Each route has a trail of a fixed length, so a step's position is its identity.
            <Fragment key={index}>
              {index > 0 && <BreadcrumbSeparator />}
              <BreadcrumbItem className={current ? "min-w-0" : "shrink-0"}>
                {step.label === undefined ? (
                  <Skeleton className="h-4 w-24" />
                ) : current ? (
                  <BreadcrumbPage className="truncate" title={step.label}>
                    {step.label}
                  </BreadcrumbPage>
                ) : (
                  <BreadcrumbLink
                    render={<Link to={step.to ?? ""} />}
                    title={step.label}
                    className="max-w-48 truncate"
                  >
                    {step.label}
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
            </Fragment>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}

const AGENTS = { label: "Agents", to: "/agents" };

export const AgentsCrumbs = () => <Trail steps={[{ label: "Agents" }]} />;
export const RunsCrumbs = () => <Trail steps={[{ label: "Runs" }]} />;
export const ConversationsCrumbs = () => <Trail steps={[{ label: "Conversations" }]} />;
export const PersonasCrumbs = () => <Trail steps={[{ label: "Personas" }]} />;
const PERSONAS = { label: "Personas", to: "/personas" };
export const NewPersonaCrumbs = () => <Trail steps={[PERSONAS, { label: "New persona" }]} />;

export function PersonaCrumbs() {
  const persona = usePersona(useParams().id);
  return <Trail steps={[PERSONAS, { label: persona.data?.name }]} />;
}
export const VoicesCrumbs = () => <Trail steps={[{ label: "Voices" }]} />;
export const NumbersCrumbs = () => <Trail steps={[{ label: "Numbers" }]} />;
export const SettingsCrumbs = () => <Trail steps={[{ label: "Settings" }]} />;
export const NewAgentCrumbs = () => <Trail steps={[AGENTS, { label: "New agent" }]} />;
export const ImportAgentCrumbs = () => (
  <Trail
    steps={[
      AGENTS,
      { label: "New agent", to: "/agents/new" },
      { label: "Import from a JSON file" },
    ]}
  />
);

export const ProviderImportCrumbs = () => (
  <Trail
    steps={[AGENTS, { label: "New agent", to: "/agents/new" }, { label: "Import from a provider" }]}
  />
);

export function AgentCrumbs() {
  const agent = useAgent(useParams().id);
  return <Trail steps={[AGENTS, { label: agent.data?.name }]} />;
}

const SUITES = { label: "Suites", to: "/suites" };

export const SuitesCrumbs = () => <Trail steps={[{ label: "Suites" }]} />;

export function SuiteCrumbs() {
  const suite = useSuite(useParams().id);
  return <Trail steps={[SUITES, { label: suite.data?.name }]} />;
}

export function SuiteRunCrumbs() {
  const suiteRun = useSuiteRun(useParams().id);
  return (
    <Trail
      steps={[
        SUITES,
        {
          label: suiteRun.data?.suite_name,
          to: suiteRun.data && `/suites/${suiteRun.data.suite_id}`,
        },
        { label: suiteRun.data && when(suiteRun.data.created_at) },
      ]}
    />
  );
}

export function RunCrumbs() {
  const run = useRun(useParams().id);
  return (
    <Trail steps={[{ label: "Runs", to: "/runs" }, { label: run.data && runTitle(run.data) }]} />
  );
}

export function ConversationCrumbs() {
  const conversation = useConversation(useParams().id);
  return (
    <Trail
      steps={[
        { label: "Conversations", to: "/conversations" },
        { label: conversation.data?.scenario_name },
      ]}
    />
  );
}
