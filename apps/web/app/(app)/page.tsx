"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BadgeIndianRupee, Bot, CalendarClock, ClipboardCheck, Loader2, RefreshCcw, ShieldAlert, Sparkles, TrendingUp } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from "recharts"
import { toast } from "sonner"

import { RunAgentButton } from "@/components/agent/run-agent-button"
import { RiskBadge, RiskMeter, RISK_STYLE } from "@/components/risk/risk"
import { KpiCard } from "@/components/shared/kpi-card"
import { PageHeader } from "@/components/shared/page-header"
import { Provenance } from "@/components/shared/provenance"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiGet, apiSend, errorMessage } from "@/lib/api"
import { formatMoneyCompact, formatNumber, formatPercent, timeAgo, titleCase } from "@/lib/format"
import type { DashboardSummary, RiskLevel } from "@/lib/types"

const LEVELS: RiskLevel[] = ["critical", "high", "medium", "low"]
const levelChart = {
  revenue: { label: "Revenue at risk", color: "var(--chart-1)" },
} satisfies ChartConfig
const reasonChart = { revenue: { label: "Revenue at risk", color: "var(--chart-1)" } } satisfies ChartConfig
const REASON_LABEL: Record<string, string> = {
  CUSTOMER_AWAITING_REPLY: "Customer awaiting reply",
  NO_RECENT_CONTACT: "No recent contact",
  QUOTE_UNANSWERED: "Quote unanswered",
  QUOTE_EXPIRING: "Quote expiring",
  QUOTE_EXPIRED: "Quote expired",
  OVERDUE_FOLLOWUP: "Overdue follow-up",
  COMPETITOR_MENTIONED: "Competitor mentioned",
  PRICE_OBJECTION: "Price objection",
  HIGH_INTENT_STALLED: "High intent stalled",
  NEGATIVE_SENTIMENT: "Negative sentiment",
  LOW_INTENT: "Low intent",
  LATE_STAGE: "Late-stage deal",
  CLOSE_DATE_PASSED: "Close date passed",
}

