import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

type Kind = "observed" | "estimated" | "synthetic" | "not_evaluated" | "offline_eval" | "live_eval" | "heuristic" | "ai" | "crm" | "rules"

const STYLES: Record<Kind, { label: string; className: string; help: string }> = {
  observed: { label: "Observed", className: "border-success/40 bg-success/10", help: "Computed from recorded data." },
  estimated: {
    label: "Estimated",
    className: "border-warning/50 bg-warning/10",
    help: "Observed counts × the assumptions shown. Not a measured business result.",
  },
  synthetic: {
    label: "Synthetic demo",
    className: "border-warning/50 bg-warning/10",
    help: "Computed from the synthetic demo dataset, not a real business.",
  },
  not_evaluated: { label: "Not evaluated yet", className: "border-border bg-muted", help: "No evaluation run has been recorded." },
  offline_eval: {
    label: "Offline eval",
    className: "border-chart-2/40 bg-chart-2/10",
    help: "Scripted LLM: measures orchestration, guardrails and DB effects — not model quality.",
  },
  live_eval: { label: "Live eval", className: "border-primary/40 bg-primary/10", help: "Real model calls on the synthetic dataset." },
  heuristic: {
    label: "Keyword heuristic",
    className: "border-border bg-muted",
    help: "Deterministic keyword match — the conversation has not been analysed by the LLM yet.",
  },
  ai: { label: "AI analysis", className: "border-primary/40 bg-primary/10", help: "Validated LLM output (Pydantic schema)." },
  crm: { label: "CRM data", className: "border-border bg-background", help: "Read directly from PostgreSQL." },
  rules: {
    label: "Rules fallback",
    className: "border-warning/50 bg-warning/10",
    help: "Produced by deterministic rules because the AI step was unavailable.",
  },
}

export function Provenance({ kind, className }: { kind: Kind; className?: string }) {
  const s = STYLES[kind]
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant="outline" className={cn("cursor-help text-[11px] font-medium text-foreground", s.className, className)}>
          {s.label}
        </Badge>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">{s.help}</TooltipContent>
    </Tooltip>
  )
}

export function sourceKind(source: string | null | undefined): Kind {
  if (source === "llm_analysis" || source === "llm") return "ai"
  if (source === "keyword_heuristic") return "heuristic"
  if (source === "rules_fallback") return "rules"
  return "crm"
}
