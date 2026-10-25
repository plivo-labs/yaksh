import { AudioLines, Bot, Hash, Layers, ListChecks, PhoneCall, UserRound } from "lucide-react";

export const NAV_GROUPS: {
  label: string;
  links: { to: string; label: string; icon: typeof Bot }[];
}[] = [
  {
    label: "Test",
    links: [
      { to: "/agents", label: "Agents", icon: Bot },
      { to: "/suites", label: "Suites", icon: Layers },
      { to: "/runs", label: "Runs", icon: ListChecks },
      { to: "/conversations", label: "Conversations", icon: PhoneCall },
    ],
  },
  {
    label: "Callers",
    links: [
      { to: "/personas", label: "Personas", icon: UserRound },
      { to: "/voices", label: "Voices", icon: AudioLines },
      { to: "/numbers", label: "Numbers", icon: Hash },
    ],
  },
];

export const DOCS_URL = "https://github.com/plivo-labs/yaksh/tree/dev/docs/content/docs";
