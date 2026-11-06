// How a corrected figure's values read: "1,77 USD/lb", "40.000 t", "69.298 t", "12,3 milioni USD".
import { fmtNumber } from '@/lib/format'
import type { Lang } from '@/lib/types'

export function fmtFigureValue(v: number | null | undefined, unit: string | null | undefined, currency: string | null | undefined, lang: Lang): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  // trade quantities are stored in kilograms: tonnes read better
  if (unit === 'kg' && !currency && Math.abs(v) >= 10_000) return `${fmtNumber(v / 1000, lang, 0)} t`
  // prices keep their published precision (USDA: 1,775 USD/lb), never rounded into another figure
  const digits = Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 100 ? 1 : Math.abs(v * 100 - Math.round(v * 100)) > 1e-6 ? 3 : 2
  const num = fmtNumber(v, lang, digits)
  if (currency && unit) return `${num} ${currency}/${unit}`
  if (currency) return `${num} ${currency}`
  if (unit) return `${num} ${unit}`
  return num
}

/** A number as a person types it in the interface language ("1,8" in Italian). */
export function typedNumber(v: number | string | null | undefined, lang: Lang): string {
  if (v === null || v === undefined || v === '') return ''
  const s = String(v)
  return lang === 'it' ? s.replace('.', ',') : s
}

/** Units a person may type a price in (the backend converts them to the figure's own unit). */
export const PRICE_UNITS = ['kg', 'lb', 't']
export const CURRENCIES = ['EUR', 'USD']
