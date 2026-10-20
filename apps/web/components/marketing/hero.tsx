"use client"

import { useQuery } from "@tanstack/react-query"
import { ArrowRight, Check, CheckCircle2, Loader2, MessageSquareText, Moon, Sun } from "lucide-react"
import { motion, useScroll, useTransform } from "motion/react"
import { useTheme } from "next-themes"
import Link from "next/link"
import { useEffect, useRef, useState } from "react"

import { LogoMark, Wordmark } from "@/components/brand/logo"
import { CountUp, LiveDot } from "@/components/motion/primitives"
import { RiskMeter } from "@/components/risk/risk"
import { ActivityFeed } from "@/components/shared/activity-feed"
import { Button } from "@/components/ui/button"
import { apiGet } from "@/lib/api"
import { formatMoneyCompact, formatMs, titleCase } from "@/lib/format"
import type { DashboardSummary } from "@/lib/types"
import { cn } from "@/lib/utils"

const NAV = [
  { href: "#product", label: "Product" },
  { href: "#workflow", label: "Workflow" },
  { href: "#trust", label: "Trust" },
]

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  return (
    <button
      type="button"
      aria-label="Toggle theme"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      className="hidden size-9 items-center justify-center rounded-full text-muted-foreground transition hover:bg-muted hover:text-foreground sm:flex"
    >
      <Sun className="hidden size-4 dark:block" />
      <Moon className="size-4 dark:hidden" />
    </button>
  )
}

export function MarketingNav() {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12)
    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])
  return (
    <header className="fixed inset-x-0 top-0 z-50 px-3 pt-3">
      <div
        className={cn(
          "mx-auto flex h-14 max-w-6xl items-center gap-4 rounded-2xl px-4 transition-all duration-300",
          scrolled ? "glass border shadow-[var(--shadow-soft)]" : "border border-transparent",
        )}
      >
        <Link href="/" className="flex min-w-0 items-center gap-2.5">
          <LogoMark className="size-7 shrink-0" />
          <Wordmark className="text-base" />
        </Link>
        <nav className="ml-6 hidden items-center gap-1 md:flex">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className="rounded-lg px-3 py-1.5 text-sm text-muted-foreground transition hover:text-foreground">
              {n.label}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-1.5">
          <ThemeToggle />
          <Link href="/copilot" className="hidden rounded-full px-3 py-1.5 text-sm font-medium transition hover:bg-muted sm:block">
            Ask the AI
          </Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-1.5 rounded-full bg-foreground px-4 py-2 text-sm font-semibold text-background transition hover:opacity-90"
          >
            Dashboard <ArrowRight className="size-4" />
          </Link>
        </div>
      </div>
    </header>
  )
}

export function Hero() {
  return (
    <section className="relative overflow-hidden pt-36 pb-10 md:pt-44">
      <div className="bg-grid pointer-events-none absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_70%_60%_at_50%_0%,black,transparent)]" />
      <div className="glow-copper pointer-events-none absolute top-0 left-1/2 -z-10 h-[34rem] w-[60rem] -translate-x-1/2 opacity-80" />
      <div className="mx-auto max-w-5xl px-5 text-center">
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <Link
            href="/copilot"
            className="group inline-flex items-center gap-2 rounded-full border bg-card py-1 pr-3 pl-1 text-sm shadow-[var(--shadow-soft)] transition hover:border-copper/40"
          >
            <span className="rounded-full bg-copper px-2 py-0.5 text-xs font-semibold text-white">New</span>
            Revenue AI chat with live tool traces
            <ArrowRight className="size-3.5 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-copper" />
          </Link>
        </motion.div>
        <motion.h1
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.08, duration: 0.7, ease: [0.2, 0.8, 0.2, 1] }}
          className="font-display mt-8 text-[3.2rem] leading-[0.98] font-extrabold tracking-[-0.045em] sm:text-7xl md:text-[5.6rem]"
        >
          Stop losing deals
          <br />
          to <span className="mark text-copper">silence.</span>
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.18 }}
          className="mx-auto mt-7 max-w-2xl text-lg leading-relaxed text-muted-foreground md:text-xl"
        >
          Revenue Recovery scores every open deal, explains what is going wrong with evidence, and drafts a grounded next
          step. Nothing reaches a customer until you approve it.
        </motion.p>
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.26 }} className="mt-9 flex flex-wrap justify-center gap-3">
          <Button asChild size="lg" className="rounded-full px-6">
            <Link href="/dashboard">
              Open the live dashboard <ArrowRight />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline" className="rounded-full px-6">
            <Link href="/copilot">
              <MessageSquareText className="text-copper" /> Talk to Revenue AI
            </Link>
          </Button>
        </motion.div>
        <motion.ul
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4 }}
          className="mt-8 flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm text-muted-foreground"
        >
          {["Deterministic risk scores", "Every policy claim cited", "You approve every email"].map((t) => (
            <li key={t} className="inline-flex items-center gap-1.5">
              <Check className="size-4 text-money" /> {t}
            </li>
          ))}
        </motion.ul>
      </div>
      <ProductPreview />
    </section>
  )
}

