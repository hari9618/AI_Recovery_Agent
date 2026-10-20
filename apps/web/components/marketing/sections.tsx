"use client"

import { Activity, ArrowRight, BookOpenCheck, ClipboardCheck, Gauge, MessageSquareText, ScanSearch, ShieldCheck, Sparkles } from "lucide-react"
import Link from "next/link"

import { LogoMark, Wordmark } from "@/components/brand/logo"
import { CountUp, Reveal, Stagger, StaggerItem } from "@/components/motion/primitives"
import { Button } from "@/components/ui/button"

/* ── Measured numbers ───────────────────────────────────────────────────────── */
const STATS = [
  { value: 160, format: (n: number) => `${Math.round(n)}`, label: "automated tests passing" },
  { value: 42, format: (n: number) => `${Math.round(n)}/42`, label: "agent scenarios passed offline" },
  { value: 0.967, format: (n: number) => n.toFixed(3), label: "retrieval MRR on policy questions" },
  { value: 0.0018, format: (n: number) => `$${n.toFixed(4)}`, label: "LLM cost of one live agent run" },
]

export function Stats() {
  return (
    <section className="border-y bg-card/60 py-12">
      <div className="mx-auto grid max-w-6xl grid-cols-2 gap-y-8 px-5 md:grid-cols-4">
        {STATS.map((s, i) => (
          <Reveal key={s.label} delay={i * 0.06} className="px-4 text-center md:border-l md:first:border-l-0">
            <CountUp value={s.value} format={s.format} duration={1.6} className="font-display block text-4xl font-bold md:text-5xl" />
            <p className="mt-2 text-sm text-muted-foreground">{s.label}</p>
          </Reveal>
        ))}
      </div>
      <p className="mt-8 text-center text-xs text-muted-foreground">Measured in this repository. Offline evaluations use a scripted LLM and test orchestration, not model quality.</p>
    </section>
  )
}

/* ── Workflow ───────────────────────────────────────────────────────────────── */
const STEPS = [
  {
    icon: Gauge,
    title: "Score",
    body: "Every open deal gets a 0–100 risk score from explained reason codes: days waiting, unanswered quotes, competitor mentions.",
    detail: "deterministic · ~100 ms",
  },
  {
    icon: ScanSearch,
    title: "Investigate",
    body: "The agent reads the conversation for intent and objections, then pulls the exact policy passages that apply.",
    detail: "LLM + hybrid search",
  },
  {
    icon: Sparkles,
    title: "Recommend",
    body: "One next step with a drafted email. Every policy claim must cite a passage, or it is flagged.",
    detail: "claims verified",
  },
  {
    icon: ClipboardCheck,
    title: "Approve",
    body: "Customer-facing actions wait for a person. Approve, edit or reject, and the outcome is tracked to revenue.",
    detail: "human in the loop",
  },
]

