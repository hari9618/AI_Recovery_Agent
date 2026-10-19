import { Badge } from "@/components/ui/badge"
import { Provenance, sourceKind } from "@/components/shared/provenance"
import type { Reason, RiskLevel } from "@/lib/types"
import { cn } from "@/lib/utils"

export const RISK_STYLE: Record<RiskLevel, { label: string; badge: string; bar: string; text: string }> = {
  critical: { label: "Critical", badge: "bg-risk-critical/12 text-risk-critical border-risk-critical/30", bar: "bg-risk-critical", text: "text-risk-critical" },
  high: { label: "High", badge: "bg-risk-high/12 text-risk-high border-risk-high/30", bar: "bg-risk-high", text: "text-risk-high" },
  medium: { label: "Medium", badge: "bg-risk-medium/20 text-foreground border-risk-medium/50", bar: "bg-risk-medium", text: "text-foreground" },
  low: { label: "Low", badge: "bg-risk-low/12 text-risk-low border-risk-low/30", bar: "bg-risk-low", text: "text-risk-low" },
}

export function RiskBadge({ level, score, className }: { level: RiskLevel | null | undefined; score?: number | null; className?: string }) {
  if (!level) return <span className="text-muted-foreground">—</span>
  const s = RISK_STYLE[level]
  return (
    <Badge variant="outline" className={cn("gap-1 font-semibold", s.badge, className)}>
      <span className={cn("size-1.5 rounded-full", s.bar)} />
      {s.label}
      {score !== undefined && score !== null ? <span className="tabular font-normal opacity-80">· {score}</span> : null}
    </Badge>
  )
}

/** Horizontal 0–100 meter (deterministic risk score). */
export function RiskMeter({ score, level, className }: { score: number; level: RiskLevel; className?: string }) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full transition-all", RISK_STYLE[level].bar)} style={{ width: `${Math.min(score, 100)}%` }} />
      </div>
      <span className="shrink-0 whitespace-nowrap text-right text-sm font-semibold tabular">{score} / 100</span>
    </div>
  )
}

export function ReasonList({ reasons, compact = false }: { reasons: Reason[]; compact?: boolean }) {
  if (!reasons.length) return <p className="text-sm text-muted-foreground">No risk signals fired.</p>
  return (
    <ul className="space-y-2">
      {reasons.map((r) => (
        <li key={r.code} className="flex items-start gap-3">
          <span className="mt-0.5 inline-flex h-5 min-w-9 items-center justify-center rounded-md bg-muted px-1.5 text-[11px] font-semibold tabular">
            +{r.points}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm">{r.label}</span>
              {!compact ? <Provenance kind={sourceKind(r.source)} /> : null}
            </div>
            {!compact && r.evidence?.excerpt ? (
              <p className="mt-1 border-l-2 pl-2 text-xs italic text-muted-foreground">“{String(r.evidence.excerpt)}”</p>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  )
}
