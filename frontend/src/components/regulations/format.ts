// Formatting for duty layers. Numbers are shown in the reader's locale, but only when the backend
// could reduce the published expression to them; otherwise the published text is shown as is.
import { fmtNumber, fmtTonnes } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type { DutyRow } from './types'

function trimmed(v: number, lang: Lang, max = 2): string {
  const digits = Number.isInteger(v) ? 0 : Math.abs(v * 10 - Math.round(v * 10)) < 1e-9 ? 1 : max
  return fmtNumber(v, lang, digits)
}

function specific(r: DutyRow, lang: Lang): string | null {
  if (r.specific_amount === null) return null
  const cur = r.specific_currency ?? ''
  const unit = r.specific_unit === '100kg' ? '100 kg' : r.specific_unit ?? ''
  if (cur === 'USD' && r.specific_unit === 'kg' && r.specific_amount < 1) {
    return `${trimmed(r.specific_amount * 100, lang)} ¢/kg`
  }
  return `${trimmed(r.specific_amount, lang)} ${cur}/${unit}`
}

/** "17,3 %", "1,9 ¢/kg", "0 % + 10 EUR/100 kg", "Free"/"Esente", or the published text. */
export function fmtDuty(r: DutyRow, lang: Lang, freeLabel: string): string {
  const complex = r.ad_valorem_pct === null && r.specific_amount === null
  if (complex) return r.duty_text ?? '—'
  if (r.duty_text && /^\s*free\s*$/i.test(r.duty_text)) return freeLabel
  const parts: string[] = []
  if (r.ad_valorem_pct !== null) parts.push(`${trimmed(r.ad_valorem_pct, lang)} %`)
  const s = specific(r, lang)
  if (s) parts.push(s)
  const text = parts.join(' + ')
  const additional = r.jurisdiction === 'US' && (r.measure_type === 'surcharge' || r.measure_type === 'other')
  return additional ? `+ ${text}` : text
}

export function fmtKg(kg: number | null | undefined, lang: Lang): string {
  return fmtTonnes(kg ?? null, lang)
}

/** Legal act / heading label shown on the link. */
export function legalLabel(r: DutyRow): string | null {
  const first = r.legal_reference?.split(';')[0]?.trim() || null
  // US references read "HTSUS 0409.00.00, column 1 general": the link shows the HTS number only.
  return first && r.jurisdiction === 'US' ? first.split(',')[0].trim() : first
}

export function fmtPct(v: number | null | undefined, lang: Lang): string {
  if (v === null || v === undefined) return '—'
  return `${fmtNumber(v, lang, v >= 10 || Number.isInteger(v) ? 0 : 1)} %`
}

export const isChapter99 = (r: DutyRow) => r.jurisdiction === 'US' && /^99\d\d\.\d\d\.\d\d$/.test(r.measure_code ?? '')
