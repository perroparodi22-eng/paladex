// Small helpers for the harvest page: condition colours, signed numbers, month names.
import { fmtNumber, fmtPeriod } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type { Condition, Flag, HarvestRegion, RuleKey } from './types'

/** Marker / badge colours per condition (distinct hues, readable on the pale map and on white). */
export const CONDITION_COLORS: Record<Condition, string> = {
  drought_watch: '#B26B12',
  heat_stress: '#B23A2A',
  wet_season: '#2F64B0',
  normal: '#3A7A60',
  no_data: '#A9A59A',
}

export const RULE_ORDER: RuleKey[] = ['drought_watch', 'heat_stress', 'wet_season']

/** "+2,6 °C" / "−0,3 °C" */
export function fmtAnomaly(v: number | null | undefined, lang: Lang): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const s = fmtNumber(Math.abs(v), lang, 1)
  return `${v > 0.04 ? '+' : v < -0.04 ? '−' : '±'}${s} °C`
}

/** "45%" (of normal) */
export function fmtPctOfNormal(v: number | null | undefined, lang: Lang): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${fmtNumber(v, lang, 0)}%`
}

export function monthName(m: number, lang: Lang): string {
  return new Intl.DateTimeFormat(lang === 'it' ? 'it-IT' : 'en-GB', { month: 'short' }).format(new Date(2026, m - 1, 15))
}

/** Context months (1-12, in season order, possibly over the new year) -> "ott–mar". */
export function monthSpan(months: number[], lang: Lang): string {
  if (!months.length) return '—'
  return months.length === 1 ? monthName(months[0], lang) : `${monthName(months[0], lang)}–${monthName(months[months.length - 1], lang)}`
}

/** "mar–apr 2026" / "giu 2026" for a flag's consecutive months. */
export function fmtMonthRun(labels: string[], lang: Lang): string {
  if (!labels.length) return '—'
  if (labels.length === 1) return fmtPeriod(labels[0], lang)
  const [y1, m1] = labels[0].split('-').map(Number)
  const [y2, m2] = labels[labels.length - 1].split('-').map(Number)
  if (y1 === y2) return `${monthName(m1, lang)}–${monthName(m2, lang)} ${y2}`
  return `${fmtPeriod(labels[0], lang)} – ${fmtPeriod(labels[labels.length - 1], lang)}`
}

/** A flag's values in words: "41% e 53%" / "+4,2 °C and +2,1 °C". */
export function fmtFlagValues(f: Flag, lang: Lang): string {
  const vals = f.values.map((v) => (f.metric === 'temp_anomaly_c' ? fmtAnomaly(v, lang) : fmtPctOfNormal(v, lang)))
  if (vals.length <= 1) return vals.join('')
  const and = lang === 'it' ? ' e ' : ' and '
  return `${vals.slice(0, -1).join(', ')}${and}${vals[vals.length - 1]}`
}

export function regionName(r: Pick<HarvestRegion, 'name_it' | 'name_en'>, lang: Lang): string {
  return lang === 'it' ? r.name_it : r.name_en
}

export function countryOf(r: Pick<HarvestRegion, 'country_name_it' | 'country_name_en' | 'country_iso3'>, lang: Lang): string {
  return (lang === 'it' ? r.country_name_it ?? r.country_name_en : r.country_name_en ?? r.country_name_it) ?? r.country_iso3
}

/** The colour of a region's markers: its main signal of the last 12 months (recent first). */
export function regionColor(r: Pick<HarvestRegion, 'condition'>): string {
  return CONDITION_COLORS[r.condition]
}
