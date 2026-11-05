// Read-only online copy ("mirror mode"), for the owner's phone when away from the computer.
//
// Enabled only in a build made with VITE_PALADEX_MIRROR=1 (scripts/mirror/build.sh); the normal
// build never takes these code paths. In mirror mode every GET /api/... request is answered from
// a static file that the exporter recorded from the real application:
//
//     key  = `${path below /api}?${query parameters, sorted}`        (mirrorKey)
//     file = /mirror/<first 24 hex chars of SHA-256(key)>.json      (mirrorFile)
//
// The exporter (scripts/mirror/key.mjs) computes exactly the same key from the request URL it
// recorded, so the copy answers precisely the views it captured, with the application's own
// answers (provenance included). Anything else is honest about it:
//   * a view that was not captured raises MirrorMissingError, which <ErrorBlock> shows as
//     "this view is not in the online copy: it is available on the computer";
//   * requests that would change data are refused by lib/api.ts (read-only copy);
//   * /mirror/manifest.json says when the copy was produced, shown on every page (MirrorStrip).
import { useQuery } from '@tanstack/react-query'

const BUILD_FLAG = import.meta.env.VITE_PALADEX_MIRROR === '1'
let override: boolean | null = null

/** True in the read-only online copy (a build made with VITE_PALADEX_MIRROR=1). */
export function isMirror(): boolean {
  return override ?? BUILD_FLAG
}

/** Tests only: force mirror mode on or off (null = follow the build flag). */
export function setMirrorMode(on: boolean | null): void {
  override = on
}

export const MIRROR_BASE = '/mirror'

/** Interactive tools and private business data that the online copy never contains. Their
 *  menu entries are hidden in the copy and their requests are answered "not in the copy"
 *  without any network request. */
export const MIRROR_HIDDEN_ROUTES = ['/offerte', '/avvisi', '/assistente', '/archivio', '/cerca']

const NEVER_IN_COPY = [
  /^\/settings$/, /^\/collect(\/|$)/, /^\/demo(\/|$)/, /^\/health$/, /^\/search$/,
  /^\/quality\/(keys|run)$/, /^\/sources\/[^/]+\/runs$/, /^\/reports\/[^/]+\/file$/,
  /^\/(quotes|alerts|archive|assistant)(\/|$)/,
]

/** Texts used where no translation context exists (the interface translates them by key). */
export const READ_ONLY_MESSAGE =
  'Copia online di sola lettura: le modifiche si fanno sul computer. / Read-only online copy: changes are made on the computer.'
const MISSING_MESSAGE =
  'Questa vista non è inclusa nella copia online: è disponibile sul computer. / This view is not included in the online copy: it is available on the computer.'

/** A view the online copy does not contain (never captured, or private by design). */
export class MirrorMissingError extends Error {
  readonly mirrorMissing = true
  constructor(public readonly key: string) {
    super(MISSING_MESSAGE)
    this.name = 'MirrorMissingError'
  }
}

export function isMirrorMissing(e: unknown): e is MirrorMissingError {
  return e instanceof MirrorMissingError || (typeof e === 'object' && e !== null && (e as { mirrorMissing?: unknown }).mirrorMissing === true)
}

/** Canonical key of an API request: the path below /api plus the query string with its parameters
 *  sorted (URLSearchParams.sort keeps repeated parameters in their order). Both sides parse a URL
 *  with the same WHATWG URL parser, so encoding differences cannot make the keys differ. */
export function mirrorKey(url: string | URL): string {
  const u = typeof url === 'string' ? new URL(url, 'http://mirror.invalid') : url
  const path = u.pathname.replace(/^\/api(?=\/|$)/, '')
  const sp = new URLSearchParams(u.search)
  sp.sort()
  return `${path}?${sp.toString()}`
}

/** True when a key belongs to something the copy never contains (private or interactive). */
export function neverInCopy(key: string): boolean {
  const path = key.slice(0, key.indexOf('?') < 0 ? undefined : key.indexOf('?'))
  return NEVER_IN_COPY.some((re) => re.test(path))
}

function hex(bytes: Uint8Array): string {
  let s = ''
  for (const b of bytes) s += b.toString(16).padStart(2, '0')
  return s
}

/** First 24 hex characters of SHA-256(key) (Web Crypto, or the fallback below where the page is
 *  not a secure context and `crypto.subtle` is missing). */
export async function mirrorHash(key: string): Promise<string> {
  const bytes = new TextEncoder().encode(key)
  const subtle = globalThis.crypto?.subtle
  const digest = subtle ? new Uint8Array(await subtle.digest('SHA-256', bytes)) : sha256(bytes)
  return hex(digest).slice(0, 24)
}

