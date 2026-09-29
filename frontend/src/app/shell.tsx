import {
  AudioLines,
  Bot,
  Hash,
  KeyRound,
  MoonStar,
  PhoneCall,
  SunMedium,
  UserRound,
} from "lucide-react";
import { type CSSProperties, useLayoutEffect, useState } from "react";
import { flushSync } from "react-dom";
import { NavLink, Outlet, useLocation } from "react-router";
import { Toaster } from "sonner";

import { TokenGate } from "@/app/token";
import { useToken } from "@/app/use-token";
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
import { TooltipProvider } from "@/components/ui/tooltip";

const THEME_KEY = "truman.theme";

function useDarkMode(): [boolean, () => void] {
  const [dark, setDark] = useState(() => {
    try {
      const saved = localStorage.getItem(THEME_KEY);
      if (saved) return saved === "dark";
    } catch {
      // storage unavailable
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
    } catch {
      // storage unavailable
    }
  }, [dark]);
  const toggle = () => {
    const flip = () => flushSync(() => setDark((value) => !value));
    if (document.startViewTransition) document.startViewTransition(flip);
    else flip();
  };
  return [dark, toggle];
}

const links = [
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/conversations", label: "Conversations", icon: PhoneCall },
  { to: "/personas", label: "Personas", icon: UserRound },
  { to: "/voices", label: "Voices", icon: AudioLines },
  { to: "/numbers", label: "Numbers", icon: Hash },
];

const sidebarOpen = () => !document.cookie.split("; ").includes("sidebar_state=false");

export function Shell() {
  const [token, setToken] = useToken();
  const [dark, toggleDark] = useDarkMode();
  const { pathname } = useLocation();
  if (!token) return <TokenGate onToken={setToken} />;
  const theme = dark ? "Light theme" : "Dark theme";
  return (
    <TooltipProvider>
      <SidebarProvider
        defaultOpen={sidebarOpen()}
        style={{ "--sidebar-width": "12rem" } as CSSProperties}
      >
        <Sidebar collapsible="icon">
          <SidebarHeader>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton size="lg" render={<NavLink to="/agents" />}>
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-base font-semibold text-primary-foreground">
                    T
                  </span>
                  <span className="text-base font-semibold tracking-tight">Truman</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarHeader>
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarMenu>
                  {links.map(({ to, label, icon: Icon }) => (
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
          </SidebarContent>
          <SidebarFooter>
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
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger />
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-6">
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
