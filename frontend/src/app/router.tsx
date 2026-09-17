import { Navigate, createBrowserRouter } from "react-router";

import { Shell } from "@/app/shell";
import { AgentFormPage } from "@/pages/agent-form";
import { AgentsPage } from "@/pages/agents";
import { ConversationPage } from "@/pages/conversation";
import { ConversationsPage } from "@/pages/conversations";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <Navigate to="/conversations" replace /> },
      { path: "conversations", element: <ConversationsPage /> },
      { path: "conversations/:id", element: <ConversationPage /> },
      { path: "agents", element: <AgentsPage /> },
      { path: "agents/new", element: <AgentFormPage /> },
      { path: "agents/:id", element: <AgentFormPage /> },
    ],
  },
]);
