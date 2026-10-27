import {
  BookOpen,
  ClipboardCheck,
  KeyRound,
  MoonStar,
  SlidersHorizontal,
  SunMedium,
  TriangleAlert,
} from "lucide-react";
import type { ComponentType, CSSProperties } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation, useMatches } from "react-router";
import { Toaster } from "sonner";

import { CommandMenu } from "@/app/command-menu";
import { DOCS_URL, NAV_GROUPS, RELEASES_URL } from "@/app/nav";
import { TokenGate } from "@/app/token";
import { useDarkMode } from "@/app/use-dark-mode";
import { useToken } from "@/app/use-token";
import { API_TOKEN } from "@/lib/api";
import { useHealth, useSettings } from "@/lib/queries";
import type { AppSettings } from "@/lib/types";
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
                  <span className="text-h4-500">Yaksh</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarHeader>
          <SidebarContent>
            {NAV_GROUPS.map((group) => (
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
                  render={<a href={DOCS_URL} target="_blank" rel="noreferrer" />}
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
            <ServerVersion />
          </SidebarFooter>
          <SidebarRail />
        </Sidebar>
        <SidebarInset className="h-svh max-h-svh overflow-clip">
          <MissingKeys />
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
            <Outlet />
          </div>
        </SidebarInset>
      </SidebarProvider>
      <CommandMenu dark={dark} onToggleDark={toggleDark} onChangeToken={() => setToken("")} />
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
    !secrets.llm_api_key && "LLM provider",
    !secrets.deepgram_api_key && "Deepgram",
    !secrets.elevenlabs_api_key && "ElevenLabs",
    !(secrets.plivo_auth_id && secrets.plivo_auth_token) && "Plivo",
  ].filter((name): name is string => Boolean(name));
}

/** A strip across the top of every page while tests cannot start: without the LLM key none
 * can, without a speech or Plivo key only phone tests are blocked. */
function MissingKeys() {
  const settings = useSettings();
  if (!settings.data) return null;
  const missing = missingKeys(settings.data);
  if (missing.length === 0) return null;
  return (
    <div
      role="alert"
      className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b bg-warning px-4 py-2 text-s-400 text-warning-foreground"
    >
      <TriangleAlert className="size-4 shrink-0" aria-hidden />
      <span>
        <span className="text-s-500">
          {settings.data.secrets.llm_api_key ? "Phone tests can't start." : "Tests can't start."}
        </span>{" "}
        Missing keys: {missing.join(", ")}.
      </span>
      <Link to="/settings" className="text-s-500 underline underline-offset-2">
        Open Settings
      </Link>
    </div>
  );
}

/** The console opens on Settings until the LLM provider key is saved, and on Agents after. */
export function FirstPage() {
  const settings = useSettings();
  if (settings.isPending) return null;
  const firstRun = settings.data !== undefined && !settings.data.secrets.llm_api_key;
  return <Navigate to={firstRun ? "/settings" : "/agents"} replace />;
}

/** The release the server runs, linked to its notes. Hidden while the sidebar shows icons only. */
function ServerVersion() {
  const { data } = useHealth();
  if (!data) return null;
  return (
    <a
      href={`${RELEASES_URL}/tag/v${data.version}`}
      target="_blank"
      rel="noreferrer"
      className="px-2 text-xs-400 text-muted-foreground hover:text-foreground group-data-[collapsible=icon]:hidden"
    >
      Yaksh {data.version}
      <span className="sr-only"> release notes (opens in a new tab)</span>
    </a>
  );
}
