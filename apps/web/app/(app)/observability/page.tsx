"use client"

import { useQuery } from "@tanstack/react-query"
import { Activity, CircleCheck, CircleSlash, ExternalLink } from "lucide-react"
import Link from "next/link"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"

import { KpiCard } from "@/components/shared/kpi-card"
import { PageHeader } from "@/components/shared/page-header"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiGet } from "@/lib/api"
import { formatDateTime, formatMs, formatNumber, formatPercent, titleCase } from "@/lib/format"

interface Usage {
  window_days: number
  totals: { llm_calls: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number; failure_rate: number | null }
  by_purpose: { purpose: string; model: string; status: string; calls: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number; p50_latency_ms: number; p95_latency_ms: number }[]
  daily: { day: string; calls: number; tokens: number; estimated_cost_usd: number }[]
  agent_runs: { status: string; count: number; avg_latency_ms: number; cost_usd: number }[]
  recent_runs: { id: string; status: string; created_at: string; latency_ms: number | null; llm_calls: number; tokens: number; cost_usd: number; trace_id: string | null; trace_url: string | null }[]
}
interface Status {
  langfuse: { enabled: boolean; reachable: boolean | null; reason?: string; host?: string | null }
  llm: { configured: boolean; model: string | null }
}
const chart = { tokens: { label: "Tokens", color: "var(--chart-1)" } } satisfies ChartConfig

const STEPS = [
  "Open Langfuse (the host above) and select your project.",
  "Tracing → Traces → filter by name “RevenueRecovery” (or open a run's “Langfuse trace” link).",
  "The trace tree shows each workflow node: load_context, conversation_analysis (with its groq:conversation_analysis generation), assess_risk, hybrid_retrieval (bm25 · vector · rerank), recommend, ground_check, policy_check, persist_recommendation and every tool:* call.",
  "Click a generation to see the exact prompt, model, parameters, token usage and estimated cost.",
  "Click hybrid_retrieval to see candidates, fusion and reranker scores; tool spans show validated inputs/outputs.",
  "The timeline view shows latency per step; scores (grounding_score, recommendation_confidence, eval_*_passed) appear on the trace.",
  "After approval, a second trace “RevenueRecovery.execute” in the same session holds the human-approved execution and verification.",
]

