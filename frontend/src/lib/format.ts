import type { Lang } from './types'

const locale = (lang: Lang) => (lang === 'it' ? 'it-IT' : 'en-GB')

// Italian CLDR leaves 4-digit numbers ungrouped ("8775 t" next to "27.605 t" in the same column):
// always group thousands so every figure reads the same way.
const GROUPING = { useGrouping: 'always' } as unknown as Intl.NumberFormatOptions

export function fmtNumber(v: number | null | undefined, lang: Lang, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat(locale(lang), { ...GROUPING, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v)
}

export function fmtMoney(v: number | null | undefined, currency: string, lang: Lang, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  try {
    return new Intl.NumberFormat(locale(lang), { ...GROUPING, style: 'currency', currency, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v)
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

/** Parse backend timestamps. Date-only values ("2026-10-15") are calendar dates (shown as-is);
 * datetimes without a zone are naive UTC (backend convention) and are shown in local time. */
export function parseBackendDate(iso: string): Date {
  if (iso.length === 10) return new Date(`${iso}T12:00:00`)
  const hasZone = iso.endsWith('Z') || /[+-]\d\d:?\d\d$/.test(iso)
  return new Date(hasZone ? iso : `${iso}Z`)
}

export function fmtDate(iso: string | null | undefined, lang: Lang, opts: Intl.DateTimeFormatOptions = { day: '2-digit', month: 'short', year: 'numeric' }): string {
  if (!iso) return '—'
  const d = parseBackendDate(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat(locale(lang), opts).format(d)
}

export function fmtDateTime(iso: string | null | undefined, lang: Lang): string {
  return fmtDate(iso, lang, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** "3 ore fa" / "3 hours ago" for timestamps stored as naive UTC by the backend. */
export function fmtAgo(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return '—'
  const diff = (Date.now() - parseBackendDate(iso).getTime()) / 1000
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
  const q = /^(\d{4})-Q([1-4])$/.exec(label)
  if (q) return lang === 'it' ? `${q[2]}° trim. ${q[1]}` : `Q${q[2]} ${q[1]}`
  const w = /^(\d{4})-W(\d{1,2})$/.exec(label)
  if (w) return lang === 'it' ? `sett. ${Number(w[2])} ${w[1]}` : `week ${Number(w[2])} ${w[1]}`
  // Week of a month (ISMEA): "2026-06-S4" = 4th week of June 2026 (S = settimana).
  const s = /^(\d{4})-(\d{2})-S([1-5])$/.exec(label)
  if (s) {
    const month = fmtDate(`${s[1]}-${s[2]}-15`, lang, { month: 'short', year: 'numeric' })
    return lang === 'it' ? `${s[3]}ª sett. ${month}` : `week ${s[3]} of ${month}`
  }
  return label
}

/** Units of production statistics as stored by the backend ("t", "number", "kg/colony",
 * "1000 BRL") in words a reader understands: "alveari", "kg per alveare", "migliaia di BRL". */
const PROD_UNITS: Record<string, Record<Lang, string>> = {
  t: { it: 't', en: 't' },
  number: { it: 'alveari', en: 'hives' },
  'kg/colony': { it: 'kg per alveare', en: 'kg per hive' },
}

export function fmtProdUnit(unit: string | null | undefined, lang: Lang): string {
  if (!unit) return ''
  const known = PROD_UNITS[unit]
  if (known) return known[lang]
  const thousands = /^1000 ([A-Z]{3})$/.exec(unit)   // IBGE production value: thousand reais
  if (thousands) return lang === 'it' ? `migliaia di ${thousands[1]}` : `thousand ${thousands[1]}`
  return unit
}

export function pctChange(curr: number | null | undefined, prev: number | null | undefined): number | null {
  if (curr === null || curr === undefined || prev === null || prev === undefined || prev === 0) return null
  return ((curr - prev) / prev) * 100
}
