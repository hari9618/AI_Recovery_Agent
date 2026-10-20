import type { NextRequest } from "next/server"

import { ACCESS_COOKIE, hasValidAccess } from "@/lib/access"

/**
 * Server-side proxy to the FastAPI backend.
 *
 * The API token lives only in server environment variables (API_TOKEN) and is attached here,
 * so it never reaches the browser bundle or network tab.
 */
const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000"
const API_TOKEN = process.env.API_TOKEN ?? ""
const FORWARD_HEADERS = ["content-type", "accept", "x-request-id"]

// Copilot answers and the demo loader can take tens of seconds on a hosted API.
export const maxDuration = 120

async function forward(req: NextRequest, path: string[]) {
  // Defence in depth: proxy.ts already gates every request, but this route holds the API token.
  if (!hasValidAccess(req.cookies.get(ACCESS_COOKIE)?.value)) {
    return Response.json(
      { error: { code: "unauthenticated", category: "access", message: "Access code required", retryable: false } },
      { status: 401 },
    )
  }
  const target = new URL(`/api/v1/${path.map(encodeURIComponent).join("/")}`, API_BASE_URL)
  target.search = req.nextUrl.search

  const headers = new Headers()
  for (const name of FORWARD_HEADERS) {
    const value = req.headers.get(name)
    if (value) headers.set(name, value)
  }
  if (API_TOKEN) headers.set("authorization", `Bearer ${API_TOKEN}`)

  const hasBody = !["GET", "HEAD"].includes(req.method)
  try {
    const upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      cache: "no-store",
    })
    const body = await upstream.arrayBuffer()
    return new Response(body, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    })
  } catch {
    return Response.json(
      {
        error: {
          code: "api_unreachable",
          category: "unavailable",
          message: `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`,
          retryable: true,
          remediation: "Start the API: uv run --project apps/api uvicorn app.main:app --port 8000",
        },
      },
      { status: 502 },
    )
  }
}

export async function GET(req: NextRequest, ctx: RouteContext<"/api/proxy/[...path]">) {
  return forward(req, (await ctx.params).path)
}
export async function POST(req: NextRequest, ctx: RouteContext<"/api/proxy/[...path]">) {
  return forward(req, (await ctx.params).path)
}
export async function PUT(req: NextRequest, ctx: RouteContext<"/api/proxy/[...path]">) {
  return forward(req, (await ctx.params).path)
}
export async function PATCH(req: NextRequest, ctx: RouteContext<"/api/proxy/[...path]">) {
  return forward(req, (await ctx.params).path)
}
export async function DELETE(req: NextRequest, ctx: RouteContext<"/api/proxy/[...path]">) {
  return forward(req, (await ctx.params).path)
}
