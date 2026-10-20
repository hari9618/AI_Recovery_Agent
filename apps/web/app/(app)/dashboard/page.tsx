"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowRight,
  ArrowUpRight,
  BadgeIndianRupee,
  Bot,
  CalendarClock,
  ClipboardCheck,
  Loader2,
  RefreshCcw,
  Sparkles,
  TriangleAlert,
} from "lucide-react"
import { motion } from "motion/react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Cell, Pie, PieChart } from "recharts"
import { toast } from "sonner"

import { RunAgentButton } from "@/components/agent/run-agent-button"
import { useChat } from "@/components/chat/chat-provider"
import { CountUp, GrowBar, LiveDot, Reveal } from "@/components/motion/primitives"
import { RiskMeter, RISK_STYLE } from "@/components/risk/risk"
import { ActivityFeed } from "@/components/shared/activity-feed"
import { Provenance } from "@/components/shared/provenance"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Button } from "@/components/ui/button"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { useHydrated } from "@/hooks/use-hydrated"
import { apiGet, apiSend, errorMessage } from "@/lib/api"
import { formatMoneyCompact, formatNumber, formatPercent, timeAgo, titleCase } from "@/lib/format"
import type { DashboardSummary, RiskLevel } from "@/lib/types"
import { cn } from "@/lib/utils"

const LEVELS: RiskLevel[] = ["critical", "high", "medium", "low"]
const pieConfig = {
  critical: { label: "Critical", color: "var(--risk-critical)" },
  high: { label: "High", color: "var(--risk-high)" },
  medium: { label: "Medium", color: "var(--risk-medium)" },
  low: { label: "Low", color: "var(--risk-low)" },
} satisfies ChartConfig
const REASON_LABEL: Record<string, string> = {
  CUSTOMER_AWAITING_REPLY: "Customer awaiting reply",
  NO_RECENT_CONTACT: "No recent contact",
  QUOTE_UNANSWERED: "Quote unanswered",
  QUOTE_EXPIRING: "Quote expiring",
  QUOTE_EXPIRED: "Quote expired",
  OVERDUE_FOLLOWUP: "Overdue follow-up",
  COMPETITOR_MENTIONED: "Competitor mentioned",
  PRICE_OBJECTION: "Price objection",
  HIGH_INTENT_STALLED: "High intent, stalled",
  NEGATIVE_SENTIMENT: "Negative sentiment",
  LOW_INTENT: "Low intent",
  LATE_STAGE: "Late-stage deal",
  CLOSE_DATE_PASSED: "Close date passed",
}
const QUICK_QUESTIONS = [
  "Which 3 deals should I call first today?",
  "Which sales rep has the most revenue at risk?",
  "What discount can a rep give without approval?",
]
const compact = (n: number) => formatMoneyCompact(n)
const integer = (n: number) => Math.round(n).toLocaleString("en-IN")

function Stat({
  icon: Icon,
  label,
  value,
  hint,
  href,
  tone,
  index,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: React.ReactNode
  hint: string
  href?: string
  tone: string
  index: number
}) {
  const body = (
    <>
      <div className="flex items-center justify-between">
        <span className={cn("flex size-8 items-center justify-center rounded-lg", tone)}>
          <Icon className="size-4" />
        </span>
        {href ? <ArrowUpRight className="size-4 text-muted-foreground opacity-0 transition group-hover:opacity-100" /> : null}
      </div>
      <div className="font-display mt-4 text-3xl font-bold tabular-nums">{value}</div>
      <p className="mt-1 text-sm font-medium">{label}</p>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </>
  )
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + index * 0.05 }}>
      {href ? (
        <Link href={href} className="group block rounded-xl p-4 transition hover:bg-muted/60">
          {body}
        </Link>
      ) : (
        <div className="rounded-xl p-4">{body}</div>
      )}
    </motion.div>
  )
}

