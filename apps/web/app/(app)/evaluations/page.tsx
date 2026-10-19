"use client"

import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, ChevronDown, ChevronRight, FlaskConical, XCircle } from "lucide-react"
import { Fragment, useState } from "react"

import { PageHeader } from "@/components/shared/page-header"
import { Provenance } from "@/components/shared/provenance"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { apiGet } from "@/lib/api"
import { formatDateTime, titleCase } from "@/lib/format"
import type { EvalRun } from "@/lib/types"
import { cn } from "@/lib/utils"

const SUITES: { key: "rag" | "agent" | "copilot"; title: string; blurb: string; command: string }[] = [
  {
    key: "rag",
    title: "RAG quality",
    blurb: "Retrieval hit-rate & MRR, insufficient-evidence handling, injection withholding; live: Ragas faithfulness, answer relevancy, context precision/recall + citation & policy-fact accuracy.",
    command: "uv run --project apps/api python -m evals.run --suite rag",
  },
  {
    key: "agent",
    title: "Agent quality",
    blurb: "42 workflow scenarios: approval & policy compliance, tool selection/arguments, DB updates, hallucination detection, failure recovery.",
    command: "uv run --project apps/api python -m evals.run --suite agent",
  },
  {
    key: "copilot",
    title: "Copilot tool use",
    blurb: "Live only: does the model pick the right read-only tool with the right arguments?",
    command: "uv run --project apps/api python -m evals.run --suite copilot --mode live",
  },
]
const LOWER_IS_BETTER = new Set(["hallucination_rate"])

function MetricRow({ name, m }: { name: string; m: { value: number; n: number; description?: string } }) {
  const good = LOWER_IS_BETTER.has(name) ? m.value <= 0.05 : m.value >= 0.9
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <Tooltip>
          <TooltipTrigger className="cursor-help text-left underline decoration-dotted underline-offset-2">{titleCase(name)}</TooltipTrigger>
          <TooltipContent className="max-w-xs">{m.description || name}</TooltipContent>
        </Tooltip>
        <span className="font-semibold tabular">
          {m.value.toFixed(3)} <span className="text-xs font-normal text-muted-foreground">n={m.n}</span>
        </span>
      </div>
      <Progress value={Math.min(m.value * 100, 100)} className={cn("h-1.5", !good && "[&>div]:bg-warning")} />
    </div>
  )
}

