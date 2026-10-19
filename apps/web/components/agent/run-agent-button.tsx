"use client"

import { useMutation } from "@tanstack/react-query"
import { Bot, Loader2 } from "lucide-react"
import { useRouter } from "next/navigation"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { apiSend, errorMessage } from "@/lib/api"

export function RunAgentButton({
  opportunityId,
  force = false,
  size = "sm",
  variant = "default",
  label = "Run recovery agent",
}: {
  opportunityId: string
  force?: boolean
  size?: "sm" | "default" | "lg"
  variant?: "default" | "outline" | "secondary"
  label?: string
}) {
  const router = useRouter()
  const run = useMutation({
    mutationFn: () => apiSend<{ run_id: string }>("POST", "/agent/runs", { opportunity_id: opportunityId, force }),
    onSuccess: (r) => router.push(`/agent-runs/${r.run_id}`),
    onError: (e) => toast.error("Could not start the agent", { description: errorMessage(e) }),
  })
  return (
    <Button size={size} variant={variant} onClick={() => run.mutate()} disabled={run.isPending}>
      {run.isPending ? <Loader2 className="animate-spin" /> : <Bot />}
      {label}
    </Button>
  )
}