export default function DashboardPage() {
  const qc = useQueryClient()
  const router = useRouter()
  const { setOpen, send } = useChat()
  const hydrated = useHydrated()
  const { data, error, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => apiGet<DashboardSummary>("/dashboard/summary") })
  const batch = useMutation({
    mutationFn: () => apiSend<{ run_ids: string[]; count: number }>("POST", "/agent/runs/batch", { levels: ["critical"], limit: 5 }),
    onSuccess: (r) => {
      toast.success(`Agent started on ${r.count} critical deals`, { description: "Runs execute one after another; follow progress in Agent runs." })
      router.push("/agent-runs")
    },
    onError: (e) => toast.error("Could not start batch", { description: errorMessage(e) }),
  })
  const recompute = useMutation({
    mutationFn: () => apiSend<{ assessed: number }>("POST", "/risks/recompute"),
    onSuccess: (r) => {
      toast.success(`Risk recomputed for ${r.assessed} open deals`)
      qc.invalidateQueries()
    },
    onError: (e) => toast.error("Recompute failed", { description: errorMessage(e) }),
  })

  if (!hydrated || isLoading) return <LoadingBlock rows={8} />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  const k = data.kpis
  const synthetic = data.data_provenance === "synthetic_demo"
  const openDeals = Object.values(data.risk_distribution).reduce((a, b) => a + b.count, 0)
  const totalValue = LEVELS.reduce((a, l) => a + data.risk_distribution[l].deal_value, 0) || 1
  const levelData = LEVELS.map((l) => ({
    key: l,
    name: RISK_STYLE[l].label,
    value: data.risk_distribution[l].deal_value,
    count: data.risk_distribution[l].count,
    fill: `var(--risk-${l})`,
  }))
  const reasons = Object.entries(data.risk_reasons)
    .slice(0, 6)
    .map(([code, v]) => ({ code, label: REASON_LABEL[code] ?? titleCase(code), revenue: v.revenue_at_risk, count: v.count }))
  const maxReason = Math.max(1, ...reasons.map((r) => r.revenue))
  const maxRep = Math.max(1, ...data.reps.map((r) => r.revenue_at_risk))
  const share = k.open_pipeline_value ? k.revenue_at_risk / k.open_pipeline_value : 0
  const ask = (q: string) => {
    setOpen(true)
    send(q)
  }

  return (
    <div className="space-y-6">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="eyebrow">Revenue overview</span>
            {synthetic ? <Provenance kind="synthetic" /> : <Provenance kind="observed" />}
          </div>
          <h1 className="font-display mt-3 text-4xl font-bold tracking-[-0.035em] md:text-[2.75rem]">
            Where revenue is <span className="mark">slipping</span> today
          </h1>
          <p className="mt-2 text-[15px] text-muted-foreground">
            {formatNumber(openDeals)} open deals, scored by the deterministic risk engine {timeAgo(data.risk_computed_at)}.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => recompute.mutate()} disabled={recompute.isPending}>
            {recompute.isPending ? <Loader2 className="animate-spin" /> : <RefreshCcw />} Re-score
          </Button>
          <Button onClick={() => batch.mutate()} disabled={batch.isPending || !k.critical_opportunities}>
            {batch.isPending ? <Loader2 className="animate-spin" /> : <Bot />} Run agent on top 5 critical
          </Button>
        </div>
      </div>

      {/* ── Summary ────────────────────────────────────────────────────────── */}
      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="surface grid grid-cols-1 overflow-hidden lg:grid-cols-12"
      >
        <div className="relative p-6 md:p-8 lg:col-span-5">
          <div className="glow-copper pointer-events-none absolute -top-24 -left-24 size-72" />
          <p className="relative text-sm font-medium text-muted-foreground">Revenue at risk · high + critical</p>
          <CountUp value={k.revenue_at_risk} format={compact} className="font-display relative mt-2 block text-5xl font-bold tracking-[-0.04em] whitespace-nowrap md:text-6xl" />
          <p className="relative mt-2 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{formatPercent(share)}</span> of the {formatMoneyCompact(k.open_pipeline_value)} open
            pipeline · {formatMoneyCompact(k.weighted_revenue_at_risk)} probability-weighted
          </p>
          <div className="relative mt-6">
            <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-full">
              {levelData.map((l, i) => (
                <motion.div
                  key={l.key}
                  initial={{ width: 0 }}
                  animate={{ width: `${(l.value / totalValue) * 100}%` }}
                  transition={{ duration: 0.9, delay: 0.2 + i * 0.1, ease: [0.2, 0.8, 0.2, 1] }}
                  className="h-full first:rounded-l-full last:rounded-r-full"
                  style={{ background: l.fill }}
                />
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {levelData.map((l) => (
                <span key={l.key} className="inline-flex items-center gap-1.5">
                  <span className="size-2 rounded-full" style={{ background: l.fill }} />
                  {l.name} <span className="font-mono text-foreground">{l.count}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-1 border-t p-2 md:grid-cols-4 lg:col-span-7 lg:border-t-0 lg:border-l lg:p-4">
          <Stat
            index={0}
            icon={BadgeIndianRupee}
            tone="bg-money/12 text-money"
            label="Recovered"
            value={<CountUp value={k.revenue_recovered} format={compact} className="text-money" />}
            hint={k.recovered_deals ? `${k.recovered_deals} wins after AI actions` : "Observed wins after AI actions"}
            href="/roi"
          />
          <Stat
            index={1}
            icon={TriangleAlert}
            tone="bg-risk-critical/10 text-risk-critical"
            label="Critical deals"
            value={<CountUp value={k.critical_opportunities} format={integer} />}
            hint={`${k.high_risk_opportunities} high + critical`}
            href="/risks"
          />
          <Stat
            index={2}
            icon={ClipboardCheck}
            tone="bg-copper-soft text-copper"
            label="Awaiting approval"
            value={<CountUp value={k.pending_approvals} format={integer} />}
            hint={`${k.ai_recommendations} AI recommendations`}
            href="/approvals"
          />
          <Stat
            index={3}
            icon={CalendarClock}
            tone="bg-blue/10 text-blue"
            label="Overdue follow-ups"
            value={<CountUp value={k.overdue_followups} format={integer} />}
            hint={`${k.unanswered_leads} new leads waiting 4h+`}
            href="/opportunities"
          />
        </div>
      </motion.section>

      {/* ── Act today + live column ────────────────────────────────────────── */}
      <section className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <Reveal className="surface overflow-hidden xl:col-span-8">
          <div className="flex items-center justify-between gap-3 border-b px-6 py-4">
            <div>
              <h2 className="font-display text-xl font-bold">Act today</h2>
              <p className="text-sm text-muted-foreground">Highest-risk deals and the next step for each</p>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link href="/risks">
                All risks <ArrowRight />
              </Link>
            </Button>
          </div>
          {data.top_risks.length ? (
            <ul className="divide-y">
              {data.top_risks.map((r, i) => (
                <motion.li
                  key={r.risk_id}
                  initial={{ opacity: 0 }}
                  whileInView={{ opacity: 1 }}
                  viewport={{ once: true }}
                  transition={{ delay: i * 0.04 }}
                  className="grid grid-cols-1 items-center gap-3 px-6 py-4 transition-colors hover:bg-muted/40 md:grid-cols-12"
                >
                  <div className="min-w-0 md:col-span-5">
                    <Link href={`/customers/${r.customer_id}`} className="block truncate font-semibold hover:text-copper">
                      {r.customer_name}
                    </Link>
                    <p className="truncate text-xs text-muted-foreground">
                      {titleCase(r.stage)} · {r.owner} · {r.reasons[0]?.label}
                    </p>
                  </div>
                  <div className="md:col-span-2">
                    <span className="font-mono text-sm font-medium">{formatMoneyCompact(r.revenue_at_risk)}</span>
                  </div>
                  <div className="md:col-span-3" title={`${RISK_STYLE[r.risk_level].label} risk`}>
                    <RiskMeter score={r.risk_score} level={r.risk_level} />
                  </div>
                  <div className="md:col-span-2 md:text-right">
                    <RunAgentButton opportunityId={r.opportunity_id} variant="outline" label="Investigate" />
                  </div>
                </motion.li>
              ))}
            </ul>
          ) : (
            <div className="p-6">
              <EmptyState title="No high-risk deals right now" description="Load the demo dataset or import your CRM data." />
            </div>
          )}
        </Reveal>

        <div className="space-y-6 xl:col-span-4">
          <Reveal delay={0.05} className="panel-dark rounded-2xl p-5">
            <div className="mb-1 flex items-center justify-between">
              <p className="font-display text-base font-bold">Live activity</p>
              <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-panel-muted">
                <LiveDot className="text-panel-money" /> live
              </span>
            </div>
            <ActivityFeed tone="panel" limit={4} />
            <Link href="/audit" className="mt-2 inline-flex items-center gap-1 text-xs text-panel-blue hover:underline">
              Full audit log <ArrowRight className="size-3" />
            </Link>
          </Reveal>
          <Reveal delay={0.1} className="surface p-5">
            <div className="flex items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-lg bg-copper-soft text-copper">
                <Sparkles className="size-4" />
              </span>
              <div>
                <p className="font-display text-base font-bold leading-tight">Ask Revenue AI</p>
                <p className="text-xs text-muted-foreground">Answers from your live pipeline</p>
              </div>
            </div>
            <div className="mt-4 space-y-2">
              {QUICK_QUESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => ask(q)}
                  className="group flex w-full items-center justify-between gap-2 rounded-xl border bg-background px-3 py-2.5 text-left text-sm transition hover:border-copper/40 hover:bg-accent/40"
                >
                  {q}
                  <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition group-hover:text-copper" />
                </button>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── Why + mix ──────────────────────────────────────────────────────── */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <Reveal className="surface p-6 lg:col-span-7">
          <h2 className="font-display text-xl font-bold">Why revenue is at risk</h2>
          <p className="mt-1 text-sm text-muted-foreground">Reason codes on high + critical deals, by deal value affected</p>
          {reasons.length ? (
            <ul className="mt-6 space-y-4">
              {reasons.map((r, i) => (
                <li key={r.code}>
                  <div className="mb-1.5 flex items-baseline justify-between gap-3 text-sm">
                    <span className="font-medium">{r.label}</span>
                    <span className="flex items-baseline gap-2">
                      <span className="font-mono font-medium">{formatMoneyCompact(r.revenue)}</span>
                      <span className="text-xs text-muted-foreground">{r.count} deals</span>
                    </span>
                  </div>
                  <GrowBar pct={(r.revenue / maxReason) * 100} delay={i * 0.06} className="h-2" barClassName="bg-gradient-to-r from-copper to-coral" />
                </li>
              ))}
            </ul>
          ) : (
            <div className="mt-6">
              <EmptyState title="No high-risk deals" />
            </div>
          )}
        </Reveal>
        <Reveal delay={0.06} className="surface p-6 lg:col-span-5">
          <h2 className="font-display text-xl font-bold">Pipeline by risk level</h2>
          <p className="mt-1 text-sm text-muted-foreground">Open deal value per level</p>
          <div className="relative mx-auto mt-4 h-52 max-w-60">
            <ChartContainer config={pieConfig} className="h-full w-full">
              <PieChart>
                <ChartTooltip content={<ChartTooltipContent hideLabel formatter={(v, n, item) => `${n}: ${formatMoneyCompact(Number(v))} · ${item.payload.count} deals`} />} />
                <Pie data={levelData} dataKey="value" nameKey="name" innerRadius="70%" outerRadius="100%" paddingAngle={3} cornerRadius={4} strokeWidth={0} animationDuration={1000}>
                  {levelData.map((d) => (
                    <Cell key={d.key} fill={d.fill} />
                  ))}
                </Pie>
              </PieChart>
            </ChartContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-xs text-muted-foreground">Open value</span>
              <span className="font-display text-2xl font-bold">{formatMoneyCompact(totalValue)}</span>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            {levelData.map((l) => (
              <div key={l.key} className="flex items-center justify-between rounded-lg bg-muted/60 px-3 py-2 text-sm">
                <span className="flex items-center gap-1.5 text-muted-foreground">
                  <span className="size-2 rounded-full" style={{ background: l.fill }} /> {l.name}
                </span>
                <span className="font-mono text-xs font-medium">{formatMoneyCompact(l.value)}</span>
              </div>
            ))}
          </div>
        </Reveal>
      </section>

      {/* ── Reps ───────────────────────────────────────────────────────────── */}
      <Reveal className="surface p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-bold">Revenue at risk by sales rep</h2>
            <p className="mt-1 text-sm text-muted-foreground">High + critical deals and overdue follow-up tasks per owner</p>
          </div>
        </div>
        <div className="mt-6 grid grid-cols-1 gap-x-10 gap-y-5 md:grid-cols-2">
          {data.reps.map((r, i) => (
            <div key={r.owner}>
              <div className="mb-1.5 flex items-baseline justify-between gap-3 text-sm">
                <span className="flex items-center gap-2 font-medium">
                  <span className="flex size-6 items-center justify-center rounded-full bg-secondary text-[10px] font-semibold">
                    {r.owner
                      .split(" ")
                      .map((p) => p[0])
                      .join("")
                      .slice(0, 2)}
                  </span>
                  {r.owner}
                </span>
                <span className="flex items-baseline gap-3 text-xs text-muted-foreground">
                  <span>{r.at_risk_deals} deals</span>
                  <span className={r.overdue_followups >= 10 ? "font-semibold text-risk-critical" : ""}>{r.overdue_followups} overdue</span>
                  <span className="font-mono text-sm font-medium text-foreground">{formatMoneyCompact(r.revenue_at_risk)}</span>
                </span>
              </div>
              <GrowBar pct={(r.revenue_at_risk / maxRep) * 100} delay={i * 0.05} barClassName="bg-gradient-to-r from-blue to-[#66b8d5]" />
            </div>
          ))}
        </div>
      </Reveal>
    </div>
  )
}
