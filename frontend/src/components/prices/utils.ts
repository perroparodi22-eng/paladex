// Helpers for the price pages: units, periods, labels, palette.
import { fmtNumber, fmtPeriod } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type { Ccy, Freq, MassUnit, PriceTypeKey, RangePreset, SeriesIdentity } from './types'

/** Price types offered in the selector, in the order a bulk buyer cares about them. */
export const PRICE_TYPE_ORDER: PriceTypeKey[] = ['wholesale_bulk', 'import_unit_value', 'producer', 'export_unit_value', 'retail']

/** Sources that will feed each price type once collected (shown in empty states). */
export const SOURCES_BY_TYPE: Record<string, string[]> = {
  wholesale_bulk: ['usda_honey', 'osservatorio_miele'],
  producer: ['usda_honey', 'usda_nass', 'faostat'],
  import_unit_value: ['comtrade', 'eurostat'],
  export_unit_value: ['comtrade', 'eurostat'],
  retail: [],
  other: [],
}

/**
 * Categorical palette for chart lines, validated with the dataviz palette checker
 * (lightness band, chroma floor, adjacent CVD ΔE ≥ 8, normal-vision ΔE ≥ 15 on white).
 * Slot 4 (gold) is below 3:1 contrast, so every line is also named in the legend and the
 * table. Never more than 8 lines are shown at once: hues are never cycled.
 */
export const SERIES_COLORS = ['#2f6fb5', '#c8741f', '#178a68', '#d4a017', '#b84f86', '#5f8f22', '#6b57c6', '#c2453a']
export const MAX_VISIBLE = SERIES_COLORS.length
/** Lines drawn when a view opens. A large view ships the points of these first series only:
 * backend api/prices.py SERIES_DEFAULT_POINTS must stay equal. */
export const DEFAULT_VISIBLE = 6

export const KG_PER_LB = 0.45359237

/** Convert a per-kg price to the display unit. */
export function toUnit(v: number | null | undefined, unit: MassUnit): number | null {
  if (v === null || v === undefined) return null
  return unit === 'lb' ? v * KG_PER_LB : v
}

export function unitLabel(ccy: string, unit: MassUnit | string): string {
  return `${ccy}/${unit}`
}

export function fmtPrice(v: number | null | undefined, lang: Lang, digits = 2): string {
  return fmtNumber(v ?? null, lang, digits)
}

/** "2026-09" -> "set 2026", "2026-Q3" -> "T3 2026" / "Q3 2026", "2026" -> "2026". */
export function fmtPeriodLabel(label: string | null | undefined, lang: Lang): string {
  if (!label) return '—'
  const q = /^(\d{4})-Q([1-4])$/.exec(label)
  if (q) return lang === 'it' ? `T${q[2]} ${q[1]}` : `Q${q[2]} ${q[1]}`
  return fmtPeriod(label, lang)
}

/** First month (YYYY-MM) of a period preset, counted back from the current month. */
export function rangeFrom(range: RangePreset, today = new Date()): string | null {
  if (range === 'all') return null
  const years = range === '1y' ? 1 : range === '3y' ? 3 : 5
  const idx = today.getFullYear() * 12 + today.getMonth() - (years * 12 - 1)
  return `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, '0')}`
}

export const FREQS: Freq[] = ['M', 'Q', 'A']
export const CCYS: Ccy[] = ['USD', 'EUR']
export const RANGES: RangePreset[] = ['1y', '3y', '5y', 'all']

/** Value in the requested currency for a raw observation row. */
export function rowValuePerKg(row: { currency: string; price_per_kg: number; usd_per_kg: number | null; eur_per_kg: number | null }, ccy: Ccy): number | null {
  if (row.currency === ccy) return row.price_per_kg
  return ccy === 'USD' ? row.usd_per_kg : row.eur_per_kg
}

const COLOR_KEYS = ['water white', 'extra white', 'white', 'extra light amber', 'light amber', 'amber', 'dark amber', 'dark']

/** Translation key for a USDA-style colour grade, or null when the raw text should be shown. */
export function colorKey(c: string | null | undefined): string | null {
  if (!c) return null
  const k = c.trim().toLowerCase()
  return COLOR_KEYS.includes(k) ? `prices.color.${k.replace(/ /g, '_')}` : null
}

export interface LabelFns {
  country: (iso3: string | null | undefined) => string
  variety: (k: string | null | undefined) => string
  t: (key: string, vars?: Record<string, string | number>) => string
}

export function colorLabel(c: string | null | undefined, t: LabelFns['t']): string {
  if (!c || c === '_none') return t('prices.color.none')
  const k = colorKey(c)
  return k ? t(k) : c.charAt(0).toUpperCase() + c.slice(1)
}

/** Which identity fields differ between the series on screen (only those are named in labels). */
export function varyingDims(items: SeriesIdentity[]) {
  const differs = (f: (s: SeriesIdentity) => unknown) => new Set(items.map((s) => String(f(s)))).size > 1
  return {
    origin: true,
    variety: differs((s) => s.variety),
    color: differs((s) => s.color_grade),
    source: differs((s) => s.source?.key),
    market: differs((s) => s.market_iso3),
    terms: differs((s) => s.terms),
    organic: differs((s) => s.organic),
  }
}

/** Short series name built only from the fields that distinguish it from its neighbours. */
export function seriesLabel(s: SeriesIdentity, dims: ReturnType<typeof varyingDims>, fns: LabelFns): string {
  const parts: string[] = [s.origin_iso3 ? fns.country(s.origin_iso3) : s.origin_label || fns.t('prices.originUnknown')]
  if (dims.variety) parts.push(fns.variety(s.variety))
  if (dims.color && s.color_grade) parts.push(colorLabel(s.color_grade, fns.t))
  if (dims.organic && s.organic) parts.push(fns.t('prices.organic'))
  if (dims.market) parts.push(`${fns.t('prices.marketShort')} ${fns.country(s.market_iso3)}`)
  if (dims.source && s.source) parts.push(s.source.publisher || s.source.name)
  if (dims.terms && s.terms && !dims.source) parts.push(s.terms)
  return parts.join(' · ')
}

/** Series that still share a label (same origin, variety and source, different terms: Cuneo's
 * monthly list next to its annual average) get the terms the others lack ("media annua"), so the
 * chart legend never lists two identical names. */
export function disambiguateLabels(series: (SeriesIdentity & { id: string })[], labels: Record<string, string>): Record<string, string> {
  const groups = new Map<string, (SeriesIdentity & { id: string })[]>()
  for (const s of series) groups.set(labels[s.id], [...(groups.get(labels[s.id]) ?? []), s])
  const out = { ...labels }
  for (const [label, group] of groups) {
    if (group.length < 2) continue
    const parts = group.map((s) => (s.terms ?? '').split(';').map((x) => x.trim()).filter(Boolean))
    group.forEach((s, i) => {
      const own = parts[i].filter((p) => !parts.every((other) => other.includes(p)))
      if (own.length) out[s.id] = `${label} · ${own.join('; ')}`
    })
  }
  return out
}