export async function mirrorFile(key: string): Promise<string> {
  return `${MIRROR_BASE}/${await mirrorHash(key)}.json`
}

/** GET in mirror mode: the recorded answer of the real application for exactly this request. */
export async function mirrorGet<T>(url: string, fetchImpl: typeof fetch = fetch): Promise<T> {
  const key = mirrorKey(url)
  if (neverInCopy(key)) throw new MirrorMissingError(key)
  const res = await fetchImpl(await mirrorFile(key), { headers: { Accept: 'application/json' } })
  // A file the copy does not have answers 404 (or, behind a plain SPA fallback, the HTML page).
  if (!res.ok || !(res.headers.get('content-type') ?? '').includes('json')) return missing(key)
  try {
    return (await res.json()) as T
  } catch {
    return missing(key)
  }
}

function missing(key: string): never {
  // Read by the exporter's check of the finished copy (scripts/mirror/crawl.mjs --verify).
  console.info(`[mirror] not in the copy: ${key}`)
  throw new MirrorMissingError(key)
}

/** /mirror/manifest.json, written by the exporter. Times are UTC ISO strings. */
export interface MirrorManifest {
  format: number
  /** When this copy was produced. */
  generated_at: string
  /** Newest successful check of the sources (else the newest collected figure): the data is
   *  "collected up to" this moment. */
  data_collected_until: string | null
  /** Expected refresh rhythm ("daily"). */
  refresh: string
  files: number
}

export async function loadManifest(fetchImpl: typeof fetch = fetch): Promise<MirrorManifest> {
  const res = await fetchImpl(`${MIRROR_BASE}/manifest.json`, { cache: 'no-cache', headers: { Accept: 'application/json' } })
  if (!res.ok) throw new MirrorMissingError('manifest')
  return (await res.json()) as MirrorManifest
}

export function useMirrorManifest() {
  return useQuery({
    queryKey: ['mirror-manifest'],
    queryFn: () => loadManifest(),
    enabled: isMirror(),
    staleTime: 10 * 60_000,
    refetchInterval: 30 * 60_000,
  })
}

/** Age of the copy in whole hours (null when unknown). */
export function copyAgeHours(m: Pick<MirrorManifest, 'generated_at'> | undefined, now = Date.now()): number | null {
  if (!m?.generated_at) return null
  const t = Date.parse(m.generated_at)
  return Number.isNaN(t) ? null : Math.max(0, Math.floor((now - t) / 3_600_000))
}

// ---------------------------------------------------------------------------------------------
// SHA-256 for pages opened without a secure context (no crypto.subtle). Constants are derived
// from the primes as in FIPS 180-4; tests compare the result with Node's crypto.
// ---------------------------------------------------------------------------------------------
const PRIMES: number[] = []
for (let n = 2; PRIMES.length < 64; n++) if (PRIMES.every((p) => n % p !== 0)) PRIMES.push(n)
const frac32 = (x: number) => ((x - Math.floor(x)) * 0x100000000) >>> 0
const K = Uint32Array.from(PRIMES, (p) => frac32(Math.cbrt(p)))
const H0 = Uint32Array.from(PRIMES.slice(0, 8), (p) => frac32(Math.sqrt(p)))

export function sha256(data: Uint8Array): Uint8Array {
  const len = data.length
  const n = Math.ceil((len + 9) / 64) * 64
  const buf = new Uint8Array(n)
  buf.set(data)
  buf[len] = 0x80
  const view = new DataView(buf.buffer)
  view.setUint32(n - 8, Math.floor(len / 0x20000000))
  view.setUint32(n - 4, (len * 8) >>> 0)
  const H = H0.slice()
  const W = new Uint32Array(64)
  const rotr = (x: number, r: number) => (x >>> r) | (x << (32 - r))
  for (let off = 0; off < n; off += 64) {
    for (let t = 0; t < 16; t++) W[t] = view.getUint32(off + t * 4)
    for (let t = 16; t < 64; t++) {
      const s0 = rotr(W[t - 15], 7) ^ rotr(W[t - 15], 18) ^ (W[t - 15] >>> 3)
      const s1 = rotr(W[t - 2], 17) ^ rotr(W[t - 2], 19) ^ (W[t - 2] >>> 10)
      W[t] = (W[t - 16] + s0 + W[t - 7] + s1) | 0
    }
    let a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7]
    for (let t = 0; t < 64; t++) {
      const t1 = (h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[t] + W[t]) | 0
      const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0
      h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0
    }
    H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h
  }
  const out = new Uint8Array(32)
  const ov = new DataView(out.buffer)
  H.forEach((x, i) => ov.setUint32(i * 4, x))
  return out
}
