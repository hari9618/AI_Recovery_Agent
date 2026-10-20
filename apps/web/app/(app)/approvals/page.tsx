"use client"

import { useQuery } from "@tanstack/react-query"
import { ClipboardCheck } from "lucide-react"
import Link from "next/link"
import { useState } from "react"

import { ApprovalActions } from "@/components/agent/approval-actions"
import { RecommendationPanel } from "@/components/agent/recommendation-panel"
import { RiskBadge } from "@/components/risk/risk"
import { PageHeader } from "@/components/shared/page-header"
import { SlackStatus } from "@/components/shared/slack-card"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { apiGet } from "@/lib/api"
import { formatDateTime, formatMoney, timeAgo } from "@/lib/format"
import type { Approval, Page } from "@/lib/types"

export default function ApprovalsPage() {
  const [status, setStatus] = useState<"pending" | "approved" | "rejected">("pending")
  const { data, error, isLoading } = useQuery({
    queryKey: ["approvals", status],
    queryFn: () => apiGet<Page<Approval>>("/approvals", { status, limit: 50 }),
  })
  return (
    <>
      <PageHeader
        title="Approval Center"
        description="Customer-facing and commercial actions wait here. Every request shows what the AI recommends, why, the evidence, and which policy rule requires a human."
        actions={<SlackStatus />}
      />
      <Tabs value={status} onValueChange={(v) => setStatus(v as typeof status)} className="mb-4">
        <TabsList>
          <TabsTrigger value="pending">Pending</TabsTrigger>
          <TabsTrigger value="approved">Approved</TabsTrigger>
          <TabsTrigger value="rejected">Rejected</TabsTrigger>
        </TabsList>
      </Tabs>
      {isLoading ? <LoadingBlock rows={6} /> : null}
      {error ? <ErrorState error={error} /> : null}
      {data && !data.items.length ? (
        <EmptyState
          icon={ClipboardCheck}
          title={status === "pending" ? "Nothing waiting for approval" : `No ${status} requests`}
          description={status === "pending" ? "Run the recovery agent on an at-risk deal; risky actions will appear here." : undefined}
        />
      ) : null}
      <div className="space-y-6">
        {data?.items.map((a) =>
          a.recommendation ? (
            <div key={a.id} className="space-y-3">
              <Card className={status === "pending" ? "border-warning/50" : ""}>
                <CardHeader className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-1">
                    <CardTitle className="flex flex-wrap items-center gap-2">
                      <Link href={`/customers/${a.recommendation.customer_id}`} className="hover:underline">
                        {a.customer_name}
                      </Link>
                      <span className="text-sm font-normal text-muted-foreground">· {formatMoney(a.deal_value)}</span>
                      <RiskBadge level={a.recommendation.risk_level ?? null} />
                    </CardTitle>
                    <CardDescription>{a.risk_summary}</CardDescription>
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {a.reasons.map((r) => (
                        <Badge key={r.rule} variant="outline" className="font-mono text-[10px]" title={r.message}>
                          {r.rule}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div className="shrink-0 space-y-2 text-right text-xs text-muted-foreground">
                    <p>
                      Requires <span className="font-medium capitalize text-foreground">{a.required_role.replace("_", " ")}</span>+ · requested{" "}
                      {timeAgo(a.created_at)}
                    </p>
                    {a.status !== "pending" ? (
                      <p>
                        {a.status} by {a.decided_by_name ?? "—"} · {formatDateTime(a.decided_at)}
                        {a.decision_note ? ` · “${a.decision_note}”` : ""}
                        {a.edited_payload ? " · with edits" : ""}
                      </p>
                    ) : null}
                  </div>
                </CardHeader>
                {a.status === "pending" ? (
                  <CardContent>
                    <ApprovalActions approval={a} rec={a.recommendation} />
                  </CardContent>
                ) : null}
              </Card>
              <RecommendationPanel rec={a.recommendation} />
            </div>
          ) : null,
        )}
      </div>
    </>
  )
}
