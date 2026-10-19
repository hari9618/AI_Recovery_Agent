"use client"

import { useQuery } from "@tanstack/react-query"
import { ExternalLink, Loader2 } from "lucide-react"
import Link from "next/link"
import { useParams } from "next/navigation"

import { ApprovalActions } from "@/components/agent/approval-actions"
import { RecommendationPanel } from "@/components/agent/recommendation-panel"
import { RUN_STATUS } from "@/components/agent/run-status"
import { RunTimeline } from "@/components/agent/run-timeline"
import { RiskBadge, RiskMeter } from "@/components/risk/risk"
import { PageHeader } from "@/components/shared/page-header"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { apiGet } from "@/lib/api"
import { formatMoney, formatMs, formatNumber, timeAgo } from "@/lib/format"
import type { AgentRun } from "@/lib/types"


export default function AgentRunPage() {
  const { id } = useParams<{ id: string }>()
  const { data: run, error, isLoading } = useQuery({
    queryKey: ["agent-run", id],
    queryFn: () => apiGet<AgentRun>(`/agent/runs/${id}`),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1200 : false),
  })
  if (isLoading) return <LoadingBlock rows={8} />
  if (error) return <ErrorState error={error} />
  if (!run) return null
  const running = run.status === "running"
  const risk = run.state?.risk_analysis
  const s = RUN_STATUS[run.status]

  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/agent-runs" className="hover:underline">
            Agent runs
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-3">
            Revenue recovery · {run.customer_name ?? "—"}
            <Badge variant="outline" className={s.className}>
              {running ? <Loader2 className="size-3 animate-spin" /> : null}
              {s.label}
            </Badge>
          </span>
        }
        description={`Started ${timeAgo(run.created_at)} · run ${run.id.slice(0, 8)}`}
        actions={
          <>
            {run.customer_id ? (
              <Button asChild variant="outline" size="sm">
                <Link href={`/customers/${run.customer_id}`}>Customer</Link>
              </Button>
            ) : null}
            {run.trace_url ? (
              <Button asChild size="sm" variant="outline">
                <a href={run.trace_url} target="_blank" rel="noreferrer">
                  <ExternalLink /> Langfuse trace
                </a>
              </Button>
            ) : null}
          </>
        }
      />
      {run.error ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Run ended with an error</AlertTitle>
          <AlertDescription>{run.error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Workflow</CardTitle>
            <CardDescription>Explicit LangGraph state machine — no open-ended agent loop</CardDescription>
          </CardHeader>
          <CardContent>
            <RunTimeline steps={run.steps} finished={!running} />
          </CardContent>
        </Card>
        <div className="space-y-4 lg:col-span-2">
          {risk ? (
            <Card>
              <CardHeader className="flex flex-row flex-wrap items-center gap-3">
                <RiskBadge level={risk.risk_level} />
                <span className="text-lg font-semibold tabular">{formatMoney(risk.revenue_at_risk)} at risk</span>
                <RiskMeter score={risk.risk_score} level={risk.risk_level} className="min-w-48 flex-1" />
              </CardHeader>
            </Card>
          ) : null}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              ["LLM calls", formatNumber(run.llm_calls)],
              ["Tokens", formatNumber(run.input_tokens + run.output_tokens)],
              ["Est. cost", `$${run.cost_usd.toFixed(4)}`],
              ["Latency", formatMs(run.latency_ms)],
            ].map(([label, value]) => (
              <Card key={label} className="gap-1 py-3">
                <CardContent className="px-4">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="font-semibold tabular">{running ? "…" : value}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          {run.state?.retrieval_queries?.length ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Knowledge queries (planned deterministically from risk reasons)</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {run.state.retrieval_queries.map((q) => (
                  <Badge key={q.query} variant="outline" className="max-w-full whitespace-normal text-left font-normal" title={q.query}>
                    <span className="font-medium">{q.reason}</span>&nbsp;→ {q.doc_types.join(", ")}
                  </Badge>
                ))}
                {run.state.withheld_evidence?.length ? (
                  <Badge variant="outline" className="border-warning/50 bg-warning/10">
                    {run.state.withheld_evidence.length} passage(s) withheld: possible prompt injection
                  </Badge>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
          {run.approval && run.recommendation && run.approval.status === "pending" ? (
            <Card className="border-warning/50">
              <CardHeader>
                <CardTitle>Human approval required</CardTitle>
                <CardDescription>
                  Requires role <span className="font-medium capitalize">{run.approval.required_role.replace("_", " ")}</span> or higher. {run.approval.risk_summary}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ApprovalActions approval={run.approval} rec={run.recommendation} />
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      <div className="mt-6">
        {run.recommendation ? (
          <RecommendationPanel rec={run.recommendation} />
        ) : running ? (
          <LoadingBlock rows={3} />
        ) : run.status === "completed" ? (
          <EmptyState title="No action needed" description="The deterministic risk engine rated this deal low risk, so no recommendation was generated." />
        ) : null}
      </div>
      {run.state?.execution_result ? (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Execution & verification</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <ul className="space-y-2 text-sm">
              {run.state.execution_result.results?.map((r, i) => (
                <li key={i} className="rounded-lg border p-3">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs">{r.tool}</span>
                    <Badge variant="outline" className={r.ok ? "text-success" : "text-destructive"}>
                      {r.ok ? "succeeded" : "failed"}
                    </Badge>
                  </div>
                  <pre className="mt-2 overflow-auto text-xs text-muted-foreground">{JSON.stringify(r.data?.detail ?? r.error, null, 2)}</pre>
                </li>
              ))}
            </ul>
            <ul className="space-y-1.5 text-sm">
              {run.state.verification_result?.checks?.map((c) => (
                <li key={c.check} className={c.passed ? "text-success" : "text-destructive"}>
                  {c.passed ? "✓" : "✗"} {c.check}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </>
  )
}
