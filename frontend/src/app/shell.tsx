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
  SunMedium,
  UserRound,
} from "lucide-react";
import type { ComponentType, CSSProperties } from "react";
import { NavLink, Outlet, useLocation, useMatches } from "react-router";
import { Toaster } from "sonner";

import { TokenGate } from "@/app/token";
import { useDarkMode } from "@/app/use-dark-mode";
import { useToken } from "@/app/use-token";
import { API_TOKEN } from "@/lib/api";
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
                  <span className="text-h4-500">Truman</span>
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
                      href="https://github.com/plivo-labs/truman/tree/dev/docs/content/docs"
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
        <SidebarInset className="h-svh max-h-svh overflow-hidden">
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
