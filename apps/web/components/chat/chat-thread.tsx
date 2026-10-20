"use client"

import {
  ArrowUp,
  BadgeIndianRupee,
  BookOpenCheck,
  ExternalLink,
  RotateCcw,
  ShieldCheck,
  TriangleAlert,
  Users,
  Wrench,
} from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { useEffect, useRef, useState } from "react"

import { Markdown } from "@/components/chat/markdown"
import { TOOL_LABEL, useChat, type ChatMessage } from "@/components/chat/chat-provider"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatMs } from "@/lib/format"
import { cn } from "@/lib/utils"

const SUGGESTIONS = [
  { icon: TriangleAlert, text: "Which deals are critical right now, and why?" },
  { icon: Users, text: "Which sales rep has the most revenue at risk?" },
  { icon: BadgeIndianRupee, text: "What's happening with Vertex Industrial Solutions?" },
  { icon: BookOpenCheck, text: "What discount can a sales rep give without approval?" },
]

/** Animated gradient orb used as the assistant's avatar. */
export function AiOrb({ className, spinning = false }: { className?: string; spinning?: boolean }) {
  return (
    <span className={cn("relative inline-flex size-7 shrink-0 items-center justify-center", className)}>
      <span
        className={cn(
          "absolute inset-0 rounded-full bg-[conic-gradient(from_0deg,#c8734a,#5ea1d9,#3ecf8e,#e29a78,#c8734a)] opacity-90 blur-[1px]",
          spinning ? "animate-spin [animation-duration:2.2s]" : "",
        )}
      />
      <span className="absolute inset-[3px] rounded-full bg-panel" />
      <span className="relative size-2 rounded-full bg-[#ffb48f] shadow-[0_0_10px_#e0875c]" />
    </span>
  )
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 100)
    return () => clearInterval(t)
  }, [])
  return <span className="money">{((now - since) / 1000).toFixed(1)}s</span>
}

