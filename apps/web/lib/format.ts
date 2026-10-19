/** Formatting helpers. Currency uses Indian digit grouping (₹4,80,000) and lakh/crore compact forms. */

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })

export function formatMoney(value: number | null | undefined, currency = "INR"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  if (currency !== "INR") {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(value)
  }
  return inr.format(value)
}

/** ₹5.28 Cr, ₹4.8 L, ₹85K */
export function formatMoneyCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  const abs = Math.abs(value)
  const sign = value < 0 ? "-" : ""
  const trim = (n: number) => (n >= 100 ? n.toFixed(0) : n.toFixed(n >= 10 ? 1 : 2)).replace(/\.0+$|(\.\d*[1-9])0+$/, "$1")
  if (abs >= 1e7) return `${sign}₹${trim(abs / 1e7)} Cr`
  if (abs >= 1e5) return `${sign}₹${trim(abs / 1e5)} L`
  if (abs >= 1e3) return `${sign}₹${trim(abs / 1e3)}K`
  return `${sign}₹${abs.toFixed(0)}`
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—"
  return `${(value * 100).toFixed(digits)}%`
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return new Intl.NumberFormat("en-IN").format(value)
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—"
  return new Date(value).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—"
  return new Date(value).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
}

export function timeAgo(value: string | null | undefined): string {
  if (!value) return "—"
  const seconds = (Date.now() - new Date(value).getTime()) / 1000
  const abs = Math.abs(seconds)
  const units: [number, string][] = [
    [86400 * 30, "mo"],
    [86400, "d"],
    [3600, "h"],
    [60, "m"],
  ]
  for (const [size, label] of units) {
    if (abs >= size) return seconds >= 0 ? `${Math.floor(abs / size)}${label} ago` : `in ${Math.floor(abs / size)}${label}`
  }
  return "just now"
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "—"
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—"
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}
