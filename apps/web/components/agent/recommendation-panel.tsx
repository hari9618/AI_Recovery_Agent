import { BookOpen, CheckCircle2, CircleAlert, FileText, MessageSquareQuote, ShieldCheck, TriangleAlert } from "lucide-react"

import { Provenance } from "@/components/shared/provenance"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { formatDateTime, formatPercent, titleCase } from "@/lib/format"
import type { EvidenceItem, Recommendation } from "@/lib/types"
import { cn } from "@/lib/utils"

const STATUS_STYLE: Record<string, string> = {
  pending_approval: "bg-warning/15 text-foreground border-warning/40",
  approved: "bg-primary/10 text-primary border-primary/30",
  executed: "bg-success/12 text-success border-success/30",
  rejected: "bg-muted text-muted-foreground",
  failed: "bg-destructive/10 text-destructive border-destructive/30",
  needs_review: "bg-warning/15 text-foreground border-warning/40",
}

export function RecommendationStatus({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={cn("capitalize", STATUS_STYLE[status])}>
      {status.replace(/_/g, " ")}
    </Badge>
  )
}

function Section({ icon: Icon, title, children }: { icon: React.ComponentType<{ className?: string }>; title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <Icon className="size-3.5" />
        {title}
      </h4>
      <div className="text-sm leading-relaxed">{children}</div>
    </section>
  )
}

function EvidenceRow({ e }: { e: EvidenceItem }) {
  if (e.kind === "knowledge") {
    return (
      <li className={cn("rounded-lg border p-3", e.cited && "border-primary/40 bg-primary/[0.03]")}>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge variant="secondary" className="font-mono text-[10px]">
            {e.evidence_id}
          </Badge>
          <span className="font-medium">{e.source_document}</span>
          <span className="text-muted-foreground">› {e.source_section}</span>
          {e.version ? <span className="text-muted-foreground">v{e.version}</span> : null}
          <span className="ml-auto text-muted-foreground tabular">relevance {e.retrieval_score?.toFixed(2)}</span>
          {e.cited ? <Badge className="text-[10px]">cited</Badge> : null}
        </div>
        {e.quote ? <p className="mt-2 line-clamp-4 whitespace-pre-line text-xs text-muted-foreground">{e.quote}</p> : null}
      </li>
    )
  }
  return (
    <li className="flex items-start gap-2 text-sm">
      {e.kind === "risk_engine" ? (
        <span className="mt-0.5 rounded bg-muted px-1.5 text-[11px] font-semibold tabular">+{e.points}</span>
      ) : (
        <MessageSquareQuote className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      )}
      <div>
        <span>{e.label}</span>
        {e.quote ? <p className="text-xs italic text-muted-foreground">“{e.quote}”</p> : null}
      </div>
    </li>
  )
}

export function RecommendationPanel({ rec }: { rec: Recommendation }) {
  const knowledge = rec.evidence.filter((e) => e.kind === "knowledge")
  const facts = rec.evidence.filter((e) => e.kind !== "knowledge")
  const primary = rec.proposed_action.primary
  const claims = rec.grounding.claims ?? []
  return (
    <Card>
      <CardHeader className="gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <RecommendationStatus status={rec.status} />
          <Provenance kind={rec.generated_by === "rules_fallback" ? "rules" : "ai"} />
          <Badge variant="outline" className="text-[11px]">
            confidence {formatPercent(rec.confidence)}
          </Badge>
          {rec.model ? <span className="text-xs text-muted-foreground">{rec.model}</span> : null}
          <span className="ml-auto text-xs text-muted-foreground">{formatDateTime(rec.created_at)}</span>
        </div>
        <CardTitle className="text-lg leading-snug">{rec.title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-5">
          <Section icon={FileText} title="What happened">
            {rec.what_happened}
          </Section>
          <Section icon={TriangleAlert} title="Why this is risky">
            <p>{rec.why_risky}</p>
            <ul className="mt-2 space-y-1.5">
              {facts.map((e, i) => (
                <EvidenceRow key={i} e={e} />
              ))}
            </ul>
          </Section>
          <Section icon={CheckCircle2} title="What the AI recommends">
            <p>{rec.recommendation}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Badge variant="secondary">{titleCase(rec.action_type)}</Badge>
              {primary?.discount_pct ? <Badge variant="secondary">{primary.discount_pct}% discount</Badge> : null}
              {(rec.proposed_action.internal ?? []).map((a) => (
                <Badge key={a.title} variant="outline" className="text-[11px]">
                  + internal task: {a.title}
                </Badge>
              ))}
            </div>
          </Section>
          <Section icon={ShieldCheck} title="What happens if approved">
            {rec.expected_outcome}
          </Section>
          {rec.requires_approval ? (
            <Section icon={CircleAlert} title="Why human approval is required">
              <ul className="space-y-1.5">
                {rec.approval_reasons.map((r) => (
                  <li key={r.rule} className="flex items-start gap-2">
                    <Badge variant="outline" className="shrink-0 font-mono text-[10px]">
                      {r.rule}
                    </Badge>
                    <span className="text-sm">{r.message}</span>
                  </li>
                ))}
              </ul>
            </Section>
          ) : (
            <Section icon={CircleAlert} title="Approval">
              Low-risk internal action — executed automatically under policy.
            </Section>
          )}
        </div>
        <div className="space-y-5">
          {rec.draft_body ? (
            <Section icon={MessageSquareQuote} title="Draft message (not sent until approved)">
              <div className="rounded-lg border bg-muted/40 p-3">
                <p className="text-xs text-muted-foreground">Subject</p>
                <p className="font-medium">{rec.draft_subject}</p>
                <p className="mt-3 whitespace-pre-line text-sm">{rec.draft_body}</p>
              </div>
            </Section>
          ) : null}
          <Section icon={BookOpen} title={`Knowledge evidence (${knowledge.length})`}>
            {knowledge.length ? (
              <ul className="space-y-2">
                {knowledge.map((e) => (
                  <EvidenceRow key={e.evidence_id} e={e} />
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground">INSUFFICIENT_EVIDENCE — no policy passage met the relevance threshold.</p>
            )}
          </Section>
          {claims.length ? (
            <Section icon={ShieldCheck} title={`Grounding: ${rec.grounding.supported}/${rec.grounding.total} policy claims verified`}>
              <ul className="space-y-1.5">
                {claims.map((c) => (
                  <li key={c.claim} className="flex items-start gap-2">
                    {c.supported ? (
                      <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
                    ) : (
                      <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
                    )}
                    <div>
                      <p>{c.claim}</p>
                      <p className="text-xs text-muted-foreground">
                        {c.supported
                          ? `${c.source_document} › ${c.source_section} · support ${c.support_score.toFixed(2)}`
                          : c.problems.join("; ")}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}
          {rec.limitations.length ? (
            <Section icon={CircleAlert} title="Limitations">
              <ul className="list-disc space-y-1 pl-4 text-muted-foreground">
                {rec.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </Section>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}
