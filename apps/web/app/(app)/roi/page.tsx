"use client"

import { useQuery } from "@tanstack/react-query"

import { PageHeader } from "@/components/shared/page-header"
import { Provenance } from "@/components/shared/provenance"
import { ErrorState, LoadingBlock } from "@/components/shared/states"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { apiGet } from "@/lib/api"
import { formatMoney, formatMoneyCompact, formatNumber, formatPercent, titleCase } from "@/lib/format"

interface Roi {
  data_provenance: string
  observed: Record<string, number>
  estimated: { hours_saved: number; potential_recovery_if_assumed_rate: number; assumptions: Record<string, number>; method: string }
}
const MONEY = new Set(["revenue_at_risk", "recovered_revenue"])

export default function RoiPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["roi"], queryFn: () => apiGet<Roi>("/roi") })
  if (isLoading) return <LoadingBlock rows={8} />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  return (
    <>
      <PageHeader
        title="ROI"
        description="Observed figures are queries over recorded activity. Estimated figures multiply observed counts by the assumptions shown below and are never presented as results."
        actions={data.data_provenance === "synthetic_demo" ? <Provenance kind="synthetic" /> : null}
      />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Observed <Provenance kind="observed" />
          </CardTitle>
          <CardDescription>Counted from the database</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(data.observed).map(([k, v]) => (
            <div key={k} className="rounded-lg border p-4">
              <p className="text-xs text-muted-foreground">{titleCase(k.replace("_usd_estimated", " (USD, est.)"))}</p>
              <p className="mt-1 text-xl font-semibold tabular">
                {MONEY.has(k) ? formatMoneyCompact(v) : k.includes("usd") ? `$${v.toFixed(4)}` : formatNumber(v)}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Estimated <Provenance kind="estimated" />
          </CardTitle>
          <CardDescription>{data.estimated.method}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-3">
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Estimated hours saved</p>
            <p className="mt-1 text-2xl font-semibold tabular">{data.estimated.hours_saved} h</p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Potential recovery at assumed rate</p>
            <p className="mt-1 text-2xl font-semibold tabular">{formatMoney(data.estimated.potential_recovery_if_assumed_rate)}</p>
            <p className="text-xs text-muted-foreground">
              = revenue at risk × {formatPercent(data.estimated.assumptions.assumed_recovery_rate)} — an assumption, not a measurement
            </p>
          </div>
          <div className="rounded-lg border p-4 text-sm">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Assumptions (editable in Settings)</p>
            {Object.entries(data.estimated.assumptions).map(([k, v]) => (
              <p key={k} className="flex justify-between gap-2">
                <span className="text-muted-foreground">{titleCase(k)}</span>
                <span className="tabular">{v}</span>
              </p>
            ))}
          </div>
        </CardContent>
      </Card>
    </>
  )
}
