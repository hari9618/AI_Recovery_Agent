import type { NextRequest } from "next/server"

import { ACCESS_COOKIE, ACCESS_MAX_AGE, accessGateEnabled, accessToken, isCorrectCode } from "@/lib/access"

/** Exchange the access code for an httpOnly cookie. Wrong codes are answered slowly to blunt guessing. */
export async function POST(req: NextRequest) {
  if (!accessGateEnabled()) return new Response(null, { status: 204 })
  let candidate = ""
  try {
    const body = (await req.json()) as { code?: unknown }
    candidate = typeof body.code === "string" ? body.code.slice(0, 200) : ""
  } catch {
    candidate = ""
  }
  if (!isCorrectCode(candidate)) {
    await new Promise((r) => setTimeout(r, 900))
    return Response.json({ error: { message: "That access code isn't right." } }, { status: 401 })
  }
  const res = new Response(null, { status: 204 })
  const secure = req.nextUrl.protocol === "https:" ? "; Secure" : ""
  res.headers.append("set-cookie", `${ACCESS_COOKIE}=${accessToken()}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${ACCESS_MAX_AGE}${secure}`)
  return res
}

/** Sign out of the private demo. */
export async function DELETE() {
  const res = new Response(null, { status: 204 })
  res.headers.append("set-cookie", `${ACCESS_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`)
  return res
}
