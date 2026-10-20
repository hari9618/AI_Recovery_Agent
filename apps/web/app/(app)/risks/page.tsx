"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronRight, Search } from "lucide-react"
import Link from "next/link"
import { Fragment, useState } from "react"

import { RunAgentButton } from "@/components/agent/run-agent-button"
import { RecommendationStatus } from "@/components/agent/recommendation-panel"
import { ReasonList, RiskBadge, RiskMeter, RISK_STYLE } from "@/components/risk/risk"
import { PageHeader } from "@/components/shared/page-header"
import { Pagination } from "@/components/shared/pagination"
import { Provenance } from "@/components/shared/provenance"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiGet } from "@/lib/api"
import { formatMoney, formatMoneyCompact, formatPercent, titleCase } from "@/lib/format"
import type { Page, RiskItem, RiskLevel } from "@/lib/types"
import { cn } from "@/lib/utils"

const LEVELS: RiskLevel[] = ["critical", "high", "medium", "low"]
const PAGE_SIZE = 25

export default function RisksPage() {
  const [levels, setLevels] = useState<RiskLevel[]>(["critical", "high"])
  const [q, setQ] = useState("")
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const { data, error, isLoading } = useQuery({
    queryKey: ["risks", levels, q, offset],
    queryFn: () => apiGet<Page<RiskItem>>("/risks", { level: levels, q, limit: PAGE_SIZE, offset }),
    placeholderData: keepPreviousData,
  })
  const toggle = (l: RiskLevel) => {
    setOffset(0)
    setLevels((cur) => (cur.includes(l) ? cur.filter((x) => x !== l) : [...cur, l]))
  }

  return (
    <>
      <PageHeader
        title="Revenue risks"
        description="Every open deal scored 0–100 by the deterministic Revenue Risk Engine. Each point is explained by a reason code and its evidence."
        actions={<Provenance kind="crm" />}
      />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex flex-wrap gap-2">
          {LEVELS.map((l) => (
            <Button
              key={l}
              size="sm"
              variant="outline"
              onClick={() => toggle(l)}
              className={cn("gap-2", levels.includes(l) && RISK_STYLE[l].badge)}
            >
              <span className={cn("size-2 rounded-full", RISK_STYLE[l].bar)} />
              {RISK_STYLE[l].label}
            </Button>
          ))}
        </div>
        <div className="relative sm:ml-auto sm:w-72">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input
            placeholder="Search customer"
            className="pl-8"
            value={q}
            onChange={(e) => {
              setOffset(0)
              setQ(e.target.value)
            }}
          />
        </div>
      </div>
      {error ? <ErrorState error={error} /> : null}
      <Card className="py-0">
        <CardContent className="px-0">
          {isLoading ? (
            <LoadingBlock rows={8} className="space-y-3 p-6" />
          ) : data && data.items.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8 pl-4" />
                  <TableHead>Customer · deal</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                  <TableHead className="min-w-52">Risk</TableHead>
                  <TableHead>Main reason</TableHead>
                  <TableHead>Recommended action</TableHead>
                  <TableHead className="pr-4" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((r) => (
                  <Fragment key={r.risk_id}>
                    <TableRow className="cursor-pointer" onClick={() => setOpen(open === r.risk_id ? null : r.risk_id)}>
                      <TableCell className="pl-4">
                        {open === r.risk_id ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                      </TableCell>
                      <TableCell>
                        <Link href={`/customers/${r.customer_id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                          {r.customer_name}
                        </Link>
                        <div className="text-xs text-muted-foreground">
                          {titleCase(r.stage)} · {r.owner} · {r.industry}
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular">{formatMoneyCompact(r.deal_value)}</TableCell>
                      <TableCell className="min-w-52">
                        <div className="space-y-1.5">
                          <RiskBadge level={r.risk_level} />
                          <RiskMeter score={r.risk_score} level={r.risk_level} />
                        </div>
                      </TableCell>
                      <TableCell className="max-w-56 text-sm whitespace-normal">{r.reasons[0]?.label ?? "—"}</TableCell>
                      <TableCell className="max-w-56 text-sm whitespace-normal">{r.recommended_next_step}</TableCell>
                      <TableCell className="pr-4 text-right" onClick={(e) => e.stopPropagation()}>
                        {r.latest_recommendation_status ? (
                          <RecommendationStatus status={r.latest_recommendation_status} />
                        ) : (
                          <RunAgentButton opportunityId={r.opportunity_id} variant="outline" label="Investigate" />
                        )}
                      </TableCell>
                    </TableRow>
                    {open === r.risk_id ? (
                      <TableRow className="bg-muted/30 hover:bg-muted/30">
                        <TableCell />
                        <TableCell colSpan={6} className="py-4">
                          <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
                            <div className="md:col-span-2">
                              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Why this score</p>
                              <ReasonList reasons={r.reasons} />
                            </div>
                            <div className="space-y-2 text-sm">
                              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Money</p>
                              <p>
                                At risk: <span className="font-semibold">{formatMoney(r.revenue_at_risk)}</span>
                              </p>
                              <p>
                                Purchase probability: <span className="font-semibold">{formatPercent(r.purchase_probability)}</span>
                              </p>
                              <p>
                                Probability-weighted: <span className="font-semibold">{formatMoney(r.weighted_revenue_at_risk)}</span>
                              </p>
                              <div className="pt-2">
                                <RunAgentButton opportunityId={r.opportunity_id} label="Run recovery agent" />
                              </div>
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState title="No deals match these filters" description="Try including more risk levels." />
          )}
        </CardContent>
      </Card>
      {data ? <Pagination total={data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} /> : null}
    </>
  )
}
