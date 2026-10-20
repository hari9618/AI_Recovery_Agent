/** Only same-site relative paths are allowed as a post-login destination (no open redirect). */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/"
  return next
}
