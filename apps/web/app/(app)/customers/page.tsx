"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Search } from "lucide-react"
import Link from "next/link"
import { useState } from "react"

import { RiskBadge } from "@/components/risk/risk"
import { PageHeader } from "@/components/shared/page-header"
import { Pagination } from "@/components/shared/pagination"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiGet } from "@/lib/api"
import { formatMoneyCompact, titleCase } from "@/lib/format"
import type { Page, RiskLevel } from "@/lib/types"

interface CustomerRow {
  id: string
  name: string
  industry: string
  segment: string
  status: string
  city: string | null
  owner: string | null
  risk_score: number | null
  revenue_at_risk: number
  open_pipeline_value: number
  open_deals: number
}

const levelFor = (score: number | null): RiskLevel | null =>
  score === null ? null : score >= 75 ? "critical" : score >= 55 ? "high" : score >= 35 ? "medium" : "low"

export default function CustomersPage() {
  const [q, setQ] = useState("")
  const [status, setStatus] = useState("all")
  const [offset, setOffset] = useState(0)
  const { data, error, isLoading } = useQuery({
    queryKey: ["customers", q, status, offset],
    queryFn: () => apiGet<Page<CustomerRow>>("/customers", { q, status: status === "all" ? undefined : status, limit: 25, offset }),
    placeholderData: keepPreviousData,
  })
  return (
    <>
      <PageHeader title="Customers" description="Accounts ranked by their highest current deal risk, then open pipeline." />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row">
        <div className="relative sm:w-80">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Search by name or city" className="pl-8" value={q} onChange={(e) => (setOffset(0), setQ(e.target.value))} />
        </div>
        <Select value={status} onValueChange={(v) => (setOffset(0), setStatus(v))}>
          <SelectTrigger className="sm:w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="prospect">Prospects</SelectItem>
            <SelectItem value="active">Active customers</SelectItem>
            <SelectItem value="churned">Churned</SelectItem>
          </SelectContent>
        </Select>
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
                  <TableHead className="pl-6">Customer</TableHead>
                  <TableHead>Industry</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Owner</TableHead>
                  <TableHead className="text-right">Open pipeline</TableHead>
                  <TableHead className="text-right">At risk</TableHead>
                  <TableHead className="pr-6">Risk</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="pl-6">
                      <Link href={`/customers/${c.id}`} className="font-medium hover:underline">
                        {c.name}
                      </Link>
                      <div className="text-xs text-muted-foreground">
                        {c.city} · {titleCase(c.segment)}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">{c.industry}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="capitalize">
                        {c.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">{c.owner ?? "—"}</TableCell>
                    <TableCell className="text-right tabular">
                      {c.open_deals ? `${formatMoneyCompact(c.open_pipeline_value)} · ${c.open_deals}` : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular">{c.revenue_at_risk ? formatMoneyCompact(c.revenue_at_risk) : "—"}</TableCell>
                    <TableCell className="pr-6">
                      <RiskBadge level={levelFor(c.risk_score)} score={c.risk_score} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState title="No customers found" />
          )}
        </CardContent>
      </Card>
      {data ? <Pagination total={data.total} limit={25} offset={offset} onChange={setOffset} /> : null}
    </>
  )
}
