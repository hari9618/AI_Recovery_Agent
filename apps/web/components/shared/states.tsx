import { AlertTriangle, Inbox } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError } from "@/lib/api"

export function LoadingBlock({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={className ?? "space-y-3"}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  )
}

export function ErrorState({ error, title = "Couldn't load this data" }: { error: unknown; title?: string }) {
  const payload = error instanceof ApiError ? error.payload : null
  return (
    <Alert variant="destructive">
      <AlertTriangle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{payload?.message ?? (error instanceof Error ? error.message : "Unknown error")}</p>
        {payload?.remediation ? <p className="mt-1 text-xs opacity-90">{payload.remediation}</p> : null}
        {error instanceof ApiError && error.status === 401 ? (
          <p className="mt-1 text-xs opacity-90">No tenant yet? Use “Load demo dataset” in the header.</p>
        ) : null}
      </AlertDescription>
    </Alert>
  )
}

export function EmptyState({
  title,
  description,
  action,
  icon: Icon = Inbox,
}: {
  title: string
  description?: React.ReactNode
  action?: React.ReactNode
  icon?: React.ComponentType<{ className?: string }>
}) {
  return (
    <div className="bg-dots flex flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-14 text-center">
      <div className="mb-4 flex size-12 items-center justify-center rounded-2xl border bg-card shadow-[var(--shadow-soft)]">
        <Icon className="size-5 text-primary" />
      </div>
      <p className="font-display text-lg font-semibold">{title}</p>
      {description ? <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}