export default function ObservabilityPage() {
  const status = useQuery({ queryKey: ["obs-status"], queryFn: () => apiGet<Status>("/observability/status") })
  const usage = useQuery({ queryKey: ["obs-usage"], queryFn: () => apiGet<Usage>("/observability/usage", { days: 30 }) })
  const lf = status.data?.langfuse
  return (
    <>
      <PageHeader
        title="Observability"
        description="Langfuse traces every agent run, generation, retrieval step and tool call. Usage below comes from the local ledger, so cost and latency stay visible even when Langfuse is off."
      />
      {status.error ? <ErrorState error={status.error} /> : null}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Langfuse
              {lf?.enabled ? (
                lf.reachable ? (
                  <Badge className="bg-success/15 text-success">
                    <CircleCheck className="size-3" /> connected
                  </Badge>
                ) : (
                  <Badge variant="outline" className="border-destructive/40 text-destructive">
                    unreachable
                  </Badge>
                )
              ) : (
                <Badge variant="outline">
                  <CircleSlash className="size-3" /> not configured
                </Badge>
              )}
            </CardTitle>
            <CardDescription>
              {lf?.enabled ? lf.host : "Set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST in .env. The app runs normally without it."}
              {lf?.reason ? ` · ${lf.reason}` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>
              LLM: {status.data?.llm.configured ? <span className="font-medium">{status.data.llm.model}</span> : <span className="text-muted-foreground">not configured</span>}
            </p>
            {lf?.enabled && lf.host ? (
              <a href={lf.host} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                Open Langfuse <ExternalLink className="size-3" />
              </a>
            ) : null}
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>How to inspect a recovery trace</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="list-decimal space-y-1.5 pl-5 text-sm">
              {STEPS.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>

      {usage.isLoading ? <LoadingBlock rows={4} className="mt-6 space-y-3" /> : null}
      {usage.data ? (
        <>
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard label="LLM calls (30 days)" value={formatNumber(usage.data.totals.llm_calls)} icon={Activity} tone="primary" />
            <KpiCard label="Tokens" value={formatNumber(usage.data.totals.input_tokens + usage.data.totals.output_tokens)} hint={`${formatNumber(usage.data.totals.input_tokens)} in · ${formatNumber(usage.data.totals.output_tokens)} out`} />
            <KpiCard label="Estimated LLM cost" value={`$${usage.data.totals.estimated_cost_usd.toFixed(4)}`} hint="From published per-token prices; provider invoice is authoritative" />
            <KpiCard
              label="Failure / fallback rate"
              value={usage.data.totals.failure_rate === null ? "—" : formatPercent(usage.data.totals.failure_rate, 1)}
              hint="Calls that errored or fell back after invalid structured output"
            />
          </div>
          <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Daily tokens</CardTitle>
              </CardHeader>
              <CardContent>
                {usage.data.daily.length ? (
                  <ChartContainer config={chart} className="h-56 w-full">
                    <BarChart data={usage.data.daily}>
                      <CartesianGrid vertical={false} />
                      <XAxis dataKey="day" tickLine={false} axisLine={false} />
                      <YAxis tickLine={false} axisLine={false} width={60} />
                      <ChartTooltip content={<ChartTooltipContent />} />
                      <Bar dataKey="tokens" fill="var(--color-tokens)" radius={4} />
                    </BarChart>
                  </ChartContainer>
                ) : (
                  <EmptyState title="No LLM calls recorded yet" description="Configure Groq and run the agent or analyse a conversation." />
                )}
              </CardContent>
            </Card>
            <Card className="py-0">
              <CardHeader className="pt-6">
                <CardTitle>Latency & cost by step</CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                {usage.data.by_purpose.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-6">Purpose</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="text-right">Calls</TableHead>
                        <TableHead className="text-right">p50</TableHead>
                        <TableHead className="text-right">p95</TableHead>
                        <TableHead className="pr-6 text-right">Cost</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {usage.data.by_purpose.map((p) => (
                        <TableRow key={p.purpose + p.status + p.model}>
                          <TableCell className="pl-6 text-sm">{titleCase(p.purpose)}</TableCell>
                          <TableCell>
                            <Badge variant="outline">{p.status}</Badge>
                          </TableCell>
                          <TableCell className="text-right tabular">{p.calls}</TableCell>
                          <TableCell className="text-right tabular">{formatMs(p.p50_latency_ms)}</TableCell>
                          <TableCell className="text-right tabular">{formatMs(p.p95_latency_ms)}</TableCell>
                          <TableCell className="pr-6 text-right tabular">${p.estimated_cost_usd.toFixed(4)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="p-6">
                    <EmptyState title="No usage yet" />
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
          <Card className="mt-6 py-0">
            <CardHeader className="pt-6">
              <CardTitle>Recent agent runs</CardTitle>
            </CardHeader>
            <CardContent className="px-0">
              {usage.data.recent_runs.length ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="pl-6">Run</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">LLM calls</TableHead>
                      <TableHead className="text-right">Tokens</TableHead>
                      <TableHead className="text-right">Latency</TableHead>
                      <TableHead className="pr-6 text-right">Trace</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {usage.data.recent_runs.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell className="pl-6">
                          <Link href={`/agent-runs/${r.id}`} className="font-mono text-xs hover:underline">
                            {r.id.slice(0, 8)}
                          </Link>
                          <span className="ml-2 text-xs text-muted-foreground">{formatDateTime(r.created_at)}</span>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{titleCase(r.status)}</Badge>
                        </TableCell>
                        <TableCell className="text-right tabular">{r.llm_calls}</TableCell>
                        <TableCell className="text-right tabular">{formatNumber(r.tokens)}</TableCell>
                        <TableCell className="text-right tabular">{formatMs(r.latency_ms)}</TableCell>
                        <TableCell className="pr-6 text-right text-xs">
                          {r.trace_url ? (
                            <a href={r.trace_url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                              open
                            </a>
                          ) : (
                            <span className="text-muted-foreground">{r.trace_id ? r.trace_id.slice(0, 10) : "—"}</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <div className="p-6">
                  <EmptyState title="No runs yet" />
                </div>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}
    </>
  )
}
