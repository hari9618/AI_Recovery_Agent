"use client"

import { Bot, ChevronDown, ChevronRight, Cog, User } from "lucide-react"
import { Fragment, useState } from "react"

import { EmptyState } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDateTime, formatMs } from "@/lib/format"
import type { AuditEntry } from "@/lib/types"
import { cn } from "@/lib/utils"

const RESULT_STYLE: Record<string, string> = {
  success: "text-success border-success/30 bg-success/10",
  failure: "text-destructive border-destructive/30 bg-destructive/10",
  blocked: "text-foreground border-warning/50 bg-warning/15",
  pending: "text-muted-foreground",
}
const ACTOR_ICON = { user: User, agent: Bot, system: Cog }

export function AuditTable({ entries, showCustomer = false }: { entries: AuditEntry[]; showCustomer?: boolean }) {
  const [open, setOpen] = useState<string | null>(null)
  if (!entries.length) return <EmptyState title="No audit entries" />
  return (
    <Card className="py-0">
      <CardContent className="px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8 pl-4" />
              <TableHead>When</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Action</TableHead>
              {showCustomer ? <TableHead>Customer</TableHead> : null}
              <TableHead>Result</TableHead>
              <TableHead className="pr-6 text-right">Latency</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((e) => {
              const Icon = ACTOR_ICON[e.actor_type]
              return (
                <Fragment key={e.id}>
                  <TableRow className="cursor-pointer" onClick={() => setOpen(open === e.id ? null : e.id)}>
                    <TableCell className="pl-4">{open === e.id ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{formatDateTime(e.occurred_at)}</TableCell>
                    <TableCell>
                      <span className="flex items-center gap-1.5 text-sm">
                        <Icon className="size-3.5 text-muted-foreground" />
                        {e.agent ?? e.actor_name ?? e.actor_type}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="font-mono text-xs">{e.action}</span>
                    </TableCell>
                    {showCustomer ? <TableCell className="text-sm">{e.customer_name ?? "—"}</TableCell> : null}
                    <TableCell>
                      <Badge variant="outline" className={cn("capitalize", RESULT_STYLE[e.result])}>
                        {e.result}
                      </Badge>
                    </TableCell>
                    <TableCell className="pr-6 text-right text-xs text-muted-foreground tabular">{formatMs(e.latency_ms)}</TableCell>
                  </TableRow>
                  {open === e.id ? (
                    <TableRow className="bg-muted/30 hover:bg-muted/30">
                      <TableCell />
                      <TableCell colSpan={showCustomer ? 6 : 5} className="py-3">
                        <div className="grid grid-cols-1 gap-3 text-xs md:grid-cols-2">
                          <div>
                            <p className="mb-1 font-semibold">Input</p>
                            <pre className="max-h-64 overflow-auto rounded bg-background p-2">{JSON.stringify(e.input, null, 2)}</pre>
                          </div>
                          <div>
                            <p className="mb-1 font-semibold">Output</p>
                            <pre className="max-h-64 overflow-auto rounded bg-background p-2">{JSON.stringify(e.output, null, 2)}</pre>
                          </div>
                          <p className="text-muted-foreground md:col-span-2">
                            {e.tool ? `tool ${e.tool} · ` : ""}
                            {e.agent_run_id ? `agent run ${e.agent_run_id.slice(0, 8)} · ` : ""}
                            {e.approval_request_id ? `approval ${e.approval_request_id.slice(0, 8)} · ` : ""}
                            {e.trace_id ? `trace ${e.trace_id}` : "no trace"}
                          </p>
                        </div>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </Fragment>
              )
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
