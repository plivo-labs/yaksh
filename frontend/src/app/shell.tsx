import {
  AudioLines,
  BookOpen,
  Bot,
  ClipboardCheck,
  Hash,
  KeyRound,
  ListChecks,
  MoonStar,
  PhoneCall,
  SlidersHorizontal,
  SunMedium,
  UserRound,
} from "lucide-react";
import type { ComponentType, CSSProperties } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation, useMatches } from "react-router";
import { Toaster } from "sonner";

import { TokenGate } from "@/app/token";
import { useDarkMode } from "@/app/use-dark-mode";
import { useToken } from "@/app/use-token";
import { API_TOKEN } from "@/lib/api";
import { useSettings } from "@/lib/queries";
import type { AppSettings } from "@/lib/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { TooltipProvider } from "@/components/ui/tooltip";

const groups: { label: string; links: { to: string; label: string; icon: typeof Bot }[] }[] = [
  {
    label: "Test",
    links: [
      { to: "/agents", label: "Agents", icon: Bot },
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

const sidebarOpen = () => !document.cookie.split("; ").includes("sidebar_state=false");

export function Shell() {
  const [token, setToken] = useToken(API_TOKEN);
  const [dark, toggleDark] = useDarkMode();
  const { pathname } = useLocation();
  /** The page's trail, from the `crumbs` component on its route. */
  const page = useMatches().at(-1);
  const Crumbs = (page?.handle as { crumbs?: ComponentType } | undefined)?.crumbs;
  if (!token) return <TokenGate onToken={setToken} />;
  const theme = dark ? "Light theme" : "Dark theme";
  return (
    <TooltipProvider delay={500}>
      <SidebarProvider
        defaultOpen={sidebarOpen()}
        style={{ "--sidebar-width": "12rem" } as CSSProperties}
      >
        <Sidebar collapsible="icon">
          <SidebarHeader>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton size="lg" render={<NavLink to="/agents" />}>
                  <img src="/favicon.svg" alt="" className="size-8 shrink-0" />
                  <span className="text-h4-500">Yaksha</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarHeader>
          <SidebarContent>
            {groups.map((group) => (
              <SidebarGroup key={group.label}>
                <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {group.links.map(({ to, label, icon: Icon }) => (
                      <SidebarMenuItem key={to}>
                        <SidebarMenuButton
                          isActive={pathname.startsWith(to)}
                          tooltip={label}
                          render={<NavLink to={to} />}
                        >
                          <Icon />
                          <span>{label}</span>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    ))}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            ))}
          </SidebarContent>
          <SidebarFooter className="border-t border-sidebar-border">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={pathname.startsWith("/settings")}
                  tooltip="Settings"
                  render={<NavLink to="/settings" />}
                >
                  <SlidersHorizontal />
                  <span>Settings</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              {/* The review screen stands outside the console: it holds a labeler's token. */}
              <SidebarMenuItem>
                <SidebarMenuButton tooltip="Review" render={<a href="/review" target="_blank" />}>
                  <ClipboardCheck />
                  <span>
                    Review<span className="sr-only"> (opens in a new tab)</span>
                  </span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton
                  tooltip="Docs"
                  render={
                    <a
                      href="https://github.com/plivo-labs/yaksha/tree/dev/docs/content/docs"
                      target="_blank"
                      rel="noreferrer"
                    />
                  }
                >
                  <BookOpen />
                  <span>
                    Docs<span className="sr-only"> (opens in a new tab)</span>
                  </span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton tooltip={theme} onClick={toggleDark}>
                  {dark ? <SunMedium /> : <MoonStar />}
                  <span>{theme}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton tooltip="Change token" onClick={() => setToken("")}>
                  <KeyRound />
                  <span>Change token</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarFooter>
          <SidebarRail />
        </Sidebar>
        <SidebarInset className="h-svh max-h-svh overflow-clip">
          <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger />
            {page && Crumbs && (
              <>
                <Separator
                  orientation="vertical"
                  className="mr-2 data-vertical:h-4 data-vertical:self-center"
                />
                <Crumbs key={page.id} />
              </>
            )}
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {!pathname.startsWith("/settings") && <MissingKeys />}
            <Outlet />
          </div>
        </SidebarInset>
      </SidebarProvider>
      <Toaster
        theme={dark ? "dark" : "light"}
        position="bottom-right"
        toastOptions={{
          classNames: {
            toast:
              "!rounded-lg !border-border !bg-popover !text-popover-foreground !font-sans !shadow-2",
            description: "!text-muted-foreground",
          },
        }}
      />
    </TooltipProvider>
  );
}

/** What calls need and the settings do not hold yet. */
function missingKeys(settings: AppSettings): string[] {
  const secrets = settings.secrets;
  return [
    !secrets.llm_api_key && "the LLM provider key",
    !secrets.deepgram_api_key && "the Deepgram key",
    !secrets.elevenlabs_api_key && "the ElevenLabs key",
    !(secrets.plivo_auth_id && secrets.plivo_auth_token) && "the Plivo Auth ID and Auth token",
  ].filter((name): name is string => Boolean(name));
}

function MissingKeys() {
  const settings = useSettings();
  if (!settings.data) return null;
  const missing = missingKeys(settings.data);
  if (missing.length === 0) return null;
  return (
    <Alert className="mb-5">
      <AlertTitle>Calls cannot start yet</AlertTitle>
      <AlertDescription>
        <p>
          Add {missing.join(", ")} in{" "}
          <Link to="/settings" className="underline">
            Settings
          </Link>
          .
        </p>
      </AlertDescription>
    </Alert>
  );
}

/** The console opens on Settings until the LLM provider key is saved, and on Agents after. */
export function FirstPage() {
  const settings = useSettings();
  if (settings.isPending) return null;
  const firstRun = settings.data !== undefined && !settings.data.secrets.llm_api_key;
  return <Navigate to={firstRun ? "/settings" : "/agents"} replace />;
}