function ToolChips({ message }: { message: Extract<ChatMessage, { role: "assistant" }> }) {
  const calls = message.meta.tool_calls
  if (!calls.length) return null
  return (
    <div className="mt-2.5 flex flex-wrap gap-1.5">
      {calls.map((t, i) => (
        <Tooltip key={i}>
          <TooltipTrigger asChild>
            <span
              className={cn(
                "inline-flex cursor-help items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
                t.ok ? "border-primary/25 bg-accent text-accent-foreground" : "border-destructive/30 bg-destructive/10 text-destructive",
              )}
            >
              <Wrench className="size-3" />
              {TOOL_LABEL[t.tool] ?? t.tool}
              {t.latency_ms !== undefined ? <span className="money opacity-70">· {formatMs(t.latency_ms)}</span> : null}
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            <p className="font-mono text-[11px]">{t.tool}</p>
            <pre className="mt-1 text-[10px] whitespace-pre-wrap opacity-80">{JSON.stringify(t.arguments ?? {}, null, 1)}</pre>
            {t.citations?.length ? (
              <p className="mt-1 text-[11px]">Sources: {t.citations.map((c) => `${c.document} › ${c.section}`).join("; ")}</p>
            ) : null}
            {t.error ? <p className="mt-1 text-[11px]">{t.error}</p> : null}
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  )
}

function Bubble({ message, compact }: { message: ChatMessage; compact: boolean }) {
  const { retry, pending, selectedId, select } = useChat()
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-sm text-primary-foreground shadow-sm">
          {message.content}
        </div>
      </div>
    )
  }
  if (message.role === "error") {
    return (
      <div className="flex gap-2.5">
        <AiOrb />
        <div className="max-w-[90%] rounded-2xl rounded-tl-md border border-destructive/30 bg-destructive/8 px-3.5 py-2.5 text-sm">
          <p className="font-medium text-destructive">I couldn&apos;t answer that.</p>
          <p className="mt-0.5 text-muted-foreground">{message.content}</p>
          <button
            type="button"
            disabled={pending}
            onClick={() => retry(message.question)}
            className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline disabled:opacity-50"
          >
            <RotateCcw className="size-3" /> Try again
          </button>
        </div>
      </div>
    )
  }
  const m = message.meta
  return (
    <div className="flex gap-2.5">
      <AiOrb />
      <div className="min-w-0 flex-1">
        <motion.div
          initial={{ opacity: 0, filter: "blur(4px)" }}
          animate={{ opacity: 1, filter: "blur(0px)" }}
          transition={{ duration: 0.5 }}
          onClick={() => !compact && select(message.id)}
          className={cn(
            "rounded-2xl rounded-tl-md border bg-card px-3.5 py-2.5 shadow-[var(--shadow-soft)]",
            !compact && "cursor-pointer transition-colors hover:border-primary/30",
            !compact && selectedId === message.id && "border-primary/40 ring-2 ring-primary/10",
          )}
        >
          <Markdown>{message.content}</Markdown>
          <ToolChips message={message} />
        </motion.div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 px-1 text-[11px] text-muted-foreground">
          <span>{m.model}</span>
          <span>·</span>
          <span className="money">{formatMs(m.latency_ms)}</span>
          <span>·</span>
          <span className="money">{(m.usage.input_tokens + m.usage.output_tokens).toLocaleString("en-IN")} tok</span>
          {m.trace_url ? (
            <a href={m.trace_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">
              trace <ExternalLink className="size-3" />
            </a>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function Thinking({ since }: { since: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-2.5">
      <AiOrb spinning />
      <div className="rounded-2xl rounded-tl-md border bg-card px-3.5 py-2.5 text-sm shadow-[var(--shadow-soft)]">
        <div className="flex items-center gap-2 text-muted-foreground">
          <span className="flex gap-1">
            {[0, 1, 2].map((i) => (
              <motion.span
                key={i}
                className="size-1.5 rounded-full bg-primary"
                animate={{ opacity: [0.25, 1, 0.25], y: [0, -3, 0] }}
                transition={{ duration: 1, repeat: Infinity, delay: i * 0.15 }}
              />
            ))}
          </span>
          Calling read-only tools · <Elapsed since={since} />
        </div>
      </div>
    </motion.div>
  )
}

function EmptyChat({ compact }: { compact: boolean }) {
  const { send, pending } = useChat()
  return (
    <div className={cn("flex flex-col items-center text-center", compact ? "px-2 pt-6" : "px-4 pt-14")}>
      <motion.div initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 180, damping: 16 }}>
        <AiOrb className="size-14" spinning />
      </motion.div>
      <h3 className={cn("font-display mt-4 font-semibold", compact ? "text-xl" : "text-3xl")}>
        Ask about your <span className="text-primary">pipeline</span>
      </h3>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">
        Answers come only from read-only tools over your CRM and policy documents. Every tool call is shown.
      </p>
      <div className={cn("mt-6 grid w-full gap-2", compact ? "grid-cols-1" : "max-w-2xl sm:grid-cols-2")}>
        {SUGGESTIONS.map((s, i) => (
          <motion.button
            key={s.text}
            type="button"
            disabled={pending}
            onClick={() => send(s.text)}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 + i * 0.06 }}
            className="lift group flex items-center gap-3 rounded-xl border bg-card px-3 py-2.5 text-left text-sm"
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <s.icon className="size-4" />
            </span>
            <span className="text-foreground/90">{s.text}</span>
          </motion.button>
        ))}
      </div>
    </div>
  )
}

export function Composer({ compact }: { compact: boolean }) {
  const { send, pending } = useChat()
  const [value, setValue] = useState("")
  const ref = useRef<HTMLTextAreaElement>(null)
  const submit = () => {
    if (value.trim().length < 3 || pending) return
    send(value)
    setValue("")
  }
  useEffect(() => {
    ref.current?.focus()
  }, [])
  return (
    <div className={cn(compact ? "p-3" : "px-1 pt-3")}>
      <div className="flex items-end gap-2 rounded-2xl border bg-card p-1.5 pl-3.5 shadow-[var(--shadow-soft)] transition focus-within:border-primary/40 focus-within:ring-4 focus-within:ring-primary/10">
        <textarea
          ref={ref}
          rows={1}
          value={value}
          maxLength={2000}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder="Ask about deals, customers or policy…"
          className="field-sizing-content max-h-36 min-h-9 flex-1 resize-none bg-transparent py-2 text-sm outline-none placeholder:text-muted-foreground"
        />
        <motion.button
          type="button"
          whileTap={{ scale: 0.92 }}
          onClick={submit}
          disabled={pending || value.trim().length < 3}
          aria-label="Send"
          className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground transition disabled:opacity-40"
        >
          <ArrowUp className="size-4" />
        </motion.button>
      </div>
      <p className="mt-1.5 flex items-center justify-center gap-1 text-[11px] text-muted-foreground">
        <ShieldCheck className="size-3" /> Read-only: the assistant can&apos;t send emails or change deals.
      </p>
    </div>
  )
}

export function ChatMessages({ compact = false }: { compact?: boolean }) {
  const { messages, pending, pendingSince } = useChat()
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages.length, pending])
  if (!messages.length && !pending) return <EmptyChat compact={compact} />
  return (
    <div className={cn("space-y-4", compact ? "px-3 py-4" : "py-4")}>
      <AnimatePresence initial={false}>
        {messages.map((m) => (
          <motion.div key={m.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
            <Bubble message={m} compact={compact} />
          </motion.div>
        ))}
      </AnimatePresence>
      {pending && pendingSince ? <Thinking since={pendingSince} /> : null}
      <div ref={end} />
    </div>
  )
}
