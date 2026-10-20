"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FileSpreadsheet, Loader2, Upload } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { PageHeader } from "@/components/shared/page-header"
import { EmptyState, ErrorState } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiGet, apiUpload, errorMessage } from "@/lib/api"
import { formatDateTime, titleCase } from "@/lib/format"
import type { Page } from "@/lib/types"

type Entity = "customers" | "leads" | "quotes" | "sales_activities"
interface IngestResult {
  job_id: string
  entity: string
  status: string
  rows_total: number
  inserted: number
  updated: number
  duplicates: number
  rejected: number
  errors: { row: number; field: string; message: string }[]
  dry_run: boolean
}
interface Job extends Omit<IngestResult, "job_id" | "dry_run"> {
  id: string
  filename: string
  created_at: string
}

const STATUS_STYLE: Record<string, string> = {
  completed: "text-success border-success/30 bg-success/10",
  completed_with_errors: "border-warning/50 bg-warning/10",
  failed: "text-destructive border-destructive/30 bg-destructive/10",
}

export default function ImportPage() {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [entity, setEntity] = useState<Entity>("customers")
  const [dryRun, setDryRun] = useState(true)
  const templates = useQuery({ queryKey: ["templates"], queryFn: () => apiGet<{ entities: Record<Entity, string[]> }>("/ingest/templates") })
  const jobs = useQuery({ queryKey: ["ingest-jobs"], queryFn: () => apiGet<Page<Job>>("/ingest/jobs", { limit: 10 }) })
  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append("file", file)
      form.append("dry_run", String(dryRun))
      return apiUpload<IngestResult>(`/ingest/${entity}`, form)
    },
    onSuccess: (r) => {
      toast[r.rejected ? "warning" : "success"](`${r.dry_run ? "Dry run: " : ""}${r.inserted} inserted · ${r.updated} updated · ${r.duplicates} duplicates · ${r.rejected} rejected`)
      qc.invalidateQueries()
    },
    onError: (e) => toast.error("Import rejected", { description: errorMessage(e) }),
  })
  const result = upload.data

  return (
    <>
      <PageHeader
        title="Data import"
        description="CSV or JSON. Every row is validated, normalised (names, emails, ₹ amounts like “4.8L”, dates), de-duplicated and matched to existing customers before anything is written."
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Upload</CardTitle>
            <CardDescription>Pipeline: raw file → validation → normalisation → de-duplication → entity resolution → PostgreSQL</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <Select value={entity} onValueChange={(v) => setEntity(v as Entity)}>
                <SelectTrigger className="w-52">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(["customers", "leads", "quotes", "sales_activities"] as Entity[]).map((e) => (
                    <SelectItem key={e} value={e}>
                      {titleCase(e)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={dryRun} onCheckedChange={setDryRun} /> Dry run (validate only)
              </label>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.json"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) upload.mutate(f)
                  e.target.value = ""
                }}
              />
              <Button onClick={() => fileRef.current?.click()} disabled={upload.isPending} className="ml-auto">
                {upload.isPending ? <Loader2 className="animate-spin" /> : <Upload />} Choose file
              </Button>
            </div>
            {upload.error ? <ErrorState error={upload.error} title="File rejected" /> : null}
            {result ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className={STATUS_STYLE[result.status]}>
                    {titleCase(result.status)}
                  </Badge>
                  {result.dry_run ? <Badge variant="secondary">dry run — nothing written</Badge> : null}
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                  {[
                    ["Rows", result.rows_total],
                    ["Inserted", result.inserted],
                    ["Updated", result.updated],
                    ["Duplicates", result.duplicates],
                    ["Rejected", result.rejected],
                  ].map(([k, v]) => (
                    <div key={k} className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">{k}</p>
                      <p className="text-lg font-semibold tabular">{v}</p>
                    </div>
                  ))}
                </div>
                {result.errors.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Row</TableHead>
                        <TableHead>Field</TableHead>
                        <TableHead>Problem</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.errors.slice(0, 50).map((e, i) => (
                        <TableRow key={i}>
                          <TableCell className="tabular">{e.row}</TableCell>
                          <TableCell className="font-mono text-xs">{e.field}</TableCell>
                          <TableCell className="text-sm">{e.message}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileSpreadsheet className="size-4" /> Expected columns
            </CardTitle>
            <CardDescription>Header names are case-insensitive. Sample files: data/demo/*.csv</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex flex-wrap gap-1.5">
              {templates.data?.entities[entity]?.map((c) => (
                <Badge key={c} variant="outline" className="font-mono text-[11px]">
                  {c}
                </Badge>
              ))}
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              {(["customers", "leads", "quotes", "sales_activities"] as Entity[]).map((e) => (
                <a key={e} href={`/samples/${e}.csv`} download className="text-xs text-primary hover:underline">
                  {e}.csv
                </a>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      <Card className="mt-6 py-0">
        <CardHeader className="pt-6">
          <CardTitle>Recent imports</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          {jobs.data?.items.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">File</TableHead>
                  <TableHead>Entity</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Inserted</TableHead>
                  <TableHead className="text-right">Duplicates</TableHead>
                  <TableHead className="text-right">Rejected</TableHead>
                  <TableHead className="pr-6">When</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.data.items.map((j) => (
                  <TableRow key={j.id}>
                    <TableCell className="pl-6 font-mono text-xs">{j.filename}</TableCell>
                    <TableCell>{titleCase(j.entity)}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={STATUS_STYLE[j.status]}>
                        {titleCase(j.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right tabular">{j.inserted}</TableCell>
                    <TableCell className="text-right tabular">{j.duplicates}</TableCell>
                    <TableCell className="text-right tabular">{j.rejected}</TableCell>
                    <TableCell className="pr-6 text-sm text-muted-foreground">{formatDateTime(j.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="p-6">
              <EmptyState title="No imports yet" />
            </div>
          )}
        </CardContent>
      </Card>
    </>
  )
}