export default function EvaluationsPage() {
  const [selected, setSelected] = useState<string | null>(null)
  const [openCase, setOpenCase] = useState<string | null>(null)
  const summary = useQuery({ queryKey: ["eval-summary"], queryFn: () => apiGet<{ suites: Record<string, EvalRun | null> }>("/evaluations/summary") })
  const runs = useQuery({ queryKey: ["eval-runs"], queryFn: () => apiGet<{ items: EvalRun[] }>("/evaluations/runs") })
  const detail = useQuery({
    queryKey: ["eval-run", selected],
    queryFn: () => apiGet<EvalRun>(`/evaluations/runs/${selected}`),
    enabled: Boolean(selected),
  })

  return (
    <>
      <PageHeader
        title="Evaluations"
        description="Only measured numbers are shown. Offline runs use a scripted LLM to test orchestration, guardrails and database effects; live runs call the real model. All runs use the synthetic dataset."
      />
      {summary.isLoading ? <LoadingBlock rows={6} /> : null}
      {summary.error ? <ErrorState error={summary.error} /> : null}
      <div className="grid gap-4 lg:grid-cols-3">
        {SUITES.map((s) => {
          const run = summary.data?.suites[s.key]
          return (
            <Card key={s.key} className={cn(run && "cursor-pointer transition-shadow hover:shadow-md")} onClick={() => run && setSelected(run.id)}>
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2">
                  {s.title}
                  {run ? <Provenance kind={run.mode === "live" ? "live_eval" : "offline_eval"} /> : <Provenance kind="not_evaluated" />}
                </CardTitle>
                <CardDescription>{s.blurb}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {run ? (
                  <>
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>
                        {run.dataset_version} · {run.model ?? (run.suite === "rag" ? "retrieval only, no LLM" : "scripted LLM")}
                      </span>
                      <span>{formatDateTime(run.finished_at ?? run.created_at)}</span>
                    </div>
                    <div className="flex items-center gap-2 text-sm">
                      <span className="text-2xl font-semibold tabular">
                        {run.cases_passed}/{run.cases_total}
                      </span>
                      <span className="text-muted-foreground">cases passed · Demo evaluation</span>
                    </div>
                    {Object.entries(run.metrics)
                      .filter(([k]) => k !== "case_pass_rate")
                      .map(([k, m]) => (
                        <MetricRow key={k} name={k} m={m} />
                      ))}
                  </>
                ) : (
                  <div className="space-y-2">
                    <p className="text-sm font-medium">Not evaluated yet</p>
                    <code className="block rounded bg-muted px-2 py-1.5 text-[11px]">{s.command}</code>
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>

      <Card className="mt-6 py-0">
        <CardHeader className="pt-6">
          <CardTitle>Run history</CardTitle>
          <CardDescription>Click a run to see every case</CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          {runs.data?.items.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Suite</TableHead>
                  <TableHead>Mode</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead className="text-right">Passed</TableHead>
                  <TableHead className="pr-6">Finished</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.data.items.map((r) => (
                  <TableRow key={r.id} className={cn("cursor-pointer", selected === r.id && "bg-muted/50")} onClick={() => setSelected(r.id)}>
                    <TableCell className="pl-6 font-medium uppercase">{r.suite}</TableCell>
                    <TableCell>
                      <Provenance kind={r.mode === "live" ? "live_eval" : "offline_eval"} />
                    </TableCell>
                    <TableCell className="text-sm">{r.model ?? (r.suite === "rag" ? "retrieval only" : "scripted LLM")}</TableCell>
                    <TableCell className="text-right tabular">
                      {r.cases_passed}/{r.cases_total}
                    </TableCell>
                    <TableCell className="pr-6 text-sm text-muted-foreground">{formatDateTime(r.finished_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="p-6">
              <EmptyState icon={FlaskConical} title="No evaluation runs recorded" description="Run python -m evals.run (see README)." />
            </div>
          )}
        </CardContent>
      </Card>

      {selected && detail.data ? (
        <Card className="mt-6 py-0">
          <CardHeader className="pt-6">
            <CardTitle className="flex items-center gap-2">
              {detail.data.suite.toUpperCase()} cases <Provenance kind={detail.data.mode === "live" ? "live_eval" : "offline_eval"} />
            </CardTitle>
            <CardDescription>{detail.data.notes}</CardDescription>
          </CardHeader>
          <CardContent className="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8 pl-4" />
                  <TableHead>Case</TableHead>
                  <TableHead>Checks</TableHead>
                  <TableHead className="pr-6 text-right">Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detail.data.results?.map((r) => (
                  <Fragment key={r.case_key}>
                    <TableRow className="cursor-pointer" onClick={() => setOpenCase(openCase === r.case_key ? null : r.case_key)}>
                      <TableCell className="pl-4">{openCase === r.case_key ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</TableCell>
                      <TableCell>
                        <p className="font-mono text-xs">{r.case_key}</p>
                        <p className="text-sm text-muted-foreground">{r.description}</p>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(r.scores).map(([k, v]) => (
                            <Badge
                              key={k}
                              variant="outline"
                              className={cn("text-[10px]", v === true && "text-success", v === false && "border-destructive/40 text-destructive")}
                            >
                              {k}
                              {typeof v === "number" ? ` ${v.toFixed(2)}` : ""}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="pr-6 text-right">
                        {r.passed === null ? (
                          <span className="text-xs text-muted-foreground">scored</span>
                        ) : r.passed ? (
                          <CheckCircle2 className="ml-auto size-5 text-success" />
                        ) : (
                          <XCircle className="ml-auto size-5 text-destructive" />
                        )}
                      </TableCell>
                    </TableRow>
                    {openCase === r.case_key ? (
                      <TableRow className="bg-muted/30 hover:bg-muted/30">
                        <TableCell />
                        <TableCell colSpan={3}>
                          <div className="grid gap-3 py-2 text-xs md:grid-cols-2">
                            <div>
                              <p className="mb-1 font-semibold">Expected</p>
                              <pre className="max-h-72 overflow-auto rounded bg-background p-2">{JSON.stringify(r.expected, null, 2)}</pre>
                            </div>
                            <div>
                              <p className="mb-1 font-semibold">Observed</p>
                              <pre className="max-h-72 overflow-auto rounded bg-background p-2">{JSON.stringify(r.output, null, 2)}</pre>
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
    </>
  )
}
