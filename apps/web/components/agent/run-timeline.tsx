import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react"

import { formatMs } from "@/lib/format"
import type { RunStep } from "@/lib/types"
import { cn } from "@/lib/utils"

const NODES: { node: string; label: string; kind: "deterministic" | "llm" | "rag" | "guardrail" | "action" }[] = [
  { node: "load_context", label: "Load CRM context", kind: "deterministic" },
  { node: "analyze_conversation", label: "Conversation intelligence", kind: "llm" },
  { node: "assess_risk", label: "Revenue risk engine", kind: "deterministic" },
  { node: "retrieve_knowledge", label: "Hybrid RAG: policies & playbooks", kind: "rag" },
  { node: "recommend", label: "Recommendation", kind: "llm" },
  { node: "ground_check", label: "Grounding & citation check", kind: "guardrail" },
  { node: "policy_check", label: "Policy engine", kind: "guardrail" },
  { node: "persist_recommendation", label: "Save · follow-up · approval request", kind: "action" },
  { node: "execute_action", label: "Execute action", kind: "action" },
  { node: "verify", label: "Verify effects", kind: "deterministic" },
]

const KIND_LABEL = { deterministic: "Deterministic", llm: "LLM", rag: "RAG", guardrail: "Guardrail", action: "Tool" }

export function RunTimeline({ steps, finished }: { steps: RunStep[]; finished: boolean }) {
  const byNode = new Map(steps.map((s) => [s.node, s]))
  const visible = NODES.filter((n) => byNode.has(n.node) || !finished)
  return (
    <ol className="relative space-y-1">
      {visible.map((n, i) => {
        const step = byNode.get(n.node)
        const status = step?.status ?? "pending"
        return (
          <li key={n.node} className="relative flex gap-3 pb-3">
            {i < visible.length - 1 ? <span className="absolute left-[9px] top-6 h-full w-px bg-border" /> : null}
            <span className="relative z-10 mt-0.5 bg-card">
              {status === "completed" ? (
                <CheckCircle2 className="size-5 text-success" />
              ) : status === "failed" ? (
                <XCircle className="size-5 text-destructive" />
              ) : status === "running" ? (
                <Loader2 className="size-5 animate-spin text-primary" />
              ) : (
                <Circle className="size-5 text-muted-foreground/40" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className={cn("text-sm font-medium", status === "pending" && "text-muted-foreground")}>{n.label}</span>
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  {KIND_LABEL[n.kind]}
                </span>
                {step?.latency_ms !== undefined ? <span className="text-xs text-muted-foreground tabular">{formatMs(step.latency_ms)}</span> : null}
              </div>
              {step?.summary ? <p className="mt-0.5 text-xs text-muted-foreground">{step.summary}</p> : null}
              {step?.error ? <p className="mt-0.5 text-xs text-destructive">{step.error}</p> : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
