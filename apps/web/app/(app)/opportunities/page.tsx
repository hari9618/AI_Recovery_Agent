"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MoreHorizontal } from "lucide-react"
import Link from "next/link"
import { toast } from "sonner"

import { RiskBadge } from "@/components/risk/risk"
import { PageHeader } from "@/components/shared/page-header"
import { ErrorState, LoadingBlock } from "@/components/shared/states"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { ScrollArea } from "@/components/ui/scroll-area"
import { apiGet, apiSend, errorMessage } from "@/lib/api"
import { formatMoneyCompact, timeAgo, titleCase } from "@/lib/format"
import type { RiskLevel } from "@/lib/types"
import { cn } from "@/lib/utils"

interface Column {
  stage: string
  count: number
  value: number
  items: { id: string; name: string; customer_id: string; customer_name: string; owner: string | null; amount: number; risk_level: RiskLevel | null; risk_score: number | null; last_activity_at: string | null; closed_at: string | null }[]
}

const STAGE_ACCENT: Record<string, string> = {
  prospecting: "bg-chart-2",
  qualification: "bg-chart-3",
  proposal: "bg-chart-1",
  negotiation: "bg-chart-4",
  closed_won: "bg-success",
  closed_lost: "bg-muted-foreground",
}

export default function OpportunitiesPage() {
  const qc = useQueryClient()
  const { data, error, isLoading } = useQuery({ queryKey: ["pipeline"], queryFn: () => apiGet<{ stages: Column[] }>("/opportunities/pipeline") })
  const outcome = useMutation({
    mutationFn: ({ id, value }: { id: string; value: "closed_won" | "closed_lost" }) =>
      apiSend("POST", `/opportunities/${id}/outcome`, { outcome: value }),
    onSuccess: (_d, v) => {
      toast.success(v.value === "closed_won" ? "Marked as won" : "Marked as lost", {
        description: v.value === "closed_won" ? "Counts as recovered revenue only if a recovery action was executed before the win." : undefined,
      })
      qc.invalidateQueries()
    },
    onError: (e) => toast.error("Update failed", { description: errorMessage(e) }),
  })
  if (isLoading) return <LoadingBlock rows={6} />
  if (error) return <ErrorState error={error} />
  return (
    <>
      <PageHeader title="Pipeline" description="Open deals by stage with their current risk, plus deals closed in the last 90 days." />
      <ScrollArea className="w-full whitespace-nowrap pb-3">
        <div className="flex gap-4">
          {data?.stages.map((col) => (
            <div key={col.stage} className="w-72 shrink-0">
              <div className="mb-2 flex items-center gap-2 px-1">
                <span className={cn("size-2 rounded-full", STAGE_ACCENT[col.stage])} />
                <span className="text-sm font-semibold">{titleCase(col.stage)}</span>
                <span className="text-xs text-muted-foreground">{col.count}</span>
                <span className="ml-auto text-xs font-medium tabular">{formatMoneyCompact(col.value)}</span>
              </div>
              <div className="space-y-2 rounded-xl bg-muted/40 p-2">
                {col.items.map((o) => (
                  <Card key={o.id} className="gap-0 py-3 shadow-none">
                    <CardContent className="space-y-2 px-3 whitespace-normal">
                      <div className="flex items-start justify-between gap-2">
                        <Link href={`/customers/${o.customer_id}`} className="text-sm font-medium leading-snug hover:underline">
                          {o.customer_name}
                        </Link>
                        {!col.stage.startsWith("closed") ? (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button size="icon" variant="ghost" className="size-6" aria-label="Deal actions">
                                <MoreHorizontal />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onClick={() => outcome.mutate({ id: o.id, value: "closed_won" })}>Mark won</DropdownMenuItem>
                              <DropdownMenuItem onClick={() => outcome.mutate({ id: o.id, value: "closed_lost" })}>Mark lost</DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        ) : null}
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold tabular">{formatMoneyCompact(o.amount)}</span>
                        {o.risk_level ? <RiskBadge level={o.risk_level} score={o.risk_score} /> : null}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {o.owner} · {o.closed_at ? `closed ${timeAgo(o.closed_at)}` : `active ${timeAgo(o.last_activity_at)}`}
                      </p>
                    </CardContent>
                  </Card>
                ))}
                {col.count > col.items.length ? (
                  <p className="px-1 py-1 text-xs text-muted-foreground">+{col.count - col.items.length} more</p>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
    </>
  )
}
