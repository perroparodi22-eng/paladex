// Plain-language explanations of collection results for a non-technical reader.
// Mirrors backend services/quality.explain_error(); the raw text stays available under "Dettagli tecnici".

/** i18n key (sources.err.*) for a technical error message. */
export function errorKey(error: string | null | undefined): string {
  const e = (error ?? '').toLowerCase()
  if (e.includes('api key') || e.includes('key not configured')) return 'sources.err.key'
  if (e.includes('no internet') || e.includes('cannot reach') || e.includes('connecterror') || e.includes('name resolution')) return 'sources.err.offline'
  if (e.includes('timeout') || e.includes('timed out')) return 'sources.err.timeout'
  if (e.includes('http 404') || e.includes('http 410')) return 'sources.err.notFound'
  if (e.includes('http 401') || e.includes('http 403')) return 'sources.err.denied'
  if (e.includes('http 429')) return 'sources.err.rate'
  if (/http 5\d\d/.test(e)) return 'sources.err.server'
  if (['pars', 'format', 'no rates', 'contained no', 'unexpected', 'keyerror', 'valueerror', 'indexerror'].some((w) => e.includes(w))) return 'sources.err.format'
  return 'sources.err.generic'
}

/** i18n key explaining a run outcome. */
export function runExplanationKey(status: string, error: string | null | undefined): string {
  switch (status) {
    case 'success':
    case 'partial':
    case 'no_change':
    case 'offline':
    case 'running':
      return `sources.runs.explain.${status}`
    case 'skipped':
      return (error ?? '').toLowerCase().includes('key') ? 'sources.runs.explain.skipped.key' : 'sources.runs.explain.skipped'
    case 'failed':
      return errorKey(error)
    default:
      return 'sources.err.generic'
  }
}

export type RunTone = 'up' | 'down' | 'warn' | 'neutral' | 'outline' | 'forest'

export function runTone(status: string | null | undefined): RunTone {
  switch (status) {
    case 'success': return 'up'
    case 'no_change': return 'forest'
    case 'partial': return 'warn'
    case 'failed': return 'down'
    case 'offline':
    case 'skipped': return 'outline'
    default: return 'neutral'
  }
}

/** The backend stores naive UTC timestamps ("2026-11-02T08:55:00"): mark them as UTC so clock
 * times are shown in the reader's local time. Dates ("2026-11-02") are returned unchanged. */
export function asUtc(iso: string | null | undefined): string | null {
  if (!iso) return null
  if (iso.length <= 10 || iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso)) return iso
  return `${iso}Z`
}