interface RunStep {
  node: string
  status: string
  latency_ms: number | null
}
interface RunListItem {
  id: string
  customer_name: string | null
  status: string
  steps: RunStep[]
}

function LatestRun() {
  const runs = useQuery({
    queryKey: ["landing-latest-run"],
    queryFn: () => apiGet<{ items: RunListItem[] }>("/agent/runs", { limit: 1 }),
    retry: false,
  })
  const run = runs.data?.items[0]
  const steps = run?.steps ?? []
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (!steps.length) return
    const t = setInterval(() => setShown((s) => (s >= steps.length + 3 ? 0 : s + 1)), 650)
    return () => clearInterval(t)
  }, [steps.length])
  if (!run) {
    return <p className="text-xs text-panel-muted">{runs.isLoading ? "Loading…" : "No agent runs yet. Run the agent on a critical deal."}</p>
  }
  return (
    <div>
      <p className="truncate font-mono text-[11px] text-panel-muted">{run.customer_name}</p>
      <ol className="mt-3 space-y-1.5">
        {steps.map((s, i) => (
          <li key={s.node} className={cn("flex items-center gap-2 text-xs transition-opacity duration-300", i < shown ? "opacity-100" : "opacity-35")}>
            <span className={cn("flex size-4 shrink-0 items-center justify-center rounded-full", i < shown ? "bg-panel-money/15 text-panel-money" : "bg-white/5")}>
              {i < shown ? <Check className="size-2.5" /> : i === shown ? <Loader2 className="size-2.5 animate-spin" /> : null}
            </span>
            <span className="truncate">{titleCase(s.node)}</span>
            <span className="ml-auto font-mono text-[10px] text-panel-muted">{formatMs(s.latency_ms)}</span>
          </li>
        ))}
      </ol>
      {run.status === "awaiting_approval" ? (
        <p className="mt-3 flex items-center gap-1.5 rounded-lg bg-[#e0875c1f] px-2.5 py-1.5 text-[11px] text-[#ffb48f]">
          <CheckCircle2 className="size-3.5" /> Waiting for a manager to approve
        </p>
      ) : null}
    </div>
  )
}

