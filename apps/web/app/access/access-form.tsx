"use client"

import { ArrowRight, Loader2, LockKeyhole } from "lucide-react"
import { motion } from "motion/react"
import { useSearchParams } from "next/navigation"
import { useState } from "react"

import { LogoMark, Wordmark } from "@/components/brand/logo"
import { Button } from "@/components/ui/button"
import { safeNext } from "@/lib/safe-next"

export function AccessForm({ contactUrl }: { contactUrl: string | null }) {
  const params = useSearchParams()
  const [code, setCode] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!code.trim() || pending) return
    setPending(true)
    setError(null)
    const res = await fetch("/api/access", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code }),
    }).catch(() => null)
    if (res && res.ok) {
      window.location.assign(safeNext(params.get("next")))
      return
    }
    setPending(false)
    setError(res?.status === 401 ? "That access code isn't right." : "Couldn't check the code. Try again.")
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}
      className="w-full max-w-md"
    >
      <div className="mb-8 flex items-center justify-center gap-2.5">
        <LogoMark className="size-8" />
        <Wordmark />
      </div>
      <form onSubmit={submit} className="surface p-7 md:p-8">
        <span className="flex size-11 items-center justify-center rounded-xl bg-copper-soft text-copper">
          <LockKeyhole className="size-5" />
        </span>
        <h1 className="font-display mt-5 text-3xl font-bold tracking-[-0.03em]">Private demo</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          This is a working demo of an AI revenue recovery agent. Enter the access code you were given.
        </p>
        <label htmlFor="code" className="mt-6 block text-sm font-medium">
          Access code
        </label>
        <input
          id="code"
          type="password"
          autoComplete="off"
          autoFocus
          value={code}
          onChange={(e) => setCode(e.target.value)}
          className="mt-2 h-11 w-full rounded-xl border bg-background px-3.5 text-sm outline-none transition focus:border-copper/50 focus:ring-4 focus:ring-copper/10"
          aria-invalid={Boolean(error)}
        />
        {error ? <p className="mt-2 text-sm text-destructive">{error}</p> : null}
        <Button type="submit" size="lg" className="mt-5 w-full rounded-xl" disabled={pending || !code.trim()}>
          {pending ? <Loader2 className="animate-spin" /> : null} Enter demo {pending ? null : <ArrowRight />}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        No code?{" "}
        {contactUrl ? (
          <a href={contactUrl} target="_blank" rel="noreferrer" className="font-medium text-copper hover:underline">
            Get in touch for access
          </a>
        ) : (
          "Ask the author for access."
        )}
      </p>
    </motion.div>
  )
}
