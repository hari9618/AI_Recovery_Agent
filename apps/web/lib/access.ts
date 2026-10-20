import { createHmac, timingSafeEqual } from "node:crypto"

/**
 * Private-demo access gate.
 *
 * When ACCESS_CODE is set (server-only env var), every page and API call needs a cookie proving the visitor
 * entered the code. The cookie holds an HMAC of a fixed label keyed by the code, never the code itself, so
 * changing ACCESS_CODE revokes every issued cookie at once. Without ACCESS_CODE (local development) the gate is off.
 */
export const ACCESS_COOKIE = "rr_access"
export const ACCESS_MAX_AGE = 60 * 60 * 24 * 30 // 30 days

function code(): string {
  return (process.env.ACCESS_CODE ?? "").trim()
}

export function accessGateEnabled(): boolean {
  return code().length > 0
}

export function accessToken(): string {
  return createHmac("sha256", code()).update("revenue-recovery-access:v1").digest("hex")
}

function safeEqual(a: string, b: string): boolean {
  const left = Buffer.from(a)
  const right = Buffer.from(b)
  return left.length === right.length && timingSafeEqual(left, right)
}

export function hasValidAccess(cookie: string | undefined): boolean {
  if (!accessGateEnabled()) return true
  return Boolean(cookie) && safeEqual(cookie as string, accessToken())
}

export function isCorrectCode(candidate: string): boolean {
  return accessGateEnabled() && safeEqual(candidate.trim(), code())
}
