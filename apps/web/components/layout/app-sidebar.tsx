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
import Link from "next/link"
import { usePathname } from "next/navigation"

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
import { apiGet } from "@/lib/api"
import type { DashboardSummary } from "@/lib/types"

const NAV = [
  {
    label: "Revenue",
    items: [
      { href: "/", label: "Dashboard", icon: Gauge },
      { href: "/risks", label: "Revenue Risks", icon: TriangleAlert, badge: "critical" as const },
      { href: "/opportunities", label: "Opportunities", icon: KanbanSquare },
      { href: "/customers", label: "Customers", icon: Users },
      { href: "/conversations", label: "Conversations", icon: MessagesSquare },
      { href: "/roi", label: "ROI", icon: BadgeIndianRupee },
    ],
  },
  {
    label: "AI Agent",
    items: [
      { href: "/recommendations", label: "Recommendations", icon: Sparkles },
      { href: "/approvals", label: "Approval Center", icon: ClipboardCheck, badge: "approvals" as const },
      { href: "/agent-runs", label: "Agent Runs", icon: Bot },
      { href: "/copilot", label: "Revenue Copilot", icon: LifeBuoy },
    ],
  },
  {
    label: "Data & Knowledge",
    items: [
      { href: "/knowledge", label: "Knowledge Base", icon: BookOpen },
      { href: "/import", label: "Data Import", icon: Upload },
    ],
  },
  {
    label: "Trust & Operations",
    items: [
      { href: "/evaluations", label: "Evaluations", icon: FlaskConical },
      { href: "/observability", label: "Observability", icon: Activity },
      { href: "/audit", label: "Audit Log", icon: ScrollText },
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
  const badges = {
    critical: data?.kpis.critical_opportunities,
    approvals: data?.kpis.pending_approvals,
  }
  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href))

  return (
    <Sidebar collapsible="icon" variant="inset">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Sparkles className="size-4" />
                </div>
                <div className="grid flex-1 text-left leading-tight">
                  <span className="truncate font-semibold">Revenue Recovery</span>
                  <span className="truncate text-xs text-muted-foreground">AI revenue operations</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {NAV.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const count = "badge" in item && item.badge ? badges[item.badge] : undefined
                  return (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton asChild isActive={active(item.href)} tooltip={item.label}>
                        <Link href={item.href}>
                          <item.icon />
                          <span>{item.label}</span>
                        </Link>
                      </SidebarMenuButton>
                      {count ? (
                        <SidebarMenuBadge
                          className={
                            item.badge === "critical"
                              ? "bg-risk-critical/15 text-risk-critical"
                              : "bg-primary/10 text-primary"
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
        <p className="px-2 pb-1 text-[11px] leading-snug text-muted-foreground group-data-[collapsible=icon]:hidden">
          Deterministic risk scoring · grounded AI · human approval for customer-facing actions
        </p>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
