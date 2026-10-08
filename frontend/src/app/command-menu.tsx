import { Autocomplete } from "@base-ui/react/autocomplete";
import {
  BookOpen,
  Bot,
  ClipboardCheck,
  KeyRound,
  MoonStar,
  Play,
  Plus,
  SearchIcon,
  SlidersHorizontal,
  SunMedium,
  UserRound,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { DOCS_URL, NAV_GROUPS } from "@/app/nav";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useAgents, usePersonas } from "@/lib/queries";
import type { AgentSummary } from "@/lib/types";
import { RunDialog } from "@/pages/run-dialog";

interface Command {
  value: string;
  label: string;
  icon: typeof Bot;
  run: () => void;
}

interface CommandGroup {
  value: string;
  items: Command[];
}

/** On macOS, Ctrl+K in a text field deletes to the end of the line, so only Cmd+K opens the menu. */
const MAC = /Mac|iPhone|iPad/.test(navigator.userAgent);

/** The menu does not open over a dialog: going to a page from it would drop the dialog's work. */
const otherDialogOpen = () =>
  document.querySelector('[role="dialog"][data-open], [role="alertdialog"][data-open]') !== null;

/** Cmd+K or Ctrl+K opens a menu that goes to a page, opens a record or does an action. */
export function CommandMenu({
  dark,
  onToggleDark,
  onChangeToken,
}: {
  dark: boolean;
  onToggleDark: () => void;
  onChangeToken: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState<AgentSummary | null>(null);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "k" || !(MAC ? event.metaKey : event.ctrlKey)) return;
      event.preventDefault();
      setOpen((now) => !now && !otherDialogOpen());
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, []);
  return (
    <>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          aria-label="Command menu"
          showCloseButton={false}
          className="top-[15vh] flex max-h-[min(32rem,70vh)] translate-y-0 flex-col gap-0 overflow-hidden p-0 sm:max-w-lg"
        >
          <Commands
            dark={dark}
            onToggleDark={onToggleDark}
            onChangeToken={onChangeToken}
            onRun={setRunning}
            onDone={() => setOpen(false)}
          />
        </DialogContent>
      </Dialog>
      {running && <RunDialog key={running.id} agent={running} onClosed={() => setRunning(null)} />}
    </>
  );
}

/** The menu's list. It mounts only while the menu is open, so agents and personas load then. */
function Commands({
  dark,
  onToggleDark,
  onChangeToken,
  onRun,
  onDone,
}: {
  dark: boolean;
  onToggleDark: () => void;
  onChangeToken: () => void;
  onRun: (agent: AgentSummary) => void;
  onDone: () => void;
}) {
  const navigate = useNavigate();
  const agents = useAgents();
  const personas = usePersonas();
  const [query, setQuery] = useState("");
  const go = (to: string) => () => navigate(to);
  const pages: Command[] = [
    ...NAV_GROUPS.flatMap((group) =>
      group.links.map(({ to, label, icon }) => ({ value: to, label, icon, run: go(to) })),
    ),
    { value: "/settings", label: "Settings", icon: SlidersHorizontal, run: go("/settings") },
  ];
  const actions: Command[] = [
    { value: "new-agent", label: "New agent", icon: Plus, run: go("/agents/new") },
    { value: "new-persona", label: "New persona", icon: Plus, run: go("/personas/new") },
    {
      value: "theme",
      label: dark ? "Light theme" : "Dark theme",
      icon: dark ? SunMedium : MoonStar,
      run: onToggleDark,
    },
    { value: "token", label: "Change token", icon: KeyRound, run: onChangeToken },
    {
      value: "review",
      label: "Review",
      icon: ClipboardCheck,
      run: () => window.open("/review", "_blank", "noopener"),
    },
    {
      value: "docs",
      label: "Docs",
      icon: BookOpen,
      run: () => window.open(DOCS_URL, "_blank", "noreferrer"),
    },
  ];
  const agentList = agents.data ?? [];
  const records: CommandGroup[] = [
    {
      value: "Agents",
      items: agentList.map((agent) => ({
        value: `agent-${agent.id}`,
        label: agent.name,
        icon: Bot,
        run: go(`/agents/${agent.id}`),
      })),
    },
    {
      value: "Run all scenarios",
      items: agentList.map((agent) => ({
        value: `run-${agent.id}`,
        label: `Run ${agent.name}`,
        icon: Play,
        run: () => onRun(agent),
      })),
    },
    {
      value: "Personas",
      items: (personas.data ?? []).map((persona) => ({
        value: `persona-${persona.id}`,
        label: persona.name,
        icon: UserRound,
        run: go(`/personas/${persona.id}`),
      })),
    },
  ];
  /** Records show once the user types, so an empty search lists only pages and actions. */
  const groups: CommandGroup[] = [
    { value: "Pages", items: pages },
    ...(query.trim() ? records : []),
    { value: "Actions", items: actions },
  ];
  return (
    <Autocomplete.Root
      open
      inline
      items={groups}
      value={query}
      onValueChange={setQuery}
      autoHighlight="always"
      keepHighlight
    >
      <div className="flex shrink-0 items-center gap-2 border-b px-3">
        <SearchIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <Autocomplete.Input
          aria-label="Search pages, agents, personas and actions"
          placeholder="Search pages, agents, personas and actions"
          className="h-11 w-full bg-transparent text-p-400 outline-none placeholder:text-muted-foreground"
        />
      </div>
      <div className="min-h-0 overflow-y-auto overscroll-contain p-1 [scroll-padding-block:0.25rem]">
        <Autocomplete.Empty className="px-3 py-6 text-center text-s-400 text-muted-foreground empty:hidden">
          No results
        </Autocomplete.Empty>
        <Autocomplete.List>
          {(group: CommandGroup) => (
            <Autocomplete.Group key={group.value} items={group.items} className="not-last:mb-1">
              <Autocomplete.GroupLabel className="px-2.5 py-1.5 text-xs-400 text-muted-foreground">
                {group.value}
              </Autocomplete.GroupLabel>
              <Autocomplete.Collection>
                {(item: Command) => (
                  <Autocomplete.Item
                    key={item.value}
                    value={item}
                    onClick={() => {
                      onDone();
                      item.run();
                    }}
                    className="flex cursor-default items-center gap-2 rounded-md px-2.5 py-1.5 text-s-400 outline-none select-none [scroll-margin-block:0.25rem] data-highlighted:bg-accent data-highlighted:text-accent-foreground"
                  >
                    <item.icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="truncate">{item.label}</span>
                  </Autocomplete.Item>
                )}
              </Autocomplete.Collection>
            </Autocomplete.Group>
          )}
        </Autocomplete.List>
      </div>
    </Autocomplete.Root>
  );
}
