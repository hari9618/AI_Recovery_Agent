"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Sparkles } from "lucide-react"
import Link from "next/link"
import { useState } from "react"

import { RecommendationStatus } from "@/components/agent/recommendation-panel"
import { RiskBadge } from "@/components/risk/risk"
import { PageHeader } from "@/components/shared/page-header"
import { Pagination } from "@/components/shared/pagination"
import { Provenance } from "@/components/shared/provenance"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiGet } from "@/lib/api"
import { formatMoneyCompact, formatPercent, timeAgo, titleCase } from "@/lib/format"
import type { Page, Recommendation } from "@/lib/types"

const STATUSES = ["all", "pending_approval", "executed", "approved", "rejected", "failed"]

export default function RecommendationsPage() {
  const [status, setStatus] = useState("all")
  const [offset, setOffset] = useState(0)
  const { data, error, isLoading } = useQuery({
    queryKey: ["recommendations", status, offset],
    queryFn: () => apiGet<Page<Recommendation>>("/recommendations", { status: status === "all" ? undefined : [status], limit: 25, offset }),
    placeholderData: keepPreviousData,
  })
  return (
    <>
      <PageHeader
        title="AI recommendations"
        description="Everything the recovery agent proposed, with its grounding, policy outcome and current status."
        actions={
          <Select value={status} onValueChange={(v) => (setOffset(0), setStatus(v))}>
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {s === "all" ? "All statuses" : titleCase(s)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />
      {error ? <ErrorState error={error} /> : null}
      <Card className="py-0">
        <CardContent className="px-0">
          {isLoading ? (
            <LoadingBlock rows={6} className="space-y-3 p-6" />
          ) : data?.items.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Recommendation</TableHead>
                  <TableHead>Customer</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead className="text-right">Confidence</TableHead>
                  <TableHead>Grounding</TableHead>
                  <TableHead className="pr-6">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="max-w-80 pl-6 whitespace-normal">
                      <Link href={`/recommendations/${r.id}`} className="font-medium hover:underline">
                        {r.title}
                      </Link>
                      <div className="flex items-center gap-2 pt-1 text-xs text-muted-foreground">
                        <Provenance kind={r.generated_by === "rules_fallback" ? "rules" : "ai"} /> {timeAgo(r.created_at)}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">
                      {r.customer_name}
                      <div className="text-xs text-muted-foreground">{formatMoneyCompact(r.deal_value)}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{titleCase(r.action_type)}</Badge>
                    </TableCell>
                    <TableCell>
                      <RiskBadge level={r.risk_level ?? null} score={r.risk_score} />
                    </TableCell>
                    <TableCell className="text-right tabular">{formatPercent(r.confidence)}</TableCell>
                    <TableCell className="text-xs">
                      {r.grounding.total ? `${r.grounding.supported}/${r.grounding.total} claims verified` : "no policy claims"}
                    </TableCell>
                    <TableCell className="pr-6">
                      <RecommendationStatus status={r.status} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState icon={Sparkles} title="No recommendations yet" description="They appear after the recovery agent runs on a deal." />
          )}
        </CardContent>
      </Card>
      {data ? <Pagination total={data.total} limit={25} offset={offset} onChange={setOffset} /> : null}
    </>
  )
}
