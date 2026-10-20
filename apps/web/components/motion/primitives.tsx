"use client"

import { animate, motion, useInView, useMotionValue, useReducedMotion, type HTMLMotionProps } from "motion/react"
import { useEffect, useRef, useState, useSyncExternalStore } from "react"

import { cn } from "@/lib/utils"

const EASE = [0.2, 0.8, 0.2, 1] as const

/** Fades and lifts its children into place the first time they scroll into view. */
export function Reveal({
  delay = 0,
  y = 14,
  className,
  children,
  ...props
}: HTMLMotionProps<"div"> & { delay?: number; y?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ duration: 0.6, delay, ease: EASE }}
      className={className}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/** Container that staggers its <StaggerItem> children. */
export function Stagger({ className, children, gap = 0.06, ...props }: HTMLMotionProps<"div"> & { gap?: number }) {
  return (
    <motion.div
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: "-40px" }}
      variants={{ hidden: {}, show: { transition: { staggerChildren: gap } } }}
      className={className}
      {...props}
    >
      {children}
    </motion.div>
  )
}

export function StaggerItem({ className, children, ...props }: HTMLMotionProps<"div">) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 14 },
        show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: EASE } },
      }}
      className={className}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/** Animates a number from 0 (or its previous value) to `value`, formatting every frame. */
export function CountUp({
  value,
  format = (n) => Math.round(n).toLocaleString("en-IN"),
  duration = 1.4,
  className,
}: {
  value: number
  format?: (n: number) => string
  duration?: number
  className?: string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true })
  const reduce = useReducedMotion()
  const mv = useMotionValue(0)
  const [text, setText] = useState(() => format(0))

  useEffect(() => mv.on("change", (v) => setText(format(v))), [mv, format])
  useEffect(() => {
    if (!inView) return
    if (reduce) {
      mv.jump(value)
      return
    }
    const controls = animate(mv, value, { duration, ease: EASE })
    return () => controls.stop()
  }, [inView, value, duration, mv, reduce])

  return (
    <span ref={ref} className={cn("tabular", className)}>
      {text}
    </span>
  )
}

/** Animated horizontal fill (0 → pct%). */
export function GrowBar({
  pct,
  className,
  barClassName,
  delay = 0,
  style,
}: {
  pct: number
  className?: string
  barClassName?: string
  delay?: number
  style?: React.CSSProperties
}) {
  return (
    <div className={cn("h-2 overflow-hidden rounded-full bg-muted", className)}>
      <motion.div
        className={cn("h-full rounded-full", barClassName)}
        style={style}
        initial={{ width: 0 }}
        whileInView={{ width: `${Math.max(0, Math.min(pct, 100))}%` }}
        viewport={{ once: true }}
        transition={{ duration: 1, delay, ease: EASE }}
      />
    </div>
  )
}

/** Small live indicator: solid dot with an expanding ring. */
export function LiveDot({ className }: { className?: string }) {
  return (
    <span className={cn("relative inline-flex size-2", className)}>
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-50" />
      <span className="relative inline-flex size-2 rounded-full bg-current" />
    </span>
  )
}

const noopSubscribe = () => () => {}
const todayLabel = () => new Date().toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })

/** Today's date, rendered on the client only (prerendered HTML has no clock). */
export function Today({ className }: { className?: string }) {
  const label = useSyncExternalStore(noopSubscribe, todayLabel, () => "")
  return <span className={cn("inline-block min-w-[5.5rem] text-center", className)}>{label}</span>
}
