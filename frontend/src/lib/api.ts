// Thin JSON client for the local backend. All calls are relative (/api/...), so the
// same build works in dev (Vite proxy) and production (served by FastAPI).
// In the read-only online copy (lib/mirror.ts) GETs read recorded answers and nothing is written.
import { isMirror, mirrorGet, READ_ONLY_MESSAGE } from './mirror'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

type Params = Record<string, string | number | boolean | null | undefined | (string | number)[]>

export function qs(params?: Params): string {
  if (!params) return ''
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)))
    else sp.append(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

async function request<T>(method: string, path: string, body?: unknown, params?: Params): Promise<T> {
  if (isMirror()) {
    if (method !== 'GET') throw new ApiError(405, READ_ONLY_MESSAGE)
    return mirrorGet<T>(`/api${path}${qs(params)}`)
  }
  const res = await fetch(`/api${path}${qs(params)}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const j = await res.json()
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j)
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>('GET', path, undefined, params),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  del: <T>(path: string) => request<T>('DELETE', path),
}
