"use client"

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Search, Sparkles } from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import { toast } from "sonner"

import { PageHeader } from "@/components/shared/page-header"
import { Pagination } from "@/components/shared/pagination"
import { Provenance } from "@/components/shared/provenance"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiGet, apiSend, errorMessage } from "@/lib/api"
import { formatPercent, timeAgo, titleCase } from "@/lib/format"
import type { Page } from "@/lib/types"

interface ConvRow {
  id: string
  customer_id: string
  customer_name: string
  subject: string | null
  channel: string
  last_message_at: string
  last_sender: string
  deal_stage: string | null
  analysis: { status: string; intent: string | null; sentiment: string | null; confidence: number | null; model: string } | null
}

export default function ConversationsPage() {
  const qc = useQueryClient()
  const [q, setQ] = useState("")
  const [openOnly, setOpenOnly] = useState(true)
  const [offset, setOffset] = useState(0)
  const { data, error, isLoading } = useQuery({
    queryKey: ["conversations", q, openOnly, offset],
    queryFn: () => apiGet<Page<ConvRow>>("/conversations", { q, open_deals_only: openOnly, limit: 25, offset }),
    placeholderData: keepPreviousData,
  })
  const batch = useMutation({
    mutationFn: () => apiSend<{ analyzed: number; fallback: number; errors: unknown[]; remaining: number }>("POST", "/conversations/analyze-batch", { limit: 15 }),
    onSuccess: (r) => {
      toast.success(`Analysed ${r.analyzed} conversations`, { description: `${r.fallback} fell back · ${r.remaining} remaining · risk re-scored` })
      qc.invalidateQueries()
    },
    onError: (e) => toast.error("Batch analysis failed", { description: errorMessage(e) }),
  })
  return (
    <>
      <PageHeader
        title="Conversation intelligence"
        description="Customer conversations analysed by the LLM into validated structured signals (intent, objections, competitors). Until analysed, a labelled keyword heuristic is used."
        actions={
          <Button onClick={() => batch.mutate()} disabled={batch.isPending}>
            {batch.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
            Analyse 15 riskiest
          </Button>
        }
      />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative sm:w-80">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Search customer or subject" className="pl-8" value={q} onChange={(e) => (setOffset(0), setQ(e.target.value))} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={openOnly} onCheckedChange={(v) => (setOffset(0), setOpenOnly(v))} />
          Open deals only
        </label>
      </div>
      {error ? <ErrorState error={error} /> : null}
      <Card className="py-0">
        <CardContent className="px-0">
          {isLoading ? (
            <LoadingBlock rows={8} className="space-y-3 p-6" />
          ) : data?.items.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Conversation</TableHead>
                  <TableHead>Customer</TableHead>
                  <TableHead>Last message</TableHead>
                  <TableHead>Analysis</TableHead>
                  <TableHead className="pr-6">Intent</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="pl-6">
                      <Link href={`/conversations/${c.id}`} className="font-medium hover:underline">
                        {c.subject ?? "Conversation"}
                      </Link>
                      <div className="text-xs text-muted-foreground">
                        {titleCase(c.channel)} {c.deal_stage ? `· ${titleCase(c.deal_stage)}` : ""}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">{c.customer_name}</TableCell>
                    <TableCell className="text-sm">
                      {timeAgo(c.last_message_at)}
                      <span className={c.last_sender === "customer" ? "ml-1 text-xs font-medium text-risk-high" : "ml-1 text-xs text-muted-foreground"}>
                        by {c.last_sender}
                      </span>
                    </TableCell>
                    <TableCell>{c.analysis ? <Provenance kind={c.analysis.status === "fallback" ? "rules" : "ai"} /> : <Provenance kind="heuristic" />}</TableCell>
                    <TableCell className="pr-6">
                      {c.analysis?.intent ? (
                        <Badge variant="outline" className="capitalize">
                          {c.analysis.intent} · {formatPercent(c.analysis.confidence)}
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">not analysed</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState title="No conversations" />
          )}
        </CardContent>
      </Card>
      {data ? <Pagination total={data.total} limit={25} offset={offset} onChange={setOffset} /> : null}
    </>
  )
}
