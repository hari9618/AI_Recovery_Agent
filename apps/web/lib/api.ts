/** Typed fetch helpers. All calls go through the Next.js server proxy (/api/proxy/...). */

export interface ApiErrorPayload {
  code: string
  category: string
  message: string
  retryable: boolean
  remediation?: string | null
  details?: Record<string, unknown> | null
}

export class ApiError extends Error {
  readonly status: number
  readonly payload: ApiErrorPayload

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message)
    this.status = status
    this.payload = payload
  }
}

type Query = Record<string, string | number | boolean | string[] | undefined | null>

function buildUrl(path: string, query?: Query): string {
  const url = new URL(`/api/proxy${path}`, window.location.origin)
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue
    if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, v))
    else url.searchParams.set(key, String(value))
  }
  return url.toString()
}

async function handle<T>(res: Response): Promise<T> {
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const payload: ApiErrorPayload = data?.error ?? {
      code: "http_error",
      category: "unavailable",
      message: `Request failed with status ${res.status}`,
      retryable: res.status >= 500,
    }
    throw new ApiError(res.status, payload)
  }
  return data as T
}

export async function apiGet<T>(path: string, query?: Query): Promise<T> {
  return handle<T>(await fetch(buildUrl(path, query), { cache: "no-store" }))
}

export async function apiSend<T>(method: "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown, query?: Query): Promise<T> {
  return handle<T>(
    await fetch(buildUrl(path, query), {
      method,
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  )
}

export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  return handle<T>(await fetch(buildUrl(path), { method: "POST", body: form }))
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.payload.message
  if (error instanceof Error) return error.message
  return "Something went wrong"
}
