"use client"

import { CheckCircle2, ExternalLink, Trash2, Wrench, XCircle } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"

import { TOOL_LABEL, useChat } from "@/components/chat/chat-provider"
import { ChatMessages, Composer } from "@/components/chat/chat-thread"
import { PageHeader } from "@/components/shared/page-header"
import { Button } from "@/components/ui/button"
import { formatMs } from "@/lib/format"

function TracePanel() {
  const { messages, selectedId } = useChat()
  const answers = messages.filter((m) => m.role === "assistant")
  const selected = answers.find((m) => m.id === selectedId) ?? answers[answers.length - 1]
  if (!selected || selected.role !== "assistant") {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 text-center">
        <Wrench className="size-6 text-bronze" />
        <p className="font-display mt-3 text-lg font-semibold">Tool trace</p>
        <p className="mt-1 text-sm text-muted-foreground">Every tool the model calls, with its exact arguments, sources and timing, appears here.</p>
      </div>
    )
  }
  const m = selected.meta
  return (
    <AnimatePresence mode="wait">
      <motion.div key={selected.id} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} className="space-y-4 p-5">
        <div>
          <span className="eyebrow">Tool trace</span>
          <p className="mt-2 line-clamp-2 text-sm font-medium">{m.question}</p>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          {[
            ["Latency", formatMs(m.latency_ms)],
            ["Tokens", (m.usage.input_tokens + m.usage.output_tokens).toLocaleString("en-IN")],
            ["Cost", `$${m.usage.estimated_cost_usd.toFixed(4)}`],
          ].map(([k, v]) => (
            <div key={k} className="rounded-xl border bg-background px-2 py-2">
              <p className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">{k}</p>
              <p className="money mt-0.5 text-sm font-semibold">{v}</p>
            </div>
          ))}
        </div>
        <ol className="relative space-y-3 border-l border-dashed pl-5">
          {m.tool_calls.length ? (
            m.tool_calls.map((t, i) => (
              <li key={i} className="relative">
                <span className="absolute top-1 -left-[27px] flex size-3.5 items-center justify-center rounded-full bg-background">
                  {t.ok ? <CheckCircle2 className="size-3.5 text-success" /> : <XCircle className="size-3.5 text-destructive" />}
                </span>
                <div className="rounded-xl border bg-card p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{TOOL_LABEL[t.tool] ?? t.tool}</span>
                    <span className="money text-muted-foreground">{formatMs(t.latency_ms)}</span>
                  </div>
                  <p className="mt-0.5 font-mono text-[10.5px] text-muted-foreground">
                    step {t.step} · {t.tool}
                  </p>
                  <pre className="mt-2 overflow-auto rounded-lg bg-muted p-2 font-mono text-[10.5px] leading-relaxed">{JSON.stringify(t.arguments ?? {}, null, 2)}</pre>
                  {t.citations?.length ? (
                    <ul className="mt-2 space-y-1">
                      {t.citations.map((c, j) => (
                        <li key={j} className="flex items-center justify-between gap-2 rounded-md bg-accent/50 px-2 py-1">
                          <span className="truncate">
                            {c.document} › {c.section}
                          </span>
                          {c.retrieval_score !== undefined ? <span className="money shrink-0">{c.retrieval_score.toFixed(2)}</span> : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {t.error ? <p className="mt-1 text-destructive">{t.error}</p> : null}
                </div>
              </li>
            ))
          ) : (
            <li className="text-xs text-muted-foreground">No tools called for this answer.</li>
          )}
        </ol>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span className="font-mono">{m.model}</span>
          {m.trace_url ? (
            <a href={m.trace_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
              Open Langfuse trace <ExternalLink className="size-3" />
            </a>
          ) : null}
        </div>
      </motion.div>
    </AnimatePresence>
  )
}

export default function CopilotPage() {
  const { messages, clear } = useChat()
  return (
    <>
      <PageHeader
        eyebrow="Revenue AI"
        title="Ask your pipeline anything"
        description="The model answers only by calling read-only tools, the same contracts the MCP server exposes. Click an answer to inspect its tool trace."
        actions={
          messages.length ? (
            <Button variant="outline" size="sm" onClick={clear}>
              <Trash2 /> New conversation
            </Button>
          ) : null
        }
      />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
        <div className="surface flex h-[calc(100dvh-16rem)] min-h-[520px] flex-col p-4 lg:col-span-8">
          <div className="min-h-0 flex-1 overflow-y-auto px-1">
            <ChatMessages />
          </div>
          <Composer compact={false} />
        </div>
        <aside className="surface h-[calc(100dvh-16rem)] min-h-[520px] overflow-y-auto lg:col-span-4">
          <TracePanel />
        </aside>
      </div>
    </>
  )
}
