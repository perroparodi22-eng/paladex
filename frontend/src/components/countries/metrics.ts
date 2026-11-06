// What each map metric reads from a country row, and how it is formatted.
import { fmtNumber } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type { CountryListItem, MapMetric } from './types'

export const MAP_METRICS: MapMetric[] = ['exports', 'production', 'imports', 'news']

/** Value used for colouring (tonnes for volumes, article count for news). null = no data. */
export function metricValue(c: CountryListItem, m: MapMetric): number | null {
  const x = c.metrics
  if (m === 'exports') return x.exports?.net_weight_kg != null ? x.exports.net_weight_kg / 1000 : null
  if (m === 'imports') return x.imports?.net_weight_kg != null ? x.imports.net_weight_kg / 1000 : null
  if (m === 'production') return x.production?.value_t ?? null
  return x.news_30d && x.news_30d.count > 0 ? x.news_30d.count : null
}

export function metricYear(c: CountryListItem, m: MapMetric): string | null {
  const x = c.metrics
  if (m === 'exports') return x.exports ? String(x.exports.year) : null
  if (m === 'imports') return x.imports ? String(x.imports.year) : null
  if (m === 'production') return x.production ? x.production.period_label : null
  return null
}

export function metricSource(c: CountryListItem, m: MapMetric): { name: string | null; demo: boolean; status: string | null } {
  const h = m === 'exports' ? c.metrics.exports : m === 'imports' ? c.metrics.imports : m === 'production' ? c.metrics.production : null
  if (!h) return { name: null, demo: false, status: null }
  return { name: h.source ? h.source.publisher || h.source.name : null, demo: Boolean(h.is_demo), status: h.data_status ?? null }
}

/** "61.671 t" / "12 notizie" */
export function fmtMetric(v: number | null, m: MapMetric, lang: Lang, newsUnit: string): string {
  if (v === null) return '—'
  if (m === 'news') return `${fmtNumber(v, lang)} ${newsUnit}`
  return `${fmtNumber(v, lang, v < 10 ? 1 : 0)} t`
}

/** Year of the figure coloured on the map (null for news, which counts the last 30 days). */
export function metricYearNum(c: CountryListItem, m: MapMetric): number | null {
  const x = c.metrics
  if (m === 'exports') return x.exports?.year ?? null
  if (m === 'imports') return x.imports?.year ?? null
  if (m === 'production') return x.production?.year ?? null
  return null
}

/** Legend label of one fixed class, contiguous with its neighbours: "< 100 t", "100 – 1.000 t",
 * "≥ 50.000 t"; news counts are whole articles: "1", "2 – 3", "≥ 21". */
export function fmtClassRange(lo: number | null, hi: number | null, m: MapMetric, lang: Lang): string {
  if (m === 'news') {
    const a = lo ?? 1
    if (hi === null) return `≥ ${fmtNumber(a, lang)}`
    const b = hi - 1
    return a === b ? fmtNumber(a, lang) : `${fmtNumber(a, lang)} – ${fmtNumber(b, lang)}`
  }
  if (lo === null) return `< ${fmtNumber(hi, lang)} t`
  if (hi === null) return `≥ ${fmtNumber(lo, lang)} t`
  return `${fmtNumber(lo, lang)} – ${fmtNumber(hi, lang)} t`
}

/** Short name of a source for the map legend: "UN Comtrade", "FAOSTAT", "Eurostat Comext",
 * "Argentina – INDEC" (the registry names continue with a description after ":" or "—"). */
export function shortSourceName(s: { name: string; name_en?: string | null } | null | undefined, lang: Lang): string {
  if (!s) return '—'
  const full = (lang === 'en' && s.name_en) || s.name
  for (const sep of [': ', ' — ']) {
    const i = full.indexOf(sep)
    if (i > 0) return full.slice(0, i)
  }
  const dash = full.indexOf(' – ')
  return dash > 0 ? full.slice(0, dash) : full
}

/** The source object behind a country's figure for a metric (null for news). */
export function metricSourceBrief(c: CountryListItem, m: MapMetric) {
  const h = m === 'exports' ? c.metrics.exports : m === 'imports' ? c.metrics.imports : m === 'production' ? c.metrics.production : null
  return h?.source ?? null
}
