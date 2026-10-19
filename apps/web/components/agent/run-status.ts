import type { AgentRun } from "@/lib/types"

export const RUN_STATUS: Record<AgentRun["status"], { label: string; className: string }> = {
  running: { label: "Running", className: "bg-primary/10 text-primary border-primary/30" },
  awaiting_approval: { label: "Awaiting approval", className: "bg-warning/15 border-warning/40" },
  completed: { label: "Completed", className: "bg-success/12 text-success border-success/30" },
  needs_review: { label: "Needs review", className: "bg-warning/15 border-warning/40" },
  failed: { label: "Failed", className: "bg-destructive/10 text-destructive border-destructive/30" },
}
