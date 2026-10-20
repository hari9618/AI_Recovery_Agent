"use client"

import { useQuery } from "@tanstack/react-query"
import {
  Activity,
  BadgeIndianRupee,
  BookOpen,
  Bot,
  ClipboardCheck,
  FlaskConical,
  Gauge,
  KanbanSquare,
  LifeBuoy,
  MessagesSquare,
  ScrollText,
  Settings,
  Sparkles,
  TriangleAlert,
  Upload,
  Users,
} from "lucide-react"
import { motion } from "motion/react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { LogoMark, Wordmark } from "@/components/brand/logo"
import { useChat } from "@/components/chat/chat-provider"
import { LiveDot } from "@/components/motion/primitives"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { useHydrated } from "@/hooks/use-hydrated"
import { apiGet } from "@/lib/api"
import type { DashboardSummary } from "@/lib/types"

const NAV = [
  {
    label: "Pipeline",
    items: [
      { href: "/dashboard", label: "Overview", icon: Gauge },
      { href: "/risks", label: "Risks", icon: TriangleAlert, badge: "critical" as const },
      { href: "/opportunities", label: "Deals", icon: KanbanSquare },
      { href: "/customers", label: "Customers", icon: Users },
      { href: "/conversations", label: "Conversations", icon: MessagesSquare },
    ],
  },
  {
    label: "AI agent",
    items: [
      { href: "/approvals", label: "Approvals", icon: ClipboardCheck, badge: "approvals" as const },
      { href: "/recommendations", label: "Recommendations", icon: Sparkles },
      { href: "/agent-runs", label: "Agent runs", icon: Bot },
      { href: "/copilot", label: "Revenue AI", icon: LifeBuoy },
    ],
  },
  {
    label: "Workspace",
    items: [
      { href: "/roi", label: "ROI", icon: BadgeIndianRupee },
      { href: "/knowledge", label: "Knowledge", icon: BookOpen },
      { href: "/import", label: "Import data", icon: Upload },
      { href: "/evaluations", label: "Evaluations", icon: FlaskConical },
      { href: "/observability", label: "Observability", icon: Activity },
      { href: "/audit", label: "Audit log", icon: ScrollText },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
]

export function AppSidebar() {
  const pathname = usePathname()
  const { data } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiGet<DashboardSummary>("/dashboard/summary"),
    refetchInterval: 60_000,
  })
  const hydrated = useHydrated()
  const badges = {
    critical: hydrated ? data?.kpis.critical_opportunities : undefined,
    approvals: hydrated ? data?.kpis.pending_approvals : undefined,
  }
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<{ llm_configured: boolean; llm_model: string | null; langfuse_configured: boolean }>("/health"),
    staleTime: 60_000,
  })
  const llm = hydrated ? health.data : undefined
  const { setOpen } = useChat()
  const active = (href: string) => pathname === href || pathname.startsWith(`${href}/`)

  return (
    <Sidebar collapsible="icon" variant="inset" className="border-r-0">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild className="hover:bg-transparent active:bg-transparent">
              <Link href="/">
                <LogoMark className="size-8 shrink-0" />
                <div className="grid flex-1 gap-1 text-left leading-tight">
                  <Wordmark className="truncate" />
                  <span className="truncate font-mono text-[10px] tracking-[0.12em] text-sidebar-muted uppercase">AI revenue agent</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {NAV.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel className="font-mono text-[10px] font-medium tracking-[0.14em] text-sidebar-muted uppercase">{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const count = "badge" in item && item.badge ? badges[item.badge] : undefined
                  return (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton
                        asChild
                        isActive={active(item.href)}
                        tooltip={item.label}
                        className="relative text-sidebar-foreground/70 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground data-active:bg-transparent data-active:font-semibold data-active:text-sidebar-accent-foreground"
                      >
                        <Link href={item.href}>
                          {active(item.href) ? (
                            <motion.span
                              layoutId="nav-active"
                              className="absolute inset-0 -z-0 rounded-lg bg-sidebar-accent shadow-[0_1px_2px_#1212120f,0_0_0_1px_var(--sidebar-border)]"
                              transition={{ type: "spring", stiffness: 420, damping: 34 }}
                            >
                              <span className="absolute top-2 right-2 size-1.5 rounded-full bg-sidebar-primary" />
                            </motion.span>
                          ) : null}
                          <item.icon className={`relative ${active(item.href) ? "text-sidebar-primary" : ""}`} />
                          <span className="relative">{item.label}</span>
                        </Link>
                      </SidebarMenuButton>
                      {count ? (
                        <SidebarMenuBadge
                          className={
                            item.badge === "critical"
                              ? "bg-risk-critical/12 font-mono text-[10px] text-risk-critical"
                              : "bg-copper-soft font-mono text-[10px] text-copper"
                          }
                        >
                          {count}
                        </SidebarMenuBadge>
                      ) : null}
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <div className="space-y-2 rounded-xl border border-sidebar-border bg-sidebar-accent p-2.5 shadow-[0_1px_2px_#1212120a] group-data-[collapsible=icon]:hidden">
          <div className="flex items-center gap-2 text-xs font-medium text-sidebar-foreground">
            <LiveDot className={llm?.llm_configured ? "text-money" : "text-amber"} />
            {llm ? (llm.llm_configured ? "AI agent online" : "Rules-fallback mode") : "Checking AI status…"}
          </div>
          <p className="truncate font-mono text-[10px] text-sidebar-muted">
            {llm ? `${llm.llm_model ?? "no model"} · tracing ${llm.langfuse_configured ? "on" : "off"}` : "connecting"}
          </p>
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-foreground px-2 py-1.5 text-xs font-semibold text-background transition hover:opacity-90"
          >
            <Sparkles className="size-3.5 text-copper" /> Ask Revenue AI
          </button>
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
