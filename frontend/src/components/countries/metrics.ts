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

/** Compact legend bound: 66 811 -> "67 mila" / "67k" */
export function fmtBound(v: number, m: MapMetric, lang: Lang): string {
  if (m === 'news') return fmtNumber(v, lang)
  return new Intl.NumberFormat(lang === 'it' ? 'it-IT' : 'en-GB', { notation: 'compact', maximumFractionDigits: v < 1000 ? 0 : 1 }).format(v)
}
