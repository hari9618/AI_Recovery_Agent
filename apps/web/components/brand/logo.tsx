import { cn } from "@/lib/utils"

/** Brand mark: an ink tile with a copper line that dips and rebounds — revenue caught on the way down. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden className={cn("size-8", className)}>
      <rect width="32" height="32" rx="9" className="fill-ink dark:fill-[#e6edf3]" />
      <path
        d="M6.5 11l6 8 4.5-4.5 8.5-8.5"
        className="stroke-copper"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M19.5 6h6v6" className="stroke-copper" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function Wordmark({ className, tone = "default" }: { className?: string; tone?: "default" | "inverse" }) {
  return (
    <span
      className={cn(
        "font-display text-[1.12rem] leading-none tracking-tight",
        tone === "inverse" ? "text-panel-foreground" : "text-foreground",
        className,
      )}
    >
      <span className="font-medium">Revenue</span> <span className="font-bold">Recovery</span>
    </span>
  )
}
