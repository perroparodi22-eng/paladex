// Small pieces shared by the simple view's pages.
import clsx from 'clsx'
import { useI18n } from '@/i18n'
import { fmtPct, fmtPeriod, parseBackendDate } from '@/lib/format'
import { vsPeriod } from '@/lib/plain'
import type { Lang } from '@/lib/types'

/** Arrow and signed % in words: "▲ +2,1% in un mese". `pct` + `label` for any other comparison;
 * else the month change, else the year change, else the change against the newest earlier figure
 * of the same series, with its date ("rispetto ad ago 2025"), else "no comparison". The sign is
 * always written, so the direction reads without colour. `currency`: the change is in the source's
 * currency. */
export function Trend({ month, year, earlier, currency, pct, label, className }: {
  month?: number | null; year?: number | null; earlier?: { pct: number | null | undefined; period_label: string | null | undefined } | null
  currency?: string | null; pct?: number | null; label?: string; className?: string
}) {
  const { t, lang } = useI18n()
  const [value, words] = pct !== undefined && pct !== null ? [pct, label ?? '']
    : month !== undefined && month !== null ? [month, t('simple.trend.month')]
    : year !== undefined && year !== null ? [year, t('simple.trend.year')]
    : earlier && earlier.pct != null && earlier.period_label ? [earlier.pct, vsPeriod(earlier.period_label, lang)]
    : [null, '']
  if (value === null) return <span className={clsx('text-muted', className)}>{t('simple.trend.none')}</span>
  const up = value > 0.05
  const down = value < -0.05
  return (
    <span className={clsx(up ? 'text-up' : down ? 'text-down' : 'text-muted', className)} data-trend={up ? 'up' : down ? 'down' : 'flat'}>
      <span className="whitespace-nowrap">
        <span aria-hidden className="text-[0.8em]">{up ? '▲' : down ? '▼' : '■'}</span>{' '}
        <span className="tabular-nums font-medium">{fmtPct(value, lang)}</span>
      </span> {words}
      {currency && <span className="text-muted"> ({t('simple.trend.in', { cur: currency })})</span>}
    </span>
  )
}

export interface Missing { period_label: string; source_has_period: boolean | null }

/** Why a comparison is missing, in a few words: "nessun dato della fonte per ago 2026" when the
 * source published nothing for that period, "nessun dato per ago 2026" when it published other
 * figures but not this one; nothing when it is not known. Two gaps of the source read as one line. */
export function useGapNote() {
  const { t, lang } = useI18n()
  return (...items: (Missing | null | undefined)[]): string | null => {
    const known = items.filter((m): m is Missing => Boolean(m) && m!.source_has_period !== null)
    if (!known.length) return null
    const source = known.filter((m) => m.source_has_period === false).map((m) => fmtPeriod(m.period_label, lang))
    const figure = known.filter((m) => m.source_has_period === true).map((m) => fmtPeriod(m.period_label, lang))
    const and = (xs: string[]) => xs.join(lang === 'it' ? ' e ' : ' and ')
    return [
      source.length ? t('simple.gap.source', { p: and(source) }) : null,
      figure.length ? t('simple.gap.figure', { p: and(figure) }) : null,
    ].filter(Boolean).join('; ')
  }
}

const DAY = 86_400_000

/** A figure whose period ended long ago for its rhythm (monthly or weekly over 4 months, quarterly
 * over 7, annual over 2 years): shown with its date and "non recente", never as current. */
export function isOldPeriod(periodEnd: string | null | undefined, frequency: string | null | undefined, today: string): boolean {
  if (!periodEnd) return false
  const end = parseBackendDate(periodEnd).getTime()
  const now = parseBackendDate(today).getTime()
  if (Number.isNaN(end) || Number.isNaN(now)) return false
  const f = (frequency ?? 'M').toUpperCase()
  const maxDays = f === 'A' ? 730 : f === 'Q' ? 210 : 120
  return now - end > maxDays * DAY
}

/** "settembre" / "September" */
export function monthName(m: number, lang: Lang): string {
  return new Intl.DateTimeFormat(lang === 'it' ? 'it-IT' : 'en-GB', { month: 'long' }).format(new Date(2026, m - 1, 15))
}
