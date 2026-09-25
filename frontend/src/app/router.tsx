import { Navigate, createBrowserRouter } from "react-router";

import { RouteError } from "@/app/route-error";
import { Shell } from "@/app/shell";
import { AgentFormPage } from "@/pages/agent-form";
import { AgentsPage } from "@/pages/agents";
import { ConversationPage } from "@/pages/conversation";
import { ConversationsPage } from "@/pages/conversations";
import { NotFoundPage } from "@/pages/not-found";
import { PersonasPage } from "@/pages/personas";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="/conversations" replace /> },
      { path: "conversations", element: <ConversationsPage /> },
      { path: "conversations/:id", element: <ConversationPage /> },
      { path: "personas", element: <PersonasPage /> },
      { path: "agents", element: <AgentsPage /> },
      { path: "agents/new", element: <AgentFormPage /> },
      { path: "agents/:id", element: <AgentFormPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
