"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { useParams } from "next/navigation"

import { ApprovalActions } from "@/components/agent/approval-actions"
import { RecommendationPanel } from "@/components/agent/recommendation-panel"
import { PageHeader } from "@/components/shared/page-header"
import { ErrorState, LoadingBlock } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { apiGet } from "@/lib/api"
import { formatDateTime, titleCase } from "@/lib/format"
import type { Recommendation } from "@/lib/types"

export default function RecommendationDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: rec, error, isLoading } = useQuery({ queryKey: ["recommendation", id], queryFn: () => apiGet<Recommendation>(`/recommendations/${id}`) })
  if (isLoading) return <LoadingBlock rows={8} />
  if (error) return <ErrorState error={error} />
  if (!rec) return null
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/recommendations" className="hover:underline">
            Recommendations
          </Link>
        }
        title={rec.customer_name}
        actions={
          <>
            <Button asChild variant="outline" size="sm">
              <Link href={`/customers/${rec.customer_id}`}>Customer</Link>
            </Button>
            {rec.agent_run_id ? (
              <Button asChild variant="outline" size="sm">
                <Link href={`/agent-runs/${rec.agent_run_id}`}>Agent run</Link>
              </Button>
            ) : null}
          </>
        }
      />
      {rec.approval?.status === "pending" ? (
        <Card className="mb-4 border-warning/50">
          <CardHeader>
            <CardTitle>Awaiting approval ({titleCase(rec.approval.required_role)}+)</CardTitle>
          </CardHeader>
          <CardContent>
            <ApprovalActions approval={rec.approval} rec={rec} />
          </CardContent>
        </Card>
      ) : null}
      <RecommendationPanel rec={rec} />
      {rec.actions?.length ? (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Actions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {rec.actions.map((a) => (
              <div key={a.id} className="rounded-lg border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs">{a.action_type}</span>
                  <Badge variant="outline" className={a.status === "succeeded" ? "text-success" : "text-destructive"}>
                    {a.status}
                  </Badge>
                  <Badge variant="secondary">{a.automated ? "automated" : "human-approved"}</Badge>
                  <span className="ml-auto text-xs text-muted-foreground">{formatDateTime(a.executed_at)}</span>
                </div>
                <pre className="mt-2 overflow-auto text-xs text-muted-foreground">{JSON.stringify(a.result, null, 2)}</pre>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </>
  )
}