export function Workflow() {
  return (
    <section id="workflow" className="scroll-mt-24 py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-5">
        <Reveal className="max-w-2xl">
          <p className="eyebrow">Workflow</p>
          <h2 className="font-display mt-4 text-4xl leading-[1.05] font-bold tracking-[-0.035em] md:text-[3.25rem]">
            From silent deal to <span className="text-copper">next step</span> in four moves
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">One LangGraph workflow with explicit steps, so every run is predictable, traceable and testable.</p>
        </Reveal>
        <Stagger className="relative mt-14 grid grid-cols-1 gap-4 md:grid-cols-4">
          <div className="pointer-events-none absolute top-10 right-[12%] left-[12%] hidden h-px bg-gradient-to-r from-transparent via-copper/40 to-transparent md:block" />
          {STEPS.map((s, i) => (
            <StaggerItem key={s.title} className="surface lift relative p-6">
              <div className="flex items-center justify-between">
                <span className="relative flex size-11 items-center justify-center rounded-xl bg-foreground text-background">
                  <s.icon className="size-5" />
                </span>
                <span className="font-mono text-xs text-muted-foreground">0{i + 1}</span>
              </div>
              <h3 className="font-display mt-6 text-2xl font-bold">{s.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{s.body}</p>
              <p className="mt-5 inline-flex rounded-md bg-copper-soft px-2 py-0.5 font-mono text-[11px] text-bronze">{s.detail}</p>
            </StaggerItem>
          ))}
        </Stagger>
      </div>
    </section>
  )
}

/* ── Trust ──────────────────────────────────────────────────────────────────── */
const TRUST = [
  { icon: BookOpenCheck, title: "Cited, or not said", body: "Policy answers come from retrieved passages, checked by a cross-encoder. No evidence means “insufficient evidence”." },
  { icon: ShieldCheck, title: "Approval enforced twice", body: "The policy engine routes it, and the email and discount tools refuse to run without an approved request in the database." },
  { icon: MessageSquareText, title: "Injection-resistant", body: "Untrusted text is fenced and scanned. Flagged documents are retrieved but never reach the model." },
  { icon: Activity, title: "Every step traced", body: "Langfuse traces for each node, tool call and token, plus cost per run and an append-only audit log." },
]

export function Trust() {
  return (
    <section id="trust" className="scroll-mt-24 bg-secondary/50 py-24 md:py-32">
      <div className="mx-auto grid max-w-6xl grid-cols-1 gap-12 px-5 lg:grid-cols-12 lg:items-start">
        <Reveal className="lg:sticky lg:top-28 lg:col-span-5">
          <p className="eyebrow">Trust</p>
          <h2 className="font-display mt-4 text-4xl leading-[1.05] font-bold tracking-[-0.035em] md:text-[3.25rem]">
            AI you can <span className="mark">audit</span>, not just trust
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Numbers come from the database and the risk engine. The model handles language, and every answer shows where it came
            from.
          </p>
          <Button asChild variant="outline" className="mt-8 rounded-full px-5">
            <Link href="/evaluations">
              See the evaluations <ArrowRight />
            </Link>
          </Button>
        </Reveal>
        <Stagger className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:col-span-7">
          {TRUST.map((t) => (
            <StaggerItem key={t.title} className="surface lift p-6">
              <span className="flex size-10 items-center justify-center rounded-xl bg-copper-soft text-copper">
                <t.icon className="size-5" />
              </span>
              <h3 className="font-display mt-5 text-xl font-bold">{t.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t.body}</p>
            </StaggerItem>
          ))}
        </Stagger>
      </div>
    </section>
  )
}

/* ── CTA + footer ───────────────────────────────────────────────────────────── */
export function FinalCta() {
  return (
    <section className="px-4 py-24">
      <Reveal className="panel-dark relative mx-auto max-w-6xl overflow-hidden rounded-[2rem] px-6 py-16 text-center md:px-16 md:py-20">
        <h2 className="font-display mx-auto max-w-3xl text-4xl leading-[1.05] font-bold tracking-[-0.04em] md:text-6xl">
          See what your pipeline is <span className="text-[#ffb48f]">hiding.</span>
        </h2>
        <p className="mx-auto mt-5 max-w-xl text-panel-muted">
          Open the demo pipeline, run the agent on a critical deal and approve its first recovery action in under a minute.
        </p>
        <div className="mt-9 flex flex-wrap justify-center gap-3">
          <Button asChild size="lg" className="rounded-full px-6">
            <Link href="/dashboard">
              Open the dashboard <ArrowRight />
            </Link>
          </Button>
          <Link
            href="/copilot"
            className="inline-flex h-11 items-center gap-2 rounded-full border border-panel-border px-6 text-[15px] font-medium text-panel-foreground transition hover:bg-white/5"
          >
            <Sparkles className="size-4 text-[#ffb48f]" /> Ask Revenue AI
          </Link>
        </div>
      </Reveal>
    </section>
  )
}

export function Footer() {
  return (
    <footer className="border-t py-10">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-5 text-sm text-muted-foreground md:flex-row">
        <div className="flex items-center gap-2.5">
          <LogoMark className="size-6" />
          <Wordmark className="text-base" />
        </div>
        <p className="text-center text-xs">Portfolio project · synthetic demo data · FastAPI, LangGraph, Groq, PostgreSQL + pgvector, Next.js</p>
        <div className="flex gap-4 text-xs">
          <Link href="/dashboard" className="hover:text-foreground">
            Dashboard
          </Link>
          <Link href="/evaluations" className="hover:text-foreground">
            Evaluations
          </Link>
          <Link href="/observability" className="hover:text-foreground">
            Observability
          </Link>
        </div>
      </div>
    </footer>
  )
}
