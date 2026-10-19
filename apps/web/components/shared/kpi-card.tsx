import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
  footer,
}: {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  icon?: React.ComponentType<{ className?: string }>
  tone?: "default" | "critical" | "success" | "warning" | "primary"
  footer?: React.ReactNode
}) {
  const toneClass = {
    default: "bg-muted text-muted-foreground",
    critical: "bg-risk-critical/12 text-risk-critical",
    success: "bg-success/12 text-success",
    warning: "bg-warning/15 text-warning",
    primary: "bg-primary/10 text-primary",
  }[tone]
  return (
    <Card className="gap-0 py-0 shadow-xs">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3">
          <p className="text-sm text-muted-foreground">{label}</p>
          {Icon ? (
            <div className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg", toneClass)}>
              <Icon className="size-4" />
            </div>
          ) : null}
        </div>
        <div className="mt-2 text-2xl font-semibold tracking-tight tabular">{value}</div>
        {hint ? <div className="mt-1 text-xs text-muted-foreground">{hint}</div> : null}
        {footer ? <div className="mt-3">{footer}</div> : null}
      </CardContent>
    </Card>
  )
}
