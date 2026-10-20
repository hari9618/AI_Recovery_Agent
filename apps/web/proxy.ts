import { NextResponse, type NextRequest } from "next/server"

import { ACCESS_COOKIE, accessGateEnabled, hasValidAccess } from "@/lib/access"

const OPEN_PATHS = ["/access", "/api/access"]

/** Private-demo gate: without a valid access cookie, pages redirect to /access and API calls get 401. */
export function proxy(request: NextRequest) {
  if (!accessGateEnabled()) return NextResponse.next()
  const { pathname, search } = request.nextUrl
  if (OPEN_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) return NextResponse.next()
  if (hasValidAccess(request.cookies.get(ACCESS_COOKIE)?.value)) return NextResponse.next()

  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { error: { code: "unauthenticated", category: "access", message: "Access code required", retryable: false } },
      { status: 401 },
    )
  }
  const url = request.nextUrl.clone()
  url.pathname = "/access"
  url.search = `?next=${encodeURIComponent(pathname + search)}`
  return NextResponse.redirect(url)
}

export const config = {
  // Everything except build assets and public files.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|samples/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt|csv|woff2?)$).*)"],
}
