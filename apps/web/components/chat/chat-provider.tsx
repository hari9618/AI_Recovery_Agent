"use client"

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"

import { apiSend, errorMessage } from "@/lib/api"

export interface ToolCall {
  step: number
  tool: string
  arguments?: Record<string, unknown>
  ok: boolean
  error?: string | null
  latency_ms?: number
  citations?: { document: string; section: string; retrieval_score?: number }[]
}

export interface CopilotAnswer {
  question: string
  answer: string
  model: string
  tool_calls: ToolCall[]
  usage: { input_tokens: number; output_tokens: number; estimated_cost_usd: number }
  latency_ms: number
  trace_id: string | null
  trace_url: string | null
}

export type ChatMessage =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; content: string; meta: CopilotAnswer }
  | { id: string; role: "error"; content: string; question: string }

interface ChatState {
  open: boolean
  setOpen: (open: boolean) => void
  toggle: () => void
  messages: ChatMessage[]
  pending: boolean
  pendingSince: number | null
  send: (question: string) => void
  retry: (question: string) => void
  clear: () => void
  selectedId: string | null
  select: (id: string | null) => void
}

const ChatContext = createContext<ChatState | null>(null)

// Only the visible text of recent turns is sent back; the API bounds it again server-side.
const HISTORY_TURNS = 8

let counter = 0
const nextId = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`

/**
 * One conversation shared by the floating chat and the full Copilot page, kept in memory for the
 * session so it survives navigation between pages.
 */
export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pendingSince, setPendingSince] = useState<number | null>(null)
  const [selectedId, select] = useState<string | null>(null)
  const messagesRef = useRef(messages)
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const ask = useCallback(async (question: string, history: ChatMessage[]) => {
    setPendingSince(Date.now())
    const turns = history
      .filter((m) => m.role === "user" || m.role === "assistant")
      .slice(-HISTORY_TURNS)
      .map((m) => ({ role: m.role, content: m.content }))
    try {
      const answer = await apiSend<CopilotAnswer>("POST", "/copilot/ask", { question, history: turns })
      const id = nextId()
      setMessages((prev) => [...prev, { id, role: "assistant", content: answer.answer, meta: answer }])
      select(id)
    } catch (error) {
      setMessages((prev) => [...prev, { id: nextId(), role: "error", content: errorMessage(error), question }])
    } finally {
      setPendingSince(null)
    }
  }, [])

  const send = useCallback(
    (raw: string) => {
      const question = raw.trim()
      if (question.length < 3 || pendingSince !== null) return
      const history = messagesRef.current
      setMessages((prev) => [...prev, { id: nextId(), role: "user", content: question }])
      void ask(question, history)
    },
    [ask, pendingSince],
  )

  const retry = useCallback(
    (question: string) => {
      if (pendingSince !== null) return
      // Drop the failed error bubble, keep the user's question, ask again.
      const kept = messagesRef.current.filter((m) => !(m.role === "error" && m.question === question))
      setMessages(kept)
      const history = kept.slice(0, -1)
      void ask(question, history)
    },
    [ask, pendingSince],
  )

  const clear = useCallback(() => {
    setMessages([])
    select(null)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const value = useMemo<ChatState>(
    () => ({
      open,
      setOpen,
      toggle: () => setOpen((o) => !o),
      messages,
      pending: pendingSince !== null,
      pendingSince,
      send,
      retry,
      clear,
      selectedId,
      select,
    }),
    [open, messages, pendingSince, send, retry, clear, selectedId],
  )
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

export function useChat(): ChatState {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error("useChat must be used inside <ChatProvider>")
  return ctx
}

export const TOOL_LABEL: Record<string, string> = {
  get_at_risk_opportunities: "Scanned at-risk deals",
  get_customer_intelligence: "Read customer profile",
  get_recovery_report: "Pulled recovery report",
  get_sales_policy: "Checked policy limits",
  search_knowledge_base: "Searched policy documents",
}
