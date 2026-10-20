"use client"

import { Maximize2, Sparkles, Trash2, X } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect } from "react"

import { useChat } from "@/components/chat/chat-provider"
import { AiOrb, ChatMessages, Composer } from "@/components/chat/chat-thread"
import { LiveDot } from "@/components/motion/primitives"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

/** Floating "Ask AI" launcher plus the slide-up chat panel, available on every app page. */
export function ChatWidget() {
  const { open, setOpen, toggle, messages, clear, pending } = useChat()
  const pathname = usePathname()
  const onCopilotPage = pathname.startsWith("/copilot")

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false)
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, setOpen])

  if (onCopilotPage) return null

  return (
    <>
      <AnimatePresence>
        {!open ? (
          <motion.button
            key="launcher"
            type="button"
            onClick={toggle}
            initial={{ opacity: 0, y: 16, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.9 }}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.96 }}
            transition={{ type: "spring", stiffness: 260, damping: 22 }}
            className="fixed right-5 bottom-5 z-50 flex items-center gap-2.5 rounded-full bg-panel py-2 pr-4 pl-2 text-sm font-medium text-panel-foreground shadow-[0_18px_40px_-12px_#0d111799] ring-1 ring-panel-border"
            aria-label="Ask Revenue AI"
          >
            <span className="rounded-full animate-pulse-ring">
              <AiOrb className="size-8" spinning={pending} />
            </span>
            <span>Ask Revenue AI</span>
            <kbd className="hidden rounded-md border border-panel-border px-1.5 py-0.5 font-mono text-[10px] text-panel-muted sm:inline">
              Ctrl J
            </kbd>
          </motion.button>
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {open ? (
          <motion.section
            key="panel"
            role="dialog"
            aria-label="Revenue AI chat"
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ type: "spring", stiffness: 280, damping: 28 }}
            style={{ transformOrigin: "bottom right" }}
            className="fixed inset-x-2 top-16 bottom-2 z-50 flex flex-col overflow-hidden rounded-3xl border bg-background shadow-[0_40px_80px_-24px_#0d111773] sm:inset-x-auto sm:top-auto sm:right-5 sm:bottom-5 sm:h-[min(700px,calc(100dvh-2.5rem))] sm:w-[440px]"
          >
            <header className="panel-dark flex items-center gap-3 rounded-none border-0 border-b px-4 py-3">
              <AiOrb className="size-9" spinning={pending} />
              <div className="min-w-0 flex-1">
                <p className="font-display text-base leading-tight font-semibold">Revenue AI</p>
                <p className="flex items-center gap-1.5 text-[11px] text-panel-muted">
                  <LiveDot className="text-panel-money" /> Grounded in your CRM · read-only tools
                </p>
              </div>
              {messages.length ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" onClick={clear} className="rounded-lg p-1.5 text-panel-muted transition hover:bg-white/10 hover:text-panel-foreground" aria-label="Clear conversation">
                      <Trash2 className="size-4" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>New conversation</TooltipContent>
                </Tooltip>
              ) : null}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Link href="/copilot" onClick={() => setOpen(false)} className="rounded-lg p-1.5 text-panel-muted transition hover:bg-white/10 hover:text-panel-foreground" aria-label="Open full screen">
                    <Maximize2 className="size-4" />
                  </Link>
                </TooltipTrigger>
                <TooltipContent>Open full screen with tool trace</TooltipContent>
              </Tooltip>
              <button type="button" onClick={() => setOpen(false)} className="rounded-lg p-1.5 text-panel-muted transition hover:bg-white/10 hover:text-panel-foreground" aria-label="Close chat">
                <X className="size-4" />
              </button>
            </header>
            <div className="bg-dots min-h-0 flex-1 overflow-y-auto">
              <ChatMessages compact />
            </div>
            <div className="border-t bg-background">
              <Composer compact />
            </div>
          </motion.section>
        ) : null}
      </AnimatePresence>
    </>
  )
}

/** Header button that opens the chat. */
export function AskAiButton() {
  const { setOpen } = useChat()
  return (
    <button
      type="button"
      onClick={() => setOpen(true)}
      className="group hidden h-9 w-56 max-w-full items-center gap-2 rounded-xl border bg-card px-3 text-sm text-muted-foreground shadow-[var(--shadow-soft)] transition hover:border-primary/30 hover:text-foreground md:flex xl:w-72"
    >
      <Sparkles className="size-4 text-primary transition group-hover:rotate-12" />
      <span className="flex-1 truncate text-left">Ask Revenue AI anything…</span>
      <kbd className="rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[10px]">Ctrl J</kbd>
    </button>
  )
}
