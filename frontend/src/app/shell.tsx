import {
  AudioLines,
  Bot,
  ClipboardCheck,
  Hash,
  KeyRound,
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

const links: { to: string; label: string; icon: typeof Bot; under?: string[] }[] = [
  /* A run belongs to an agent, so a run page keeps Agents active. */
  { to: "/agents", label: "Agents", icon: Bot, under: ["/runs"] },
  { to: "/conversations", label: "Conversations", icon: PhoneCall },
  { to: "/personas", label: "Personas", icon: UserRound },
  { to: "/voices", label: "Voices", icon: AudioLines },
  { to: "/numbers", label: "Numbers", icon: Hash },
  /* The review screen stands outside the console: it holds a labeler's token. */
  { to: "/review", label: "Review", icon: ClipboardCheck },
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
        style={{ "--sidebar-width": "15rem" } as CSSProperties}
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
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarMenu>
                  {links.map(({ to, label, icon: Icon, under = [] }) => (
                    <SidebarMenuItem key={to}>
                      <SidebarMenuButton
                        isActive={[to, ...under].some((path) => pathname.startsWith(path))}
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
          </SidebarContent>
          <SidebarFooter className="border-t border-sidebar-border">
            <SidebarMenu>
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
            toast: "!rounded-lg !border-border !bg-popover !text-popover-foreground !font-sans",
            description: "!text-muted-foreground",
          },
        }}
      />
    </TooltipProvider>
  );
}
