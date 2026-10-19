"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, BookOpen, CheckCircle2, CircleAlert, FileUp, Loader2, Search, ShieldAlert } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { PageHeader } from "@/components/shared/page-header"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/shared/states"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { apiGet, apiSend, apiUpload, errorMessage } from "@/lib/api"
import { formatDate, formatNumber, titleCase } from "@/lib/format"
import type { GroundedAnswer, KnowledgeDoc, RetrievedEvidence } from "@/lib/types"
import { cn } from "@/lib/utils"

const STATUS_STYLE: Record<GroundedAnswer["status"], string> = {
  ANSWERED: "bg-success/12 text-success border-success/30",
  PARTIALLY_SUPPORTED: "bg-warning/15 border-warning/40",
  INSUFFICIENT_EVIDENCE: "bg-muted text-muted-foreground",
  LLM_FALLBACK: "bg-warning/15 border-warning/40",
}

function EvidenceCard({ e }: { e: RetrievedEvidence }) {
  return (
    <div className={cn("rounded-lg border p-3", e.flagged_injection && "border-warning/60 bg-warning/5")}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="secondary" className="font-mono">
          {e.evidence_id}
        </Badge>
        <span className="font-medium">{e.document_title}</span>
        <span className="text-muted-foreground">› {e.section}</span>
        {e.flagged_injection ? (
          <Badge variant="outline" className="border-warning/60 text-[10px]">
            <ShieldAlert className="size-3" /> possible injection
          </Badge>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground tabular">
        <span>BM25 rank {e.scores.bm25_rank ?? "—"}</span>
        <span>vector rank {e.scores.vector_rank ?? "—"}</span>
        <span>RRF {e.scores.rrf.toFixed(4)}</span>
        <span className="font-medium text-foreground">rerank {e.scores.rerank?.toFixed(3) ?? "—"}</span>
      </div>
      <p className="mt-2 line-clamp-5 whitespace-pre-line text-sm text-muted-foreground">{e.content}</p>
    </div>
  )
}

export default function KnowledgePage() {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState("What discount can a salesperson offer without manager approval?")
  const docs = useQuery({ queryKey: ["documents"], queryFn: () => apiGet<{ items: KnowledgeDoc[]; totals: { documents: number; chunks: number; flagged: number } }>("/knowledge/documents") })
  const search = useMutation({
    mutationFn: (q: string) => apiSend<{ status: string; evidence: RetrievedEvidence[]; timings_ms: Record<string, number>; candidates: Record<string, number>; reranker: string | null }>("POST", "/knowledge/search", { query: q }),
  })
  const ask = useMutation({ mutationFn: (q: string) => apiSend<GroundedAnswer>("POST", "/knowledge/ask", { question: q }) })
  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append("file", file)
      return apiUpload<{ title: string; chunks: number; duplicate: boolean; injection_findings: unknown[] }>("/knowledge/documents", form)
    },
    onSuccess: (r) => {
      if (r.duplicate) toast.message("Already indexed", { description: r.title })
      else toast.success(`Indexed “${r.title}”`, { description: `${r.chunks} chunks${r.injection_findings.length ? " · ⚠ instruction-like text flagged" : ""}` })
      qc.invalidateQueries({ queryKey: ["documents"] })
    },
    onError: (e) => toast.error("Upload rejected", { description: errorMessage(e) }),
  })
  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => apiSend("PATCH", `/knowledge/documents/${id}`, undefined, { is_active: active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
    onError: (e) => toast.error("Update failed", { description: errorMessage(e) }),
  })

  return (
    <>
      <PageHeader
        title="Knowledge base"
        description="Policies, playbooks and SOPs used by hybrid RAG (BM25 + pgvector → reciprocal rank fusion → cross-encoder rerank). Transactional CRM data is never retrieved this way."
        actions={
          <>
            <input
              ref={fileRef}
              type="file"
              accept=".md,.markdown,.txt,.pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) upload.mutate(f)
                e.target.value = ""
              }}
            />
            <Button onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
              {upload.isPending ? <Loader2 className="animate-spin" /> : <FileUp />} Upload document
            </Button>
          </>
        }
      />
      <Tabs defaultValue="ask">
        <TabsList>
          <TabsTrigger value="ask">Ask (grounded)</TabsTrigger>
          <TabsTrigger value="search">Search inspector</TabsTrigger>
          <TabsTrigger value="docs">Documents {docs.data ? `(${docs.data.totals.documents})` : ""}</TabsTrigger>
        </TabsList>

        <TabsContent value="ask" className="mt-4 space-y-4">
          <Card>
            <CardContent className="flex flex-col gap-2 sm:flex-row">
              <Input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask.mutate(query)} />
              <Button onClick={() => ask.mutate(query)} disabled={ask.isPending || query.length < 3}>
                {ask.isPending ? <Loader2 className="animate-spin" /> : <BookOpen />} Ask
              </Button>
            </CardContent>
          </Card>
          {ask.error ? <ErrorState error={ask.error} /> : null}
          {ask.data ? (
            <Card>
              <CardHeader>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className={STATUS_STYLE[ask.data.status]}>
                    {ask.data.status.replace(/_/g, " ")}
                  </Badge>
                  {ask.data.claims.length ? (
                    <span className="text-xs text-muted-foreground">
                      {ask.data.claims.filter((c) => c.supported).length}/{ask.data.claims.length} claims verified against cited passages
                    </span>
                  ) : null}
                  {ask.data.model ? <span className="ml-auto text-xs text-muted-foreground">{ask.data.model}</span> : null}
                </div>
                <CardTitle className="text-base">{ask.data.question}</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-6 lg:grid-cols-2">
                <div className="space-y-4">
                  {ask.data.answer ? <p className="text-sm leading-relaxed">{ask.data.answer}</p> : null}
                  {ask.data.status === "INSUFFICIENT_EVIDENCE" ? (
                    <p className="text-sm text-muted-foreground">The knowledge base does not contain evidence to answer this. Nothing was made up.</p>
                  ) : null}
                  {ask.data.claims.length ? (
                    <ul className="space-y-2">
                      {ask.data.claims.map((c) => (
                        <li key={c.claim} className="flex items-start gap-2 text-sm">
                          {c.supported ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />}
                          <div>
                            <p>{c.claim}</p>
                            <p className="text-xs text-muted-foreground">
                              {c.supported ? `${c.source_document} › ${c.source_section} · support ${c.support_score.toFixed(2)} · retrieval ${c.retrieval_score?.toFixed(2)}` : c.problems.join("; ")}
                            </p>
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {ask.data.withheld_evidence.length ? (
                    <Alert>
                      <AlertTriangle />
                      <AlertTitle>Passages withheld from the model</AlertTitle>
                      <AlertDescription>
                        {ask.data.withheld_evidence.map((w) => `${w.document} › ${w.section}`).join("; ")} — contained instruction-like text (possible prompt injection).
                      </AlertDescription>
                    </Alert>
                  ) : null}
                  {ask.data.limitations.length ? (
                    <ul className="list-disc pl-4 text-xs text-muted-foreground">
                      {ask.data.limitations.map((l) => (
                        <li key={l}>{l}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Retrieved evidence</p>
                  {ask.data.evidence.length ? ask.data.evidence.map((e) => <EvidenceCard key={e.chunk_id} e={e} />) : <p className="text-sm text-muted-foreground">None above the relevance floor.</p>}
                </div>
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>

        <TabsContent value="search" className="mt-4 space-y-4">
          <Card>
            <CardContent className="flex flex-col gap-2 sm:flex-row">
              <Input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search.mutate(query)} />
              <Button variant="outline" onClick={() => search.mutate(query)} disabled={search.isPending || query.length < 3}>
                {search.isPending ? <Loader2 className="animate-spin" /> : <Search />} Search
              </Button>
            </CardContent>
          </Card>
          {search.error ? <ErrorState error={search.error} /> : null}
          {search.data ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                  <Badge variant="outline">{search.data.status}</Badge>
                  <span className="text-sm font-normal text-muted-foreground">
                    candidates: BM25 {search.data.candidates.bm25} · vector {search.data.candidates.vector} · fused {search.data.candidates.fused} · reranker {search.data.reranker ?? "off"}
                  </span>
                </CardTitle>
                <CardDescription className="tabular">
                  {Object.entries(search.data.timings_ms)
                    .map(([k, v]) => `${k} ${v}ms`)
                    .join(" · ")}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {search.data.evidence.length ? search.data.evidence.map((e) => <EvidenceCard key={e.chunk_id} e={e} />) : <EmptyState title="INSUFFICIENT_EVIDENCE" description="No passage met the relevance floor." />}
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>

        <TabsContent value="docs" className="mt-4">
          {docs.isLoading ? <LoadingBlock /> : null}
          {docs.error ? <ErrorState error={docs.error} /> : null}
          {docs.data ? (
            <Card className="py-0">
              <CardContent className="px-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="pl-6">Document</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Version</TableHead>
                      <TableHead className="text-right">Chunks</TableHead>
                      <TableHead>Security scan</TableHead>
                      <TableHead>Indexed</TableHead>
                      <TableHead className="pr-6">Active</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {docs.data.items.map((d) => (
                      <TableRow key={d.id}>
                        <TableCell className="pl-6">
                          <p className="font-medium">{d.title}</p>
                          <p className="text-xs text-muted-foreground">
                            {d.source} · {formatNumber(d.char_count)} chars
                          </p>
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{titleCase(d.document_type)}</Badge>
                        </TableCell>
                        <TableCell className="text-sm">{d.version}</TableCell>
                        <TableCell className="text-right tabular">{d.chunk_count}</TableCell>
                        <TableCell>
                          {d.injection_findings.length ? (
                            <Badge variant="outline" className="border-warning/60 bg-warning/10" title={d.injection_findings.map((f) => `${f.pattern}: ${f.excerpt}`).join("\n")}>
                              <ShieldAlert className="size-3" /> {d.injection_findings.length} injection pattern(s)
                            </Badge>
                          ) : (
                            <span className="text-xs text-success">clean</span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">{formatDate(d.created_at)}</TableCell>
                        <TableCell className="pr-6">
                          <Switch checked={d.is_active} onCheckedChange={(v) => toggle.mutate({ id: d.id, active: v })} aria-label="Active" />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>
      </Tabs>
    </>
  )
}
