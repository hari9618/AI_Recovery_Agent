"use client"

import { useQuery } from "@tanstack/react-query"
import {
  Building2,
  CalendarClock,
  CheckCircle2,
  FileText,
  Mail,
  MessagesSquare,
  Phone,
  Sparkles,
  Swords,
  Target,
  UserRound,
} from "lucide-react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { useState } from "react"

import { RecommendationPanel, RecommendationStatus } from "@/components/agent/recommendation-panel"
import { RunAgentButton } from "@/components/agent/run-agent-button"
import { ReasonList, RiskBadge, RiskMeter, RISK_STYLE } from "@/components/risk/risk"
import { AuditTable } from "@/components/shared/audit-table"
import { PageHeader } from "@/components/shared/page-header"
import { Provenance, sourceKind } from "@/components/shared/provenance"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { apiGet } from "@/lib/api"
import { formatDate, formatDateTime, formatMoney, formatMoneyCompact, formatPercent, timeAgo, titleCase } from "@/lib/format"
import type { CustomerProfile } from "@/lib/types"
import { cn } from "@/lib/utils"

function Field({ label, children, icon: Icon }: { label: string; children: React.ReactNode; icon?: React.ComponentType<{ className?: string }> }) {
  return (
    <div className="space-y-1">
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {Icon ? <Icon className="size-3.5" /> : null}
        {label}
      </p>
      <div className="text-sm font-medium">{children}</div>
    </div>
  )
}

const INTENT_STYLE: Record<string, string> = {
  high: "bg-success/12 text-success border-success/30",
  medium: "bg-warning/15 text-foreground border-warning/40",
  low: "bg-muted text-muted-foreground",
}

