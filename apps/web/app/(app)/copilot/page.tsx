"use client"

import { useMutation } from "@tanstack/react-query"
import { ExternalLink, Loader2, Send, Wrench } from "lucide-react"
import { useState } from "react"

import { PageHeader } from "@/components/shared/page-header"
import { ErrorState } from "@/components/shared/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { apiSend } from "@/lib/api"
import { formatMs } from "@/lib/format"

interface CopilotAnswer {
  question: string
  answer: string
  model: string
  tool_calls: { step: number; tool: string; arguments?: Record<string, unknown>; ok: boolean; error?: string | null; latency_ms?: number; citations?: { document: string; section: string }[] }[]
  usage: { input_tokens: number; output_tokens: number; estimated_cost_usd: number }
  latency_ms: number
  trace_url: string | null
}

const EXAMPLES = [
  "Which deals are critical right now?",
  "Which sales rep has the most revenue at risk?",
  "What's going on with Vertex Industrial Solutions and what should we do next?",
  "What discount can a sales rep give without manager approval?",
  "A customer says a competitor quoted 15% lower. How should we respond?",
]

export default function CopilotPage() {
  const [question, setQuestion] = useState("")
  const [history, setHistory] = useState<CopilotAnswer[]>([])
  const ask = useMutation({
    mutationFn: (q: string) => apiSend<CopilotAnswer>("POST", "/copilot/ask", { question: q }),
    onSuccess: (a) => {
      setHistory((h) => [a, ...h])
      setQuestion("")
    },
  })
  return (
    <>
      <PageHeader
        title="Revenue Copilot"
        description="Ask in plain language. The model answers only by calling read-only tools (the same contracts the MCP server exposes) — every call and argument is shown."
      />
      <Card>
        <CardContent className="space-y-3">
          <Textarea
            rows={3}
            placeholder="e.g. Which critical deals belong to Priya Nair?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && question.trim()) ask.mutate(question)
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            {EXAMPLES.map((ex) => (
              <Button key={ex} size="sm" variant="outline" className="h-auto whitespace-normal py-1 text-left text-xs" onClick={() => ask.mutate(ex)} disabled={ask.isPending}>
                {ex}
              </Button>
            ))}
            <Button className="ml-auto" onClick={() => ask.mutate(question)} disabled={ask.isPending || question.trim().length < 3}>
              {ask.isPending ? <Loader2 className="animate-spin" /> : <Send />} Ask
            </Button>
          </div>
        </CardContent>
      </Card>
      {ask.error ? (
        <div className="mt-4">
          <ErrorState error={ask.error} title="The copilot could not answer" />
        </div>
      ) : null}
      <div className="mt-6 space-y-4">
        {history.map((a, i) => (
          <Card key={i}>
            <CardHeader>
              <CardTitle className="text-base">{a.question}</CardTitle>
              <CardDescription className="flex flex-wrap items-center gap-2">
                {a.model} · {formatMs(a.latency_ms)} · {a.usage.input_tokens + a.usage.output_tokens} tokens · ${a.usage.estimated_cost_usd.toFixed(5)}
                {a.trace_url ? (
                  <a href={a.trace_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                    trace <ExternalLink className="size-3" />
                  </a>
                ) : null}
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-6 lg:grid-cols-3">
              <div className="whitespace-pre-line text-sm leading-relaxed lg:col-span-2">{a.answer}</div>
              <div className="space-y-2">
                <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  <Wrench className="size-3.5" /> Tool calls ({a.tool_calls.length})
                </p>
                {a.tool_calls.length ? (
                  a.tool_calls.map((t, j) => (
                    <div key={j} className="rounded-lg border p-2 text-xs">
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary" className="font-mono">
                          {t.tool}
                        </Badge>
                        <span className={t.ok ? "text-success" : "text-destructive"}>{t.ok ? "ok" : "error"}</span>
                        <span className="ml-auto text-muted-foreground">{formatMs(t.latency_ms)}</span>
                      </div>
                      <pre className="mt-1 overflow-auto text-muted-foreground">{JSON.stringify(t.arguments ?? {}, null, 1)}</pre>
                      {t.error ? <p className="text-destructive">{t.error}</p> : null}
                      {t.citations?.length ? (
                        <p className="mt-1 text-muted-foreground">sources: {t.citations.map((c) => `${c.document} › ${c.section}`).join("; ")}</p>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <p className="text-xs text-muted-foreground">No tools called.</p>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  )
}
