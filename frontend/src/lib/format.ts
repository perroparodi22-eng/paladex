import type { Lang } from './types'

const locale = (lang: Lang) => (lang === 'it' ? 'it-IT' : 'en-GB')

export function fmtNumber(v: number | null | undefined, lang: Lang, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat(locale(lang), { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v)
}

export function fmtMoney(v: number | null | undefined, currency: string, lang: Lang, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  try {
    return new Intl.NumberFormat(locale(lang), { style: 'currency', currency, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v)
  } catch {
    return `${fmtNumber(v, lang, digits)} ${currency}`
  }
}

/** Compact large numbers: 12 400 000 -> "12,4 Mln" / "12.4M" */
export function fmtCompact(v: number | null | undefined, lang: Lang): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat(locale(lang), { notation: 'compact', maximumFractionDigits: 1 }).format(v)
}

export function fmtTonnes(kg: number | null | undefined, lang: Lang): string {
  if (kg === null || kg === undefined) return '—'
  return `${fmtNumber(kg / 1000, lang, kg < 10000 ? 1 : 0)} t`
}

export function fmtPct(v: number | null | undefined, lang: Lang, digits = 1, signed = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const s = fmtNumber(Math.abs(v), lang, digits)
  if (!signed) return `${s}%`
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${s}%`
}

export function fmtDate(iso: string | null | undefined, lang: Lang, opts: Intl.DateTimeFormatOptions = { day: '2-digit', month: 'short', year: 'numeric' }): string {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat(locale(lang), opts).format(d)
}

export function fmtDateTime(iso: string | null | undefined, lang: Lang): string {
  return fmtDate(iso, lang, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** "3 ore fa" / "3 hours ago" for timestamps stored as naive UTC by the backend. */
export function fmtAgo(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return '—'
  const s = iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso.length === 10 ? `${iso}T12:00:00Z` : `${iso}Z`
  const diff = (Date.now() - new Date(s).getTime()) / 1000
  const rtf = new Intl.RelativeTimeFormat(locale(lang), { numeric: 'auto' })
  if (Math.abs(diff) < 60) return rtf.format(-Math.round(diff), 'second')
  if (Math.abs(diff) < 3600) return rtf.format(-Math.round(diff / 60), 'minute')
  if (Math.abs(diff) < 86400) return rtf.format(-Math.round(diff / 3600), 'hour')
  if (Math.abs(diff) < 86400 * 45) return rtf.format(-Math.round(diff / 86400), 'day')
  if (Math.abs(diff) < 86400 * 400) return rtf.format(-Math.round(diff / (86400 * 30)), 'month')
  return rtf.format(-Math.round(diff / (86400 * 365)), 'year')
}

/** Format a period label such as "2026-09" / "2025" / "2026-Q3" for display. */
export function fmtPeriod(label: string | null | undefined, lang: Lang): string {
  if (!label) return '—'
  const m = /^(\d{4})-(\d{2})$/.exec(label)
  if (m) return fmtDate(`${m[1]}-${m[2]}-15`, lang, { month: 'short', year: 'numeric' })
  return label
}

export function pctChange(curr: number | null | undefined, prev: number | null | undefined): number | null {
  if (curr === null || curr === undefined || prev === null || prev === undefined || prev === 0) return null
  return ((curr - prev) / prev) * 100
}
