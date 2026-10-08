import { Navigate, createBrowserRouter } from "react-router";

import {
  AgentCrumbs,
  AgentsCrumbs,
  ConversationCrumbs,
  ConversationsCrumbs,
  NewAgentCrumbs,
  NewPersonaCrumbs,
  NumbersCrumbs,
  PersonaCrumbs,
  PersonasCrumbs,
  RunCrumbs,
  RunsCrumbs,
  VoicesCrumbs,
} from "@/app/crumbs";
import { RouteError } from "@/app/route-error";
import { Shell } from "@/app/shell";
import { AgentPage } from "@/pages/agent";
import { AgentsPage } from "@/pages/agents";
import { ConversationPage } from "@/pages/conversation";
import { ConversationsPage } from "@/pages/conversations";
import { AgentWizardPage } from "@/pages/agent-wizard";
import { NewAgentPage } from "@/pages/new-agent";
import { NotFoundPage } from "@/pages/not-found";
import { NumbersPage } from "@/pages/numbers";
import { PersonaPage } from "@/pages/persona";
import { PersonasPage } from "@/pages/personas";
import { ReviewPage, ReviewQueuePage, ReviewShell } from "@/pages/review";
import { RunPage } from "@/pages/run";
import { RunsPage } from "@/pages/runs";
import { VoicesPage } from "@/pages/voices";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="/agents" replace /> },
      {
        path: "conversations",
        element: <ConversationsPage />,
        handle: { crumbs: ConversationsCrumbs },
      },
      {
        path: "conversations/:id",
        element: <ConversationPage />,
        handle: { crumbs: ConversationCrumbs },
      },
      { path: "personas", element: <PersonasPage />, handle: { crumbs: PersonasCrumbs } },
      {
        path: "personas/new",
        element: <PersonaPage key="new" />,
        handle: { crumbs: NewPersonaCrumbs },
      },
      { path: "personas/:id", element: <PersonaPage />, handle: { crumbs: PersonaCrumbs } },
      { path: "voices", element: <VoicesPage />, handle: { crumbs: VoicesCrumbs } },
      { path: "agents", element: <AgentsPage />, handle: { crumbs: AgentsCrumbs } },
      { path: "agents/new", element: <NewAgentPage />, handle: { crumbs: NewAgentCrumbs } },
      {
        path: "agents/new/details",
        element: <AgentWizardPage />,
        handle: { crumbs: NewAgentCrumbs },
      },
      { path: "agents/:id", element: <AgentPage />, handle: { crumbs: AgentCrumbs } },
      { path: "numbers", element: <NumbersPage />, handle: { crumbs: NumbersCrumbs } },
      { path: "runs", element: <RunsPage />, handle: { crumbs: RunsCrumbs } },
      { path: "runs/:id", element: <RunPage />, handle: { crumbs: RunCrumbs } },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
  {
    path: "/review",
    element: <ReviewShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <ReviewQueuePage /> },
      { path: ":id", element: <ReviewPage /> },
    ],
  },
]);
