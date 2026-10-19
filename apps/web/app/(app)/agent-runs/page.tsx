"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Bot, ExternalLink, Loader2 } from "lucide-react"
import Link from "next/link"
import { useState } from "react"

import { RUN_STATUS } from "@/components/agent/run-status"
import { PageHeader } from "@/components/shared/page-header"
import { Pagination } from "@/components/shared/pagination"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiGet } from "@/lib/api"
import { formatDateTime, formatMs, formatNumber } from "@/lib/format"
import type { AgentRun, Page } from "@/lib/types"

export default function AgentRunsPage() {
  const [offset, setOffset] = useState(0)
  const { data, error, isLoading } = useQuery({
    queryKey: ["agent-runs", offset],
    queryFn: () => apiGet<Page<AgentRun>>("/agent/runs", { limit: 25, offset }),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === "running") ? 2000 : false),
  })
  return (
    <>
      <PageHeader title="Agent runs" description="Every recovery workflow execution with its outcome, token usage, estimated cost and trace." />
      {error ? <ErrorState error={error} /> : null}
      <Card className="py-0">
        <CardContent className="px-0">
          {isLoading ? (
            <LoadingBlock rows={6} className="space-y-3 p-6" />
          ) : data?.items.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Customer</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead className="text-right">LLM calls</TableHead>
                  <TableHead className="text-right">Tokens</TableHead>
                  <TableHead className="text-right">Est. cost</TableHead>
                  <TableHead className="text-right">Latency</TableHead>
                  <TableHead className="pr-6 text-right">Trace</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="pl-6">
                      <Link href={`/agent-runs/${r.id}`} className="font-medium hover:underline">
                        {r.customer_name ?? r.id.slice(0, 8)}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={RUN_STATUS[r.status].className}>
                        {r.status === "running" ? <Loader2 className="size-3 animate-spin" /> : null}
                        {RUN_STATUS[r.status].label}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{formatDateTime(r.created_at)}</TableCell>
                    <TableCell className="text-right tabular">{r.llm_calls}</TableCell>
                    <TableCell className="text-right tabular">{formatNumber(r.input_tokens + r.output_tokens)}</TableCell>
                    <TableCell className="text-right tabular">${r.cost_usd.toFixed(4)}</TableCell>
                    <TableCell className="text-right tabular">{formatMs(r.latency_ms)}</TableCell>
                    <TableCell className="pr-6 text-right">
                      {r.trace_url ? (
                        <a href={r.trace_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                          Langfuse <ExternalLink className="size-3" />
                        </a>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState icon={Bot} title="No agent runs yet" description="Open a risky deal and press “Run recovery agent”." />
          )}
        </CardContent>
      </Card>
      {data ? <Pagination total={data.total} limit={25} offset={offset} onChange={setOffset} /> : null}
    </>
  )
}
