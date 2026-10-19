"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, Loader2, RefreshCcw, Sparkles } from "lucide-react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { toast } from "sonner"

import { PageHeader } from "@/components/shared/page-header"
import { Provenance } from "@/components/shared/provenance"
import { ErrorState, LoadingBlock } from "@/components/shared/states"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { apiGet, apiSend, errorMessage } from "@/lib/api"
import { formatDateTime, formatPercent, titleCase } from "@/lib/format"
import type { ConversationInsight } from "@/lib/types"
import { cn } from "@/lib/utils"

interface ConversationDetail {
  id: string
  customer: { id: string; name: string }
  opportunity_id: string | null
  subject: string | null
  channel: string
  is_synthetic: boolean
  messages: { id: string; sender_type: "customer" | "rep" | "system"; sender_name: string; body: string; sent_at: string }[]
  analysis: (ConversationInsight & { status: string; model: string; created_at: string }) | null
  stale_analysis_exists: boolean
  heuristic: { intent: string; price_objection: boolean; competitor_mentioned: boolean; sentiment: string; evidence: Record<string, string> }
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  )
}

export default function ConversationPage() {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()
  const { data, error, isLoading } = useQuery({ queryKey: ["conversation", id], queryFn: () => apiGet<ConversationDetail>(`/conversations/${id}`) })
  const analyze = useMutation({
    mutationFn: (force: boolean) => apiSend<{ status: string; cached: boolean; dropped_quotes: string[] }>("POST", `/conversations/${id}/analyze`, undefined, { force }),
    onSuccess: (r) => {
      toast.success(r.cached ? "Cached analysis (transcript unchanged)" : `Analysed · ${r.status}`, {
        description: r.dropped_quotes.length ? `${r.dropped_quotes.length} unverifiable quote(s) removed` : undefined,
      })
      qc.invalidateQueries()
    },
    onError: (e) => toast.error("Analysis failed", { description: errorMessage(e) }),
  })
  if (isLoading) return <LoadingBlock rows={8} />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  const a = data.analysis

  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/conversations" className="hover:underline">
            Conversations
          </Link>
        }
        title={data.subject ?? "Conversation"}
        description={
          <>
            <Link href={`/customers/${data.customer.id}`} className="hover:underline">
              {data.customer.name}
            </Link>{" "}
            · {titleCase(data.channel)} · {data.messages.length} messages
          </>
        }
        actions={
          <>
            {data.is_synthetic ? <Provenance kind="synthetic" /> : null}
            <Button onClick={() => analyze.mutate(Boolean(a))} disabled={analyze.isPending} variant={a ? "outline" : "default"}>
              {analyze.isPending ? <Loader2 className="animate-spin" /> : a ? <RefreshCcw /> : <Sparkles />}
              {a ? "Re-analyse" : "Analyse with AI"}
            </Button>
          </>
        }
      />
      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Transcript</CardTitle>
            <CardDescription>Customer-written text is treated as untrusted data by every AI step.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.messages.map((m) => (
              <div key={m.id} className={cn("flex", m.sender_type === "rep" ? "justify-end" : "justify-start")}>
                <div
                  className={cn(
                    "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm",
                    m.sender_type === "rep" ? "rounded-br-sm bg-primary text-primary-foreground" : "rounded-bl-sm bg-muted",
                  )}
                >
                  <p className={cn("mb-1 text-xs font-medium", m.sender_type === "rep" ? "text-primary-foreground/80" : "text-muted-foreground")}>
                    {m.sender_name} · {formatDateTime(m.sent_at)}
                  </p>
                  <p className="whitespace-pre-line leading-relaxed">{m.body}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
        <div className="space-y-4 lg:col-span-2">
          {a ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2">
                  AI analysis <Provenance kind={a.status === "fallback" ? "rules" : "ai"} />
                </CardTitle>
                <CardDescription>
                  {a.model} · {formatDateTime(a.created_at)} · confidence {formatPercent(a.confidence)}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="mb-3 text-sm">{a.summary}</p>
                <Row label="Intent">
                  <Badge variant="outline" className="capitalize">
                    {a.intent}
                  </Badge>
                </Row>
                <Row label="Buying stage">{titleCase(a.buying_stage)}</Row>
                <Row label="Urgency">{titleCase(a.urgency)}</Row>
                <Row label="Budget signal">{titleCase(a.budget_signal)}</Row>
                <Row label="Sentiment">{titleCase(a.sentiment)}</Row>
                <Row label="Decision maker">{titleCase(a.decision_maker_status)}</Row>
                <Row label="Waiting on us for">{a.customer_waiting_on ?? "—"}</Row>
                <Row label="Next action">{titleCase(a.next_action)}</Row>
                {a.objections.length ? (
                  <div className="mt-4 space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Objections</p>
                    {a.objections.map((o) => (
                      <div key={o.quote} className="rounded-lg border p-2 text-sm">
                        <Badge variant="secondary" className="mb-1 capitalize">
                          {o.type}
                        </Badge>
                        <p>{o.detail}</p>
                        <p className="mt-1 text-xs italic text-muted-foreground">“{o.quote}”</p>
                      </div>
                    ))}
                  </div>
                ) : null}
                {a.competitor_mentions.length ? (
                  <div className="mt-4 space-y-1">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Competitors</p>
                    {a.competitor_mentions.map((c) => (
                      <p key={c.name} className="text-sm">
                        <span className="font-medium">{c.name}</span> — {c.context}
                      </p>
                    ))}
                  </div>
                ) : null}
                {a._dropped_quotes?.length ? (
                  <Alert className="mt-4">
                    <AlertTriangle />
                    <AlertTitle>Unverified quotes removed</AlertTitle>
                    <AlertDescription>{a._dropped_quotes.length} quote(s) from the model did not appear verbatim in the transcript.</AlertDescription>
                  </Alert>
                ) : null}
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  Keyword heuristic <Provenance kind="heuristic" />
                </CardTitle>
                <CardDescription>
                  {data.stale_analysis_exists ? "The transcript changed since the last AI analysis. " : ""}Run “Analyse with AI” for a validated structured analysis.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Row label="Intent">{titleCase(data.heuristic.intent)}</Row>
                <Row label="Price objection">{data.heuristic.price_objection ? "Yes" : "No"}</Row>
                <Row label="Competitor mentioned">{data.heuristic.competitor_mentioned ? "Yes" : "No"}</Row>
                <Row label="Sentiment">{titleCase(data.heuristic.sentiment)}</Row>
                {Object.entries(data.heuristic.evidence).map(([k, v]) => (
                  <p key={k} className="mt-2 border-l-2 pl-2 text-xs italic text-muted-foreground">
                    {titleCase(k.toLowerCase())}: “{v}”
                  </p>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  )
}
