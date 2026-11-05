// Shared by the exporter scripts: the file name of a recorded API answer in the online copy.
// MUST match frontend/src/lib/mirror.ts (mirrorKey / mirrorHash); frontend/tests/mirror.test.ts
// checks that both give the same names.
import { createHash } from 'node:crypto'

/** Canonical key: path below /api + '?' + query parameters sorted (URLSearchParams.sort). */
export function mirrorKey(url) {
  const u = typeof url === 'string' ? new URL(url, 'http://mirror.invalid') : url
  const path = u.pathname.replace(/^\/api(?=\/|$)/, '')
  const sp = new URLSearchParams(u.search)
  sp.sort()
  return `${path}?${sp.toString()}`
}

/** First 24 hex characters of SHA-256(key). */
export function mirrorHash(key) {
  return createHash('sha256').update(key, 'utf8').digest('hex').slice(0, 24)
}

/** Read-only GET endpoints of the market sections: the only answers the copy may contain.
 * Everything else (settings, collection control, API-key status, run logs, raw files, search,
 * supplier quotes, alerts, archive, assistant...) is never recorded. */
export const CAPTURE = [
  /^\/meta$/,
  /^\/overview$/,
  /^\/prices\/(facets|series|latest|compare|observations|discrepancies)$/,
  /^\/news$/, /^\/news\/topics$/, /^\/news\/\d+$/,
  /^\/trade\/(facets|leaders|flows|series)$/,
  /^\/countries$/, /^\/countries\/[A-Za-z0-9_]+$/,
  /^\/regulations$/, /^\/regulations\/duties$/, /^\/regulations\/duties\/[A-Za-z0-9_]+$/,
  /^\/sources$/,
  /^\/quality\/(summary|issues)$/,
  /^\/reports$/, /^\/reports\/\d+$/,
  /^\/harvest\/(production|weather|reports)(\/[A-Za-z0-9_.-]+)?$/,
]

/** Query parameters that would turn a GET into something else than a JSON view. */
const NEVER_PARAMS = new Set(['format'])

export function capturable(key) {
  const q = key.indexOf('?')
  const path = key.slice(0, q)
  if (!CAPTURE.some((re) => re.test(path))) return false
  for (const k of new URLSearchParams(key.slice(q + 1)).keys()) if (NEVER_PARAMS.has(k)) return false
  return true
}