/** A straight, full-width window onto the real dashboard data. */
function ProductPreview() {
  const ref = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "start 30%"] })
  const rotateX = useTransform(scrollYProgress, [0, 1], [14, 0])
  const scale = useTransform(scrollYProgress, [0, 1], [0.94, 1])
  const summary = useQuery({ queryKey: ["dashboard"], queryFn: () => apiGet<DashboardSummary>("/dashboard/summary"), retry: false })
  const k = summary.data?.kpis
  const top = summary.data?.top_risks.slice(0, 6) ?? []
  return (
    <div id="product" ref={ref} className="mx-auto mt-16 max-w-6xl scroll-mt-24 px-4 [perspective:1600px] md:mt-20">
      <motion.div style={{ rotateX, scale, transformOrigin: "50% 0%" }} className="rounded-[1.6rem] border bg-card/70 p-2 shadow-[0_50px_100px_-40px_#12121240] backdrop-blur">
        <div className="overflow-hidden rounded-[1.2rem] border bg-background">
          <div className="flex items-center gap-2 border-b bg-muted/50 px-4 py-2.5">
            <span className="size-2.5 rounded-full bg-[#ff5f57]" />
            <span className="size-2.5 rounded-full bg-[#febc2e]" />
            <span className="size-2.5 rounded-full bg-[#28c840]" />
            <span className="mx-auto rounded-md bg-background px-3 py-0.5 font-mono text-[11px] text-muted-foreground">revenue-recovery / overview</span>
            <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-muted-foreground">
              <LiveDot className="text-money" /> live data
            </span>
          </div>
          <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-12">
            <div className="space-y-4 lg:col-span-8">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                {[
                  { label: "At risk", value: k?.revenue_at_risk, money: true, tone: "text-foreground" },
                  { label: "Recovered", value: k?.revenue_recovered, money: true, tone: "text-money" },
                  { label: "Critical deals", value: k?.critical_opportunities, money: false, tone: "text-risk-critical" },
                  { label: "Awaiting approval", value: k?.pending_approvals, money: false, tone: "text-copper" },
                ].map((s) => (
                  <div key={s.label} className="rounded-xl border bg-card p-3.5 text-left">
                    <p className="text-xs text-muted-foreground">{s.label}</p>
                    {s.value !== undefined ? (
                      <CountUp
                        value={s.value}
                        format={s.money ? (n) => formatMoneyCompact(n) : undefined}
                        className={cn("font-display mt-1 block text-2xl font-bold whitespace-nowrap md:text-[1.75rem]", s.tone)}
                      />
                    ) : (
                      <div className="shimmer-skeleton mt-2 h-7 w-20" />
                    )}
                  </div>
                ))}
              </div>
              <div className="rounded-xl border bg-card text-left">
                <div className="flex items-center justify-between border-b px-4 py-2.5">
                  <p className="text-sm font-semibold">Act today</p>
                  <p className="text-xs text-muted-foreground">risk engine · deterministic</p>
                </div>
                {top.length ? (
                  <ul className="divide-y">
                    {top.map((r) => (
                      <li key={r.risk_id} className="grid grid-cols-12 items-center gap-3 px-4 py-2.5">
                        <div className="col-span-7 min-w-0 sm:col-span-5">
                          <p className="truncate text-sm font-medium">{r.customer_name}</p>
                          <p className="truncate text-[11px] text-muted-foreground">{r.reasons[0]?.label}</p>
                        </div>
                        <span className="col-span-5 text-right font-mono text-xs sm:col-span-2 sm:text-left">{formatMoneyCompact(r.revenue_at_risk)}</span>
                        <RiskMeter score={r.risk_score} level={r.risk_level} className="col-span-5 hidden sm:flex" />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="space-y-2 p-4">
                    {[0, 1, 2].map((i) => (
                      <div key={i} className="shimmer-skeleton h-8" />
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="panel-dark rounded-xl p-4 text-left lg:col-span-4">
              <p className="font-display text-sm font-bold">Latest agent run</p>
              <div className="mt-2">
                <LatestRun />
              </div>
              <div className="mt-4 border-t border-panel-border pt-3">
                <p className="text-xs font-semibold">Activity</p>
                {summary.isError ? (
                  <p className="py-2 text-xs text-panel-muted">Start the API to see live activity.</p>
                ) : (
                  <ActivityFeed tone="panel" limit={3} />
                )}
              </div>
            </div>
          </div>
        </div>
      </motion.div>
      <p className="mt-4 text-center text-xs text-muted-foreground">Live from the synthetic demo workspace. No real customer data.</p>
    </div>
  )
}
