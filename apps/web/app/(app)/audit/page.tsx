"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Search } from "lucide-react"
import { useState } from "react"

import { AuditTable } from "@/components/shared/audit-table"
import { PageHeader } from "@/components/shared/page-header"
import { Pagination } from "@/components/shared/pagination"
import { ErrorState, LoadingBlock } from "@/components/shared/states"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { apiGet } from "@/lib/api"
import type { AuditEntry, Page } from "@/lib/types"

export default function AuditPage() {
  const [actor, setActor] = useState("all")
  const [result, setResult] = useState("all")
  const [action, setAction] = useState("")
  const [reads, setReads] = useState(false)
  const [offset, setOffset] = useState(0)
  const { data, error, isLoading } = useQuery({
    queryKey: ["audit", actor, result, action, reads, offset],
    queryFn: () =>
      apiGet<Page<AuditEntry>>("/audit", {
        actor_type: actor === "all" ? undefined : actor,
        result: result === "all" ? undefined : result,
        action,
        include_reads: reads,
        limit: 50,
        offset,
      }),
    placeholderData: keepPreviousData,
  })
  const reset = <T,>(fn: (v: T) => void) => (v: T) => {
    setOffset(0)
    fn(v)
  }
  return (
    <>
      <PageHeader
        title="Audit log"
        description="Append-only record of every user, agent and system action: who, what, which tool, inputs, outputs, approval and result. Agent rows link to their run and Langfuse trace."
      />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        <div className="relative sm:w-72">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Action, e.g. approval or tool.send_email" className="pl-8" value={action} onChange={(e) => reset(setAction)(e.target.value)} />
        </div>
        <Select value={actor} onValueChange={reset(setActor)}>
          <SelectTrigger className="sm:w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All actors</SelectItem>
            <SelectItem value="user">Users</SelectItem>
            <SelectItem value="agent">Agents</SelectItem>
            <SelectItem value="system">System</SelectItem>
          </SelectContent>
        </Select>
        <Select value={result} onValueChange={reset(setResult)}>
          <SelectTrigger className="sm:w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All results</SelectItem>
            <SelectItem value="success">Success</SelectItem>
            <SelectItem value="failure">Failure</SelectItem>
            <SelectItem value="blocked">Blocked</SelectItem>
          </SelectContent>
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={reads} onCheckedChange={reset(setReads)} /> Include read-only tool calls
        </label>
      </div>
      {error ? <ErrorState error={error} /> : null}
      {isLoading ? <LoadingBlock rows={8} /> : data ? <AuditTable entries={data.items} showCustomer /> : null}
      {data ? <Pagination total={data.total} limit={50} offset={offset} onChange={setOffset} /> : null}
    </>
  )
}
