// Pure helpers of the archive views (kept apart so tests can call them directly).
import { KG_PER_LB } from '@/components/prices/utils'
import type { Lang } from '@/lib/types'
import type { Overlay, OverlayPoint, SeriesMeta } from './types'

export const YEAR_COLORS = ['#143A2B', '#A8873A', '#8A877C'] as const

export function monthNames(lang: Lang, style: 'short' | 'long' = 'short'): string[] {
  const fmt = new Intl.DateTimeFormat(lang === 'it' ? 'it-IT' : 'en-GB', { month: style, timeZone: 'UTC' })
  return Array.from({ length: 12 }, (_, i) => fmt.format(new Date(Date.UTC(2024, i, 15))))
}

/** Value per kg → per `unit` (prices only). */
export function perUnit(v: number | null | undefined, unit: 'kg' | 'lb'): number | null {
  if (v === null || v === undefined) return null
  return unit === 'lb' ? v * KG_PER_LB : v
}

export type OverlayRow = { month: number; label: string } & Record<string, number | null | OverlayPoint | string>

/** One row per month with a value per year (`y2026`) and its point (`p2026`); a month without
 * data stays null so the chart shows a gap, never an interpolated line. */
export function overlayRows(ov: Overlay, unit: 'kg' | 'lb', lang: Lang): OverlayRow[] {
  const names = monthNames(lang)
  return names.map((label, i) => {
    const row: OverlayRow = { month: i + 1, label }
    for (const y of ov.years) {
      const p = y.points[i]
      row[`y${y.year}`] = p ? perUnit(p.value, unit) : null
      if (p) row[`p${y.year}`] = p
    }
    return row
  })
}

/** "Eurostat (European Commission) · Unione Europea · mensile": what tells the series of one selection
 * apart. When two would still read the same, the source's own terms are added to both. */
export function seriesLabels(series: SeriesMeta[], fns: { country: (c: string | null) => string; color: (c: string | null) => string;
  t: (k: string) => string }): Record<string, string> {
  const base = (s: SeriesMeta) => {
    const parts = [s.source?.publisher || s.source?.name || '—']
    if (s.market_iso3) parts.push(fns.country(s.market_iso3))
    if (s.market_location && s.market_location !== s.market_iso3) parts.push(s.market_location)
    if (s.color_grade) parts.push(fns.color(s.color_grade))
    parts.push(fns.t(`archive.p.freq.${s.freq}`))
    return parts.join(' · ')
  }
  const counts = new Map<string, number>()
  for (const s of series) counts.set(base(s), (counts.get(base(s)) ?? 0) + 1)
  const out: Record<string, string> = {}
  for (const s of series) {
    const b = base(s)
    out[s.id] = (counts.get(b) ?? 0) > 1 && (s.terms || s.variety_raw.length) ? `${b} · ${s.terms || s.variety_raw.join(', ')}` : b
  }
  return out
}

export function yearRange(first: string | null | undefined, last: string | null | undefined): string {
  if (!first || !last) return '—'
  return first.slice(0, 4) === last.slice(0, 4) ? first.slice(0, 4) : `${first.slice(0, 4)}–${last.slice(0, 4)}`
}