export default function DashboardPage() {
  const qc = useQueryClient()
  const router = useRouter()
  const { data, error, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => apiGet<DashboardSummary>("/dashboard/summary") })
  const batch = useMutation({
    mutationFn: () => apiSend<{ run_ids: string[]; count: number }>("POST", "/agent/runs/batch", { levels: ["critical"], limit: 5 }),
    onSuccess: (r) => {
      toast.success(`Agent started on ${r.count} critical deals`, { description: "Runs execute one after another; follow progress in Agent Runs." })
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

  if (isLoading) return <LoadingBlock rows={8} />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  const k = data.kpis
  const synthetic = data.data_provenance === "synthetic_demo"
  const levelData = LEVELS.map((l) => ({ level: RISK_STYLE[l].label, key: l, revenue: data.risk_distribution[l].deal_value, count: data.risk_distribution[l].count }))
  const reasonData = Object.entries(data.risk_reasons)
    .slice(0, 7)
    .map(([code, v]) => ({ reason: REASON_LABEL[code] ?? titleCase(code), revenue: v.revenue_at_risk, count: v.count }))

  return (
    <>
      <PageHeader
        eyebrow={<span className="flex items-center gap-2">Revenue overview {synthetic ? <Provenance kind="synthetic" /> : <Provenance kind="observed" />}</span>}
        title="Where revenue is leaking — and what to do next"
        description={`Deterministic risk engine over ${formatNumber(Object.values(data.risk_distribution).reduce((a, b) => a + b.count, 0))} open deals · last computed ${timeAgo(data.risk_computed_at)}`}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => recompute.mutate()} disabled={recompute.isPending}>
              {recompute.isPending ? <Loader2 className="animate-spin" /> : <RefreshCcw />} Recompute risk
            </Button>
            <Button size="sm" onClick={() => batch.mutate()} disabled={batch.isPending || !k.critical_opportunities}>
              {batch.isPending ? <Loader2 className="animate-spin" /> : <Bot />} Run agent on top critical deals
            </Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <KpiCard
          label="Revenue at risk (high + critical)"
          value={formatMoneyCompact(k.revenue_at_risk)}
          hint={`${formatMoneyCompact(k.weighted_revenue_at_risk)} probability-weighted · of ${formatMoneyCompact(k.open_pipeline_value)} open pipeline`}
          icon={ShieldAlert}
          tone="critical"
        />
        <KpiCard
          label="Revenue recovered"
          value={formatMoneyCompact(k.revenue_recovered)}
          hint={k.recovered_deals ? `${k.recovered_deals} deals won after a recovery action` : "Attributed when a deal is won after an executed recovery action"}
          icon={BadgeIndianRupee}
          tone="success"
          footer={<Provenance kind="observed" />}
        />
        <KpiCard
          label="High-risk opportunities"
          value={formatNumber(k.high_risk_opportunities)}
          hint={`${k.critical_opportunities} critical`}
          icon={TrendingUp}
          tone="warning"
          footer={
            <Button asChild size="sm" variant="link" className="h-auto p-0">
              <Link href="/risks">Review risks →</Link>
            </Button>
          }
        />
        <KpiCard
          label="Overdue follow-ups"
          value={formatNumber(k.overdue_followups)}
          hint={`${k.unanswered_leads} new leads unanswered for 4h+`}
          icon={CalendarClock}
          tone="warning"
        />
        <KpiCard
          label="AI actions"
          value={formatNumber(k.ai_actions)}
          hint={`${k.ai_recommendations} recommendations generated`}
          icon={Sparkles}
          tone="primary"
        />
        <KpiCard
          label="Automation success rate"
          value={k.automation_success_rate === null ? "—" : formatPercent(k.automation_success_rate, 1)}
          hint={k.automation_success_rate === null ? "No automated actions executed yet" : "Succeeded / (succeeded + failed) automated actions"}
          icon={ClipboardCheck}
          footer={
            k.pending_approvals ? (
              <Button asChild size="sm" variant="link" className="h-auto p-0">
                <Link href="/approvals">{k.pending_approvals} awaiting approval →</Link>
              </Button>
            ) : null
          }
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Pipeline by risk level</CardTitle>
            <CardDescription>Open deal value per level (count in tooltip)</CardDescription>
          </CardHeader>
          <CardContent>
            <ChartContainer config={levelChart} className="h-64 w-full">
              <BarChart data={levelData} margin={{ left: 8, right: 8 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="level" tickLine={false} axisLine={false} />
                <YAxis tickFormatter={(v) => formatMoneyCompact(v)} width={70} tickLine={false} axisLine={false} />
                <ChartTooltip
                  content={<ChartTooltipContent formatter={(v, _n, item) => `${formatMoneyCompact(Number(v))} · ${item.payload.count} deals`} />}
                />
                <Bar dataKey="revenue" radius={6}>
                  {levelData.map((d) => (
                    <Cell key={d.key} fill={`var(--risk-${d.key})`} />
                  ))}
                </Bar>
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Why revenue is at risk</CardTitle>
            <CardDescription>Reason codes on high + critical deals, by deal value affected</CardDescription>
          </CardHeader>
          <CardContent>
            {reasonData.length ? (
              <ChartContainer config={reasonChart} className="h-64 w-full">
                <BarChart data={reasonData} layout="vertical" margin={{ left: 24, right: 16 }}>
                  <CartesianGrid horizontal={false} />
                  <XAxis type="number" tickFormatter={(v) => formatMoneyCompact(v)} tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="reason" width={150} tickLine={false} axisLine={false} />
                  <ChartTooltip content={<ChartTooltipContent formatter={(v, _n, item) => `${formatMoneyCompact(Number(v))} · ${item.payload.count} deals`} />} />
                  <Bar dataKey="revenue" fill="var(--color-revenue)" radius={5} />
                </BarChart>
              </ChartContainer>
            ) : (
              <EmptyState title="No high-risk deals" />
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="space-y-1">
            <CardTitle>Act today</CardTitle>
            <CardDescription>Highest-risk open deals with the deterministic next step</CardDescription>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link href="/risks">All risks</Link>
          </Button>
        </CardHeader>
        <CardContent className="px-0">
          {data.top_risks.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Customer</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead className="w-56">Risk</TableHead>
                  <TableHead>Top reasons</TableHead>
                  <TableHead>Next step</TableHead>
                  <TableHead className="pr-6 text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.top_risks.map((r) => (
                  <TableRow key={r.risk_id}>
                    <TableCell className="pl-6">
                      <Link href={`/customers/${r.customer_id}`} className="font-medium hover:underline">
                        {r.customer_name}
                      </Link>
                      <div className="text-xs text-muted-foreground">
                        {titleCase(r.stage)} · {r.owner}
                      </div>
                    </TableCell>
                    <TableCell className="tabular">{formatMoneyCompact(r.revenue_at_risk)}</TableCell>
                    <TableCell className="min-w-48">
                      <div className="space-y-1.5">
                        <RiskBadge level={r.risk_level} />
                        <RiskMeter score={r.risk_score} level={r.risk_level} />
                      </div>
                    </TableCell>
                    <TableCell className="max-w-64 text-xs text-muted-foreground whitespace-normal">
                      {r.reasons.slice(0, 3).map((x) => x.label).join(" · ")}
                    </TableCell>
                    <TableCell className="max-w-56 text-sm whitespace-normal">{r.recommended_next_step}</TableCell>
                    <TableCell className="pr-6 text-right">
                      <RunAgentButton opportunityId={r.opportunity_id} variant="outline" label="Investigate" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState title="No high-risk deals right now" description="Load the demo dataset or import your CRM data." />
          )}
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Follow-up discipline by sales rep</CardTitle>
          <CardDescription>High + critical revenue at risk and overdue follow-up tasks per owner</CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-6">Sales rep</TableHead>
                <TableHead className="text-right">At-risk deals</TableHead>
                <TableHead className="text-right">Revenue at risk</TableHead>
                <TableHead className="pr-6 text-right">Overdue follow-ups</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.reps.map((r) => (
                <TableRow key={r.owner}>
                  <TableCell className="pl-6 font-medium">{r.owner}</TableCell>
                  <TableCell className="text-right tabular">{r.at_risk_deals}</TableCell>
                  <TableCell className="text-right tabular">{formatMoneyCompact(r.revenue_at_risk)}</TableCell>
                  <TableCell className="pr-6 text-right tabular">
                    <span className={r.overdue_followups >= 10 ? "font-semibold text-risk-critical" : ""}>{r.overdue_followups}</span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  )
}
