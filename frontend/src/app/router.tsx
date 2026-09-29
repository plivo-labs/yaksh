import { Navigate, createBrowserRouter } from "react-router";

import { RouteError } from "@/app/route-error";
import { Shell } from "@/app/shell";
import { AgentPage } from "@/pages/agent";
import { NewAgentPage } from "@/pages/agent-form";
import { AgentsPage } from "@/pages/agents";
import { ConversationPage } from "@/pages/conversation";
import { ConversationsPage } from "@/pages/conversations";
import { NotFoundPage } from "@/pages/not-found";
import { NumbersPage } from "@/pages/numbers";
import { PersonasPage } from "@/pages/personas";
import { VoicesPage } from "@/pages/voices";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="/agents" replace /> },
      { path: "conversations", element: <ConversationsPage /> },
      { path: "conversations/:id", element: <ConversationPage /> },
      { path: "personas", element: <PersonasPage /> },
      { path: "voices", element: <VoicesPage /> },
      { path: "agents", element: <AgentsPage /> },
      { path: "agents/new", element: <NewAgentPage /> },
      { path: "agents/:id", element: <AgentPage /> },
      { path: "numbers", element: <NumbersPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