export default function CustomerDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [tab, setTab] = useState("overview")
  const { data, error, isLoading } = useQuery({ queryKey: ["customer", id], queryFn: () => apiGet<CustomerProfile>(`/customers/${id}`) })
  if (isLoading) return <LoadingBlock rows={10} />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  const { customer: c, summary: s } = data
  const risk = [...data.risks].sort((a, b) => b.risk_score - a.risk_score)[0]
  const openOpp = data.opportunities.find((o) => risk && o.id === risk.opportunity_id) ?? data.opportunities.find((o) => !o.stage.startsWith("closed"))
  const latestRec = data.recommendations[0]

  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/customers" className="hover:underline">
            Customers
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-3">
            {c.name}
            {c.is_synthetic ? <Provenance kind="synthetic" /> : null}
          </span>
        }
        description={`${c.industry} · ${titleCase(c.segment)} · ${c.city ?? ""}${c.state ? `, ${c.state}` : ""} · owner ${c.owner ?? "—"}`}
        actions={openOpp ? <RunAgentButton opportunityId={openOpp.id} /> : null}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="size-4 text-primary" /> Customer intelligence
            </CardTitle>
            <CardDescription>Numbers from PostgreSQL and the risk engine; intent and objections from conversation analysis</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-5 md:grid-cols-4">
            <Field label="Deal value" icon={Target}>
              {formatMoney(s.deal_value)}
            </Field>
            <Field label="Lead stage">{titleCase(s.lead_stage)}</Field>
            <Field label="Intent">
              <span className="flex flex-wrap items-center gap-1.5">
                <Badge variant="outline" className={cn("capitalize", INTENT_STYLE[s.intent])}>
                  {s.intent}
                </Badge>
                <Provenance kind={sourceKind(s.intent_source)} />
              </span>
            </Field>
            <Field label="Purchase probability">{formatPercent(s.purchase_probability)}</Field>
            <Field label="Revenue risk">
              <RiskBadge level={s.revenue_risk} score={s.risk_score} />
            </Field>
            <Field label="Last contact" icon={CalendarClock}>
              {s.last_contact_days === null ? "—" : `${Math.floor(s.last_contact_days)} days ago`}
            </Field>
            <Field label="Last quote" icon={FileText}>
              {s.last_quote_value ? `${formatMoney(s.last_quote_value)} · ${s.last_quote_status}` : "—"}
            </Field>
            <Field label="Main objection">{s.main_objection ? titleCase(s.main_objection) : "None detected"}</Field>
            <Field label="Competitor mention" icon={Swords}>
              {s.competitor_mentioned ? `Yes${s.competitors[0]?.name && s.competitors[0].name !== "unnamed" ? ` — ${s.competitors[0].name}` : ""}` : "No"}
            </Field>
            <Field label="Open pipeline">{formatMoneyCompact(s.open_pipeline_value)}</Field>
            <div className="col-span-2">
              <Field label="Recommended action">{s.recommended_action ?? "—"}</Field>
            </div>
            {s.ai_summary ? (
              <div className="col-span-2 md:col-span-4">
                <Field label="AI summary of the conversation">
                  <span className="font-normal">{s.ai_summary}</span>
                </Field>
              </div>
            ) : null}
          </CardContent>
        </Card>

        {risk ? (
          <Card className={cn("border-2", risk.risk_level === "critical" && "border-risk-critical/40")}>
            <CardHeader className="gap-2">
              <RiskBadge level={risk.risk_level} className="w-fit text-sm" />
              <div>
                <div className={cn("text-3xl font-semibold tracking-tight tabular", RISK_STYLE[risk.risk_level].text)}>
                  {formatMoney(risk.revenue_at_risk)}
                </div>
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">at risk</p>
              </div>
              <RiskMeter score={risk.risk_score} level={risk.risk_level} />
            </CardHeader>
            <CardContent className="space-y-4">
              <ul className="space-y-1.5">
                {risk.reason_codes.slice(0, 5).map((r) => (
                  <li key={r.code} className="flex items-start gap-2 text-sm">
                    <CheckCircle2 className={cn("mt-0.5 size-4 shrink-0", RISK_STYLE[risk.risk_level].text)} />
                    {r.label}
                  </li>
                ))}
              </ul>
              <div className="rounded-lg bg-muted/60 p-3">
                <p className="text-xs text-muted-foreground">Recommended</p>
                <p className="text-sm font-medium">{risk.recommended_next_step}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => setTab("risk")}>
                  View evidence
                </Button>
                <RunAgentButton opportunityId={risk.opportunity_id} variant="default" label="Generate message & request approval" />
              </div>
              <p className="text-[11px] text-muted-foreground">
                Engine {risk.engine_version} · computed {timeAgo(risk.computed_at)}
              </p>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="py-10">
              <EmptyState title="No open deal at risk" description="Risk is only assessed for open opportunities." />
            </CardContent>
          </Card>
        )}
      </div>

      <Tabs value={tab} onValueChange={setTab} className="mt-6">
        <TabsList className="flex-wrap">
          <TabsTrigger value="overview">Timeline</TabsTrigger>
          <TabsTrigger value="conversations">Conversations ({data.conversations.length})</TabsTrigger>
          <TabsTrigger value="quotes">Quotes ({data.quotes.length})</TabsTrigger>
          <TabsTrigger value="opportunities">Opportunities ({data.opportunities.length})</TabsTrigger>
          <TabsTrigger value="risk">Revenue risk</TabsTrigger>
          <TabsTrigger value="ai">AI insights ({data.recommendations.length})</TabsTrigger>
          <TabsTrigger value="evidence">Knowledge evidence</TabsTrigger>
          <TabsTrigger value="audit">Audit</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-4 grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Activity timeline</CardTitle>
            </CardHeader>
            <CardContent>
              {data.timeline.length ? (
                <ol className="space-y-3">
                  {data.timeline.map((a) => (
                    <li key={a.id} className="flex gap-3">
                      <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", a.type === "ai_action" ? "bg-primary" : "bg-muted-foreground/40")} />
                      <div>
                        <p className="text-sm">{a.description}</p>
                        <p className="text-xs text-muted-foreground">
                          {titleCase(a.type)} · {formatDateTime(a.occurred_at)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <EmptyState title="No activity yet" />
              )}
            </CardContent>
          </Card>
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Contacts</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {data.contacts.map((p) => (
                  <div key={p.id} className="flex items-start gap-3">
                    <UserRound className="mt-0.5 size-4 text-muted-foreground" />
                    <div className="min-w-0 text-sm">
                      <p className="font-medium">
                        {p.name} {p.is_decision_maker ? <Badge variant="secondary" className="ml-1 text-[10px]">decision maker</Badge> : null}
                      </p>
                      <p className="text-xs text-muted-foreground">{p.title}</p>
                      {p.email ? (
                        <p className="flex items-center gap-1 truncate text-xs text-muted-foreground">
                          <Mail className="size-3" /> {p.email}
                        </p>
                      ) : null}
                      {p.phone ? (
                        <p className="flex items-center gap-1 text-xs text-muted-foreground">
                          <Phone className="size-3" /> {p.phone}
                        </p>
                      ) : null}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Follow-ups</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.followups.length ? (
                  data.followups.map((f) => (
                    <div key={f.id} className="flex items-start justify-between gap-2 text-sm">
                      <div>
                        <p>{f.title}</p>
                        <p className="text-xs text-muted-foreground">
                          due {formatDate(f.due_at)} {f.created_by_agent ? "· created by agent" : ""}
                        </p>
                      </div>
                      <Badge
                        variant="outline"
                        className={cn(f.overdue && "border-risk-critical/40 bg-risk-critical/10 text-risk-critical", f.status === "completed" && "text-success")}
                      >
                        {f.overdue ? "overdue" : f.status}
                      </Badge>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground">None</p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Building2 className="size-4" /> Account
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                <p>Status: <span className="capitalize">{c.status}</span></p>
                <p>Employees: {c.employee_count ?? "—"}</p>
                <p>Lifetime value: {formatMoney(c.lifetime_value)}</p>
                {c.website ? <p className="truncate text-muted-foreground">{c.website}</p> : null}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="conversations" className="mt-4 space-y-3">
          {data.conversations.length ? (
            data.conversations.map((cv) => (
              <Card key={cv.id} className="py-4">
                <CardContent className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div className="min-w-0">
                    <Link href={`/conversations/${cv.id}`} className="font-medium hover:underline">
                      <MessagesSquare className="mr-1.5 inline size-4 text-muted-foreground" />
                      {cv.subject ?? "Conversation"}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      {titleCase(cv.channel)} · {cv.message_count} messages · last {timeAgo(cv.last_message_at)} by {cv.last_sender}
                    </p>
                    {cv.analysis?.summary ? <p className="mt-1 text-sm">{cv.analysis.summary}</p> : null}
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <Provenance kind={cv.analysis?.source === "llm_analysis" ? "ai" : "heuristic"} />
                    {cv.analysis?.intent ? <Badge variant="outline" className={cn("capitalize", INTENT_STYLE[cv.analysis.intent])}>intent {cv.analysis.intent}</Badge> : null}
                  </div>
                </CardContent>
              </Card>
            ))
          ) : (
            <EmptyState title="No conversations" />
          )}
        </TabsContent>

        <TabsContent value="quotes" className="mt-4 space-y-4">
          {data.quotes.length ? (
            data.quotes.map((q) => (
              <Card key={q.id}>
                <CardHeader className="flex flex-row flex-wrap items-center gap-3">
                  <CardTitle className="font-mono text-base">{q.quote_number}</CardTitle>
                  <Badge variant="outline" className="capitalize">{q.status}</Badge>
                  {q.version > 1 ? <Badge variant="secondary">v{q.version}</Badge> : null}
                  <span className="ml-auto text-sm">
                    {q.discount_pct ? <span className="mr-2 text-muted-foreground">−{q.discount_pct}%</span> : null}
                    <span className="font-semibold tabular">{formatMoney(q.total)}</span>
                  </span>
                </CardHeader>
                <CardContent className="px-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-6">Item</TableHead>
                        <TableHead className="text-right">Qty</TableHead>
                        <TableHead className="text-right">Unit</TableHead>
                        <TableHead className="pr-6 text-right">Total</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {q.items.map((i) => (
                        <TableRow key={i.sku + i.description}>
                          <TableCell className="pl-6">
                            <span className="font-mono text-xs text-muted-foreground">{i.sku}</span> {i.description}
                          </TableCell>
                          <TableCell className="text-right tabular">{i.quantity}</TableCell>
                          <TableCell className="text-right tabular">{formatMoney(i.unit_price)}</TableCell>
                          <TableCell className="pr-6 text-right tabular">{formatMoney(i.line_total)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <p className="px-6 pt-3 text-xs text-muted-foreground">
                    Sent {formatDate(q.sent_at)} · valid until {formatDate(q.valid_until)} · totals exclude GST
                  </p>
                </CardContent>
              </Card>
            ))
          ) : (
            <EmptyState title="No quotations" />
          )}
        </TabsContent>

        <TabsContent value="opportunities" className="mt-4">
          <Card className="py-0">
            <CardContent className="px-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-6">Opportunity</TableHead>
                    <TableHead>Stage</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                    <TableHead>Expected close</TableHead>
                    <TableHead className="pr-6">Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.opportunities.map((o) => (
                    <TableRow key={o.id}>
                      <TableCell className="pl-6 font-medium">{o.name}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{titleCase(o.stage)}</Badge>
                      </TableCell>
                      <TableCell className="text-right tabular">{formatMoney(o.amount)}</TableCell>
                      <TableCell>{formatDate(o.expected_close_date)}</TableCell>
                      <TableCell className="pr-6 text-sm text-muted-foreground">{o.loss_reason ?? (o.competitor ? `Competitor: ${o.competitor}` : "")}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="risk" className="mt-4">
          {data.risks.length ? (
            data.risks.map((r) => (
              <Card key={r.id}>
                <CardHeader>
                  <CardTitle className="flex flex-wrap items-center gap-3">
                    <RiskBadge level={r.risk_level} score={r.risk_score} />
                    <span className="text-base">{formatMoney(r.revenue_at_risk)} at risk</span>
                    <span className="text-sm font-normal text-muted-foreground">
                      purchase probability {formatPercent(r.purchase_probability)} (stage base {formatPercent(r.signals.probability_breakdown?.stage_base)} ×
                      calibration {r.signals.probability_breakdown?.historical_calibration} × intent {r.signals.probability_breakdown?.intent_multiplier})
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="grid gap-6 md:grid-cols-3">
                  <div className="md:col-span-2">
                    <ReasonList reasons={r.reason_codes} />
                  </div>
                  <div className="space-y-1 text-xs text-muted-foreground">
                    <p className="font-semibold uppercase tracking-wide">Measured signals</p>
                    {Object.entries(r.signals)
                      .filter(([k, v]) => !["evidence", "probability_breakdown"].includes(k) && v !== null && v !== "" && !(Array.isArray(v) && !v.length))
                      .map(([k, v]) => (
                        <p key={k} className="flex justify-between gap-2">
                          <span>{titleCase(k)}</span>
                          <span className="font-mono text-foreground">{typeof v === "number" ? Math.round(v * 10) / 10 : String(v)}</span>
                        </p>
                      ))}
                  </div>
                </CardContent>
              </Card>
            ))
          ) : (
            <EmptyState title="No current risk assessment" />
          )}
        </TabsContent>

        <TabsContent value="ai" className="mt-4 space-y-4">
          {latestRec ? (
            <>
              <RecommendationPanel rec={latestRec} />
              {data.recommendations.slice(1).map((r) => (
                <Card key={r.id} className="py-4">
                  <CardContent className="flex items-center justify-between gap-3">
                    <Link href={`/recommendations/${r.id}`} className="font-medium hover:underline">
                      {r.title}
                    </Link>
                    <RecommendationStatus status={r.status} />
                  </CardContent>
                </Card>
              ))}
            </>
          ) : (
            <EmptyState
              icon={Sparkles}
              title="No AI recommendation yet"
              description="Run the recovery agent to analyse the conversation, retrieve policy and draft a next step."
              action={openOpp ? <RunAgentButton opportunityId={openOpp.id} /> : null}
            />
          )}
        </TabsContent>

        <TabsContent value="evidence" className="mt-4">
          {latestRec?.evidence.some((e) => e.kind === "knowledge") ? (
            <div className="grid gap-3 md:grid-cols-2">
              {latestRec.evidence
                .filter((e) => e.kind === "knowledge")
                .map((e) => (
                  <Card key={e.evidence_id} className={cn("py-4", e.cited && "border-primary/40")}>
                    <CardContent className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <Badge variant="secondary" className="font-mono">{e.evidence_id}</Badge>
                        <span className="font-medium">{e.source_document}</span>
                        <span className="text-muted-foreground">› {e.source_section}</span>
                        {e.cited ? <Badge>cited</Badge> : null}
                      </div>
                      <p className="whitespace-pre-line text-sm text-muted-foreground">{e.quote}</p>
                      <p className="text-xs text-muted-foreground tabular">relevance {e.retrieval_score?.toFixed(3)}</p>
                    </CardContent>
                  </Card>
                ))}
            </div>
          ) : (
            <EmptyState title="No knowledge evidence yet" description="Evidence appears after the agent retrieves policies for this deal." />
          )}
        </TabsContent>

        <TabsContent value="audit" className="mt-4">
          <AuditTable entries={data.audit} />
        </TabsContent>
      </Tabs>
    </>
  )
}
