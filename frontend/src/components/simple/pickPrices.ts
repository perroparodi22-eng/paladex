// Simple view of /prezzi: which ONE series stands for each main origin in the short table of a
// price type. Never mixes price types (one table per type); every row names its own market and
// carries its source chip; old figures are listed by name and date only, never as current.
import type { LatestRow } from '@/components/prices/types'
import { isOldPeriod } from './bits'

/** The origins a bulk-honey importer in Italy and the US follows first (the rest is in the full view). */
export const MAIN_ORIGINS = ['ARG', 'UKR', 'CHN', 'BRA', 'VNM', 'IND', 'MEX', 'URY', 'HUN', 'ITA', 'USA']
/** At most this many rows per table. */
export const MAX_ROWS = 6

/** Where a price is observed, in order of interest for an importer selling in Italy and the US. */
const MARKET_ORDER: Record<string, string[]> = {
  wholesale_bulk: ['USA', 'ITA'],
  import_unit_value: ['EU27', 'USA', 'ITA', 'DEU', 'GBR', 'ESP', 'FRA', 'BEL', 'NLD'],
  export_unit_value: ['ITA', 'EU27', 'USA', 'DEU', 'ESP', 'FRA', 'GBR', 'BEL', 'NLD', 'JPN'],
  producer: [],
}
const VARIETY_ORDER = ['polyflora', 'unspecified', 'acacia', 'sunflower', 'clover', 'orange_blossom', 'chestnut',
  'eucalyptus', 'linden', 'rapeseed', 'honeydew', 'buckwheat', 'lavender', 'dandelion', 'other']
const COLOR_ORDER = [null, 'white', 'extra light amber', 'light amber', 'amber', 'extra white', 'water white', 'dark amber', 'dark']
const FREQ_ORDER = ['M', 'Q', 'A']

const rank = <T,>(list: T[], v: T) => {
  const i = list.indexOf(v)
  return i < 0 ? list.length : i
}

export function rowIsOld(r: Pick<LatestRow, 'latest' | 'freq' | 'freshness'>, today: string): boolean {
  return r.freshness?.status === 'stale' || isOldPeriod(r.latest?.period_end, r.freq, today)
}

/** Packaging preference for wholesale lists: drums first, then lists that do not say, then buckets. */
function termsRank(terms: string | null): number {
  const s = (terms ?? '').toLowerCase()
  if (/media annua|annual average/.test(s)) return 3
  if (/\bfust[oi]\b|bulk honey|drum/.test(s)) return 0
  if (/secchi/.test(s)) return 2
  return 1
}

function sortKey(r: LatestRow, today: string): (number | string)[] {
  const comparisons = Number(r.previous?.value != null && r.freq === 'M') + Number(r.year_ago?.value != null)
  const market = r.price_type === 'producer' || r.market_iso3 === r.origin_iso3 ? -1 : rank(MARKET_ORDER[r.price_type] ?? [], r.market_iso3 ?? '')
  return [
    Number(rowIsOld(r, today)),
    Number(r.is_demo),                         // real figures before demonstration ones (when shown)
    rank(FREQ_ORDER, r.freq),
    Number(r.latest?.value == null),           // a value in the chosen currency first
    -comparisons,
    market,
    Number(r.organic),
    rank(VARIETY_ORDER, r.variety),
    rank(COLOR_ORDER, r.color_grade ? r.color_grade.toLowerCase() : null),
    termsRank(r.terms),
    r.reliability === 'official' ? 0 : 1,
    // newer first: invert the period label character by character
    [...(r.period_label ?? '')].map((c) => String.fromCharCode(0xffff - c.charCodeAt(0))).join(''),
  ]
}

function cmp(a: (number | string)[], b: (number | string)[]): number {
  for (let i = 0; i < a.length; i++) {
    if (a[i] < b[i]) return -1
    if (a[i] > b[i]) return 1
  }
  return 0
}

export interface PickedPrices {
  /** one current row per main origin, in MAIN_ORIGINS order, at most MAX_ROWS */
  rows: LatestRow[]
  /** main origins whose newest figure for this type is old: named with its period only */
  old: LatestRow[]
}

export function pickPriceRows(all: LatestRow[], today: string, origins = MAIN_ORIGINS, max = MAX_ROWS): PickedPrices {
  const rows: LatestRow[] = []
  const old: LatestRow[] = []
  for (const iso3 of origins) {
    const cands = all.filter((r) => r.origin_iso3 === iso3)
    if (!cands.length) continue
    const best = [...cands].sort((a, b) => cmp(sortKey(a, today), sortKey(b, today)))[0]
    if (rowIsOld(best, today)) old.push(best)
    else if (rows.length < max) rows.push(best)
  }
  return { rows, old }
}
