import { ChevronLeft, ChevronRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { formatNumber } from "@/lib/format"

export function Pagination({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  if (total <= limit) return <p className="mt-3 text-xs text-muted-foreground">{formatNumber(total)} results</p>
  const page = Math.floor(offset / limit) + 1
  const pages = Math.ceil(total / limit)
  return (
    <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
      <span>
        {formatNumber(offset + 1)}–{formatNumber(Math.min(offset + limit, total))} of {formatNumber(total)}
      </span>
      <div className="flex items-center gap-2">
        <Button size="icon" variant="outline" className="size-7" disabled={page <= 1} onClick={() => onChange(offset - limit)} aria-label="Previous page">
          <ChevronLeft />
        </Button>
        <span>
          Page {page} of {pages}
        </span>
        <Button size="icon" variant="outline" className="size-7" disabled={page >= pages} onClick={() => onChange(offset + limit)} aria-label="Next page">
          <ChevronRight />
        </Button>
      </div>
    </div>
  )
}
