"use client"

import { useQuery } from "@tanstack/react-query"
import {
  BellRing,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  Database,
  FileSearch,
  Mail,
  MessageSquareText,
  ShieldAlert,
  Sparkles,
  Trophy,
  XCircle,
} from "lucide-react"
import { AnimatePresence, motion } from "motion/react"

import { apiGet } from "@/lib/api"
import { timeAgo, titleCase } from "@/lib/format"
import type { AuditEntry } from "@/lib/types"
import { cn } from "@/lib/utils"

const ACTIONS: Record<string, { label: string; icon: React.ComponentType<{ className?: string }> }> = {
  "agent_run.finished": { label: "Agent finished an investigation", icon: Bot },
  "approval.approved": { label: "Recommendation approved", icon: CheckCircle2 },
  "approval.rejected": { label: "Recommendation rejected", icon: XCircle },
  "conversation.analyzed": { label: "Conversation analysed by AI", icon: MessageSquareText },
  "conversation.created": { label: "Conversation added", icon: MessageSquareText },
  "data.ingested": { label: "CRM data imported", icon: Database },
  "demo.loaded": { label: "Demo dataset loaded", icon: Database },
  "opportunity.outcome_recorded": { label: "Deal outcome recorded", icon: Trophy },
  "risk.recomputed": { label: "Risk engine re-scored the pipeline", icon: ShieldAlert },
  "settings.updated": { label: "Policy settings updated", icon: ClipboardCheck },
  "tool.request_human_approval": { label: "Approval requested", icon: ClipboardCheck },
  "tool.draft_followup_message": { label: "Follow-up email drafted", icon: Mail },
  "tool.send_email": { label: "Email queued to outbox", icon: Mail },
  "tool.offer_discount": { label: "Revised quote issued", icon: Sparkles },
  "tool.create_followup": { label: "Follow-up task created", icon: ClipboardCheck },
  "tool.analyze_conversation": { label: "Conversation analysed", icon: MessageSquareText },
  "tool.calculate_revenue_risk": { label: "Risk scored", icon: ShieldAlert },
  "tool.log_action": { label: "Action logged", icon: FileSearch },
  "slack.notified": { label: "Sales team alerted in Slack", icon: BellRing },
  "slack.test": { label: "Slack connection tested", icon: BellRing },
}

export function describeAction(action: string) {
  if (ACTIONS[action]) return ACTIONS[action]
  if (action.startsWith("knowledge.")) return { label: "Knowledge base updated", icon: FileSearch }
  return { label: titleCase(action.split(".").pop() ?? action), icon: Sparkles }
}

/** Real audit-log events, polled. `tone="panel"` renders for dark instrument panels. */
export function ActivityFeed({ limit = 4, tone = "default", className }: { limit?: number; tone?: "default" | "panel"; className?: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["activity", limit],
    queryFn: () => apiGet<{ items: AuditEntry[] }>("/audit", { limit: limit * 3 }),
    refetchInterval: 15_000,
  })
  // Collapse bulk events (e.g. 18 "document indexed" rows) so the feed stays informative.
  const items: AuditEntry[] = []
  for (const e of data?.items ?? []) {
    const prev = items[items.length - 1]
    if (prev && describeAction(prev.action).label === describeAction(e.action).label) continue
    items.push(e)
    if (items.length >= limit) break
  }
  const panel = tone === "panel"
  if (isLoading) {
    return (
      <div className={cn("space-y-2", className)}>
        {Array.from({ length: limit }).map((_, i) => (
          <div key={i} className={cn("h-9 rounded-lg", panel ? "bg-white/5" : "shimmer-skeleton")} />
        ))}
      </div>
    )
  }
  if (!items.length) {
    return <p className={cn("py-3 text-xs", panel ? "text-panel-muted" : "text-muted-foreground", className)}>No activity yet. Run the agent on a critical deal.</p>
  }
  return (
    <ul className={cn("divide-y", panel ? "divide-panel-border" : "divide-border", className)}>
      <AnimatePresence initial={false}>
        {items.map((e) => {
          const a = describeAction(e.action)
          const failed = e.result === "failure" || e.result === "blocked"
          return (
            <motion.li
              key={e.id}
              layout
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-3 py-2.5"
            >
              <span
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full",
                  panel ? "bg-panel-money/12 text-panel-money" : "bg-accent text-accent-foreground",
                  failed && (panel ? "bg-red-400/15 text-red-300" : "bg-destructive/10 text-destructive"),
                )}
              >
                <a.icon className="size-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className={cn("truncate text-[13px] font-medium", panel ? "text-panel-foreground" : "text-foreground")}>{a.label}</p>
                {e.customer_name ? (
                  <p className={cn("truncate text-[11px]", panel ? "text-panel-muted" : "text-muted-foreground")}>{e.customer_name}</p>
                ) : null}
              </div>
              <span className={cn("shrink-0 font-mono text-[10.5px]", panel ? "text-panel-muted" : "text-muted-foreground")}>
                {timeAgo(e.occurred_at)}
              </span>
            </motion.li>
          )
        })}
      </AnimatePresence>
    </ul>
  )
}
