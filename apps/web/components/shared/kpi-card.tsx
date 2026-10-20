"use client"

import { motion } from "motion/react"

import { cn } from "@/lib/utils"

const TONE = {
  default: { chip: "bg-muted text-muted-foreground", value: "text-foreground" },
  critical: { chip: "bg-risk-critical/10 text-risk-critical", value: "text-foreground" },
  success: { chip: "bg-money/10 text-money", value: "text-money" },
  warning: { chip: "bg-amber/12 text-amber", value: "text-foreground" },
  primary: { chip: "bg-copper-soft text-copper", value: "text-foreground" },
  teal: { chip: "bg-blue/10 text-blue", value: "text-foreground" },
} as const

export function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
  footer,
  index = 0,
}: {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  icon?: React.ComponentType<{ className?: string }>
  tone?: keyof typeof TONE
  footer?: React.ReactNode
  index?: number
}) {
  const t = TONE[tone]
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.55, delay: 0.05 * index, ease: [0.2, 0.8, 0.2, 1] }}
      className="surface lift flex flex-col p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-muted-foreground">{label}</p>
        {Icon ? (
          <div className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg", t.chip)}>
            <Icon className="size-4" />
          </div>
        ) : null}
      </div>
      <div className={cn("font-display mt-3 text-[1.9rem] leading-none font-bold tabular-nums", t.value)}>{value}</div>
      {hint ? <div className="mt-2 text-xs leading-relaxed text-muted-foreground">{hint}</div> : null}
      {footer ? <div className="mt-auto pt-3">{footer}</div> : null}
    </motion.div>
  )
}
