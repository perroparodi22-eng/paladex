// "2026 finora" — year-to-date figures from monthly customs data (backend/paladex/api/ytd.py): the
// running year's months against THE SAME months of the year before, from ONE source.
import type { Freshness, Lang } from '@/lib/types'
import type { TradeProv } from './types'

export interface YtdPrevious {
  year: number; period_label: string; net_weight_kg: number | null; usd_value: number | null
  unit_value_usd_per_kg: number | null; fx_missing: boolean; data_status: string | null
  published_at: string | null; is_demo: boolean
}

export interface YtdFigure extends TradeProv {
  iso3: string; name_it: string | null; name_en: string | null
  /** overview rows: name in the page language and the country page */
  name?: string; link?: string; flow?: 'import' | 'export'
  year: number; prev_year: number; month_from: number; month_to: number; months_count: number; is_current_year: boolean
  net_weight_kg: number | null; usd_value: number | null; unit_value_usd_per_kg: number | null; fx_missing: boolean
  /** the previous year has every month Jan..month_to from the same source */
  comparable: boolean
  previous: YtdPrevious | null
  /** months of the previous year this source has, when the change cannot be computed */
  prev_months_available: number[] | null
  change_volume_pct: number | null; change_value_pct: number | null; change_unit_value_pct: number | null
  summed_from_partners: boolean; partners_count: number | null
  /** newer months left out: published without the total (partial release), or after a missing month */
  excluded_months: { month: string; reason: 'no_total' | 'after_gap' }[]
  freshness: Freshness | null
}

export type YtdStatus = 'ok' | 'no_monthly' | 'full_year' | 'stale' | 'incomplete'

export interface YtdSection {
  own: YtdFigure | null
  status: YtdStatus
  /** newest month with a published total, any source ("2026-07") */
  last_month: string | null
  /** what partner countries declare month by month (only when the country has no figure of its own) */
  mirror: { declared_flow: 'import' | 'export'; rows: YtdFigure[]; count: number } | null
}

export interface YtdLeaders {
  year: number; prev_year: number; flow: 'import' | 'export'; rows: YtdFigure[]; count: number; is_demo: boolean
}

const MONTHS: Record<Lang, string[]> = {
  it: ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic'],
  en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
}
const MONTHS_LONG: Record<Lang, string[]> = {
  it: ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'],
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
}

/** "gen–set" / "Jan–Sep"; a single month: "gen" / "Jan". */
export function fmtMonthSpan(from: number, to: number, lang: Lang): string {
  const a = MONTHS[lang][from - 1] ?? String(from)
  const b = MONTHS[lang][to - 1] ?? String(to)
  return from === to ? a : `${a}–${b}`
}

/** "2026-08" -> "agosto 2026" / "August 2026" */
export function fmtMonthLong(ym: string | null | undefined, lang: Lang): string {
  const m = ym ? /^(\d{4})-(\d{2})$/.exec(ym) : null
  if (!m) return ym ?? '—'
  return `${MONTHS_LONG[lang][Number(m[2]) - 1]} ${m[1]}`
}

/** "gen–set 2025" — the comparison period (same months of the year before). */
export function prevSpan(f: Pick<YtdFigure, 'month_from' | 'month_to' | 'prev_year'>, lang: Lang): string {
  return `${fmtMonthSpan(f.month_from, f.month_to, lang)} ${f.prev_year}`
}
