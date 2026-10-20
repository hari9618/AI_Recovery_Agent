"use client"

import { useMutation, useQuery } from "@tanstack/react-query"
import { CheckCircle2, Loader2, Send } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { useHydrated } from "@/hooks/use-hydrated"
import { apiGet, apiSend, errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

interface Integrations {
  slack: { configured: boolean; events: string[]; app_public_url: string }
  email: { configured: boolean; transport: string }
}

function SlackLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className}>
      <path fill="#E01E5A" d="M5.04 15.17a2.52 2.52 0 1 1-2.52-2.52h2.52zm1.27 0a2.52 2.52 0 0 1 5.04 0v6.31a2.52 2.52 0 1 1-5.04 0z" />
      <path fill="#36C5F0" d="M8.83 5.04a2.52 2.52 0 1 1 2.52-2.52v2.52zm0 1.27a2.52 2.52 0 0 1 0 5.04H2.52a2.52 2.52 0 0 1 0-5.04z" />
      <path fill="#2EB67D" d="M18.96 8.83a2.52 2.52 0 1 1 2.52 2.52h-2.52zm-1.27 0a2.52 2.52 0 0 1-5.04 0V2.52a2.52 2.52 0 1 1 5.04 0z" />
      <path fill="#ECB22E" d="M15.17 18.96a2.52 2.52 0 1 1-2.52 2.52v-2.52zm0-1.27a2.52 2.52 0 0 1 0-5.04h6.31a2.52 2.52 0 1 1 0 5.04z" />
    </svg>
  )
}

export function useIntegrations() {
  const hydrated = useHydrated()
  const q = useQuery({ queryKey: ["integrations"], queryFn: () => apiGet<Integrations>("/integrations"), staleTime: 60_000 })
  return hydrated ? q.data : undefined
}

/** Small status pill: whether approval alerts go to Slack. */
export function SlackStatus({ className }: { className?: string }) {
  const data = useIntegrations()
  if (!data) return null
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-1 text-xs", className)}>
      <SlackLogo className="size-3.5" />
      {data.slack.configured ? "Slack alerts on" : "Slack not connected"}
    </span>
  )
}

export function SlackCard() {
  const data = useIntegrations()
  const test = useMutation({
    mutationFn: () => apiSend<{ ok: boolean }>("POST", "/integrations/slack/test"),
    onSuccess: () => toast.success("Test message posted to Slack"),
    onError: (e) => toast.error("Slack test failed", { description: errorMessage(e) }),
  })
  const on = data?.slack.configured
  return (
    <section className="surface mt-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <span className="flex size-11 items-center justify-center rounded-xl border bg-background">
            <SlackLogo className="size-6" />
          </span>
          <div>
            <h2 className="font-display text-xl font-bold">Slack alerts</h2>
            <p className="mt-1 max-w-xl text-sm text-muted-foreground">
              When the agent drafts a customer email that needs approval, the sales team gets the deal, the reasons, who to call and
              the draft in Slack. Approvals and rejections are posted back to the same channel.
            </p>
          </div>
        </div>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
            on ? "bg-money/12 text-money" : "bg-muted text-muted-foreground",
          )}
        >
          {on ? <CheckCircle2 className="size-3.5" /> : null}
          {data ? (on ? "Connected" : "Not connected") : "Checking…"}
        </span>
      </div>
      {on ? (
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Button type="button" variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? <Loader2 className="animate-spin" /> : <Send />} Send test message
          </Button>
          <p className="text-xs text-muted-foreground">Links in messages open {data?.slack.app_public_url}</p>
        </div>
      ) : data ? (
        <ol className="mt-5 list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
          <li>
            In Slack, create an app at <span className="font-mono text-foreground">api.slack.com/apps</span> and turn on{" "}
            <span className="font-medium text-foreground">Incoming Webhooks</span>.
          </li>
          <li>Add a webhook to your sales channel and copy its URL.</li>
          <li>
            Put it in <span className="font-mono text-foreground">.env</span> as{" "}
            <span className="font-mono text-foreground">SLACK_WEBHOOK_URL=…</span> and restart the API.
          </li>
        </ol>
      ) : null}
    </section>
  )
}
