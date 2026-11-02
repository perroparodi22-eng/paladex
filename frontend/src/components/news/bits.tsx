// Small building blocks shared by the news components.
import clsx from 'clsx'
import type { ReactNode } from 'react'
import { useI18n } from '@/i18n'
import { fmtAgo, fmtDate, fmtDateTime } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type { NewsItem, RelevanceLevel } from './types'

/** The backend stores naive UTC timestamps: mark them as UTC so the browser shows local time. */
export function utc(iso: string | null | undefined): string | null {
  if (!iso) return null
  if (iso.length === 10 || iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso)) return iso
  return `${iso}Z`
}

/** "2 nov 2026" for older items, "3 ore fa" for the last 24 hours. */
export function fmtNewsDate(iso: string | null | undefined, lang: Lang): string {
  const s = utc(iso)
  if (!s) return '—'
  const age = Date.now() - new Date(s).getTime()
  if (age >= 0 && age < 24 * 3600 * 1000) return fmtAgo(s, lang)
  return fmtDate(s, lang)
}

export function fmtNewsDateTime(iso: string | null | undefined, lang: Lang): string {
  return fmtDateTime(utc(iso), lang)
}

/** Article language as a word ("inglese"), or null when the code is unknown. */
export function useLangName() {
  const { t } = useI18n()
  return (code: string | null | undefined, capitalised = false): string => {
    if (!code) return t('news.lang.unknown')
    const k = code.slice(0, 2).toLowerCase()
    const key = `news.${capitalised ? 'langName' : 'lang'}.${k}`
    const v = t(key)
    return v === key ? code.toUpperCase() : v
  }
}

const LEVEL_BARS: Record<RelevanceLevel, number> = { high: 3, medium: 2, low: 1 }

/** Three-step relevance meter with a hover/focus card that explains the score. */
export function RelevanceMeter({ item }: { item: NewsItem }) {
  const { t, lang } = useI18n()
  const level = item.relevance_level
  const reason = lang === 'it' ? item.relevance_reason_it : item.relevance_reason_en
  const filled = LEVEL_BARS[level] ?? 1
  const label = t(`news.rel.${level}`)
  return (
    <div className="group relative shrink-0">
      <button
        type="button"
        className="flex items-center gap-2 rounded-sm px-1.5 py-1 -mx-1.5 -my-1 text-[0.82rem] text-charcoal-soft hover:bg-paper focus:bg-paper"
        aria-label={`${label}. ${reason ?? ''} ${t('news.rel.score', { n: item.relevance_score })}`}
      >
        <span className="flex items-end gap-[3px]" aria-hidden>
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className={clsx(
                'w-[5px] rounded-[1px]',
                i === 0 ? 'h-[7px]' : i === 1 ? 'h-[11px]' : 'h-[15px]',
                i < filled
                  ? level === 'high' ? 'bg-forest-700' : level === 'medium' ? 'bg-gold' : 'bg-muted/60'
                  : 'bg-line',
              )}
            />
          ))}
        </span>
        <span className={clsx('whitespace-nowrap', level === 'high' && 'font-medium text-forest-800')}>{label}</span>
      </button>
      <div
        role="tooltip"
        className="invisible opacity-0 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100 transition-opacity
          absolute right-0 top-full z-20 mt-2 w-[19rem] rounded-sm border border-line bg-white p-3.5 text-left shadow-[0_6px_24px_rgba(31,33,32,0.12)]"
      >
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-serif text-[1rem] font-semibold text-charcoal">{label}</span>
          <span className="num text-[0.82rem] text-muted">{t('news.rel.score', { n: item.relevance_score })}</span>
        </div>
        {reason && (
          <div className="mt-2 text-[0.86rem] leading-snug text-charcoal-soft">
            <span className="eyebrow mr-1">{t('news.rel.why')}</span>
            <ul className="mt-1 space-y-0.5">
              {reason.split(' · ').map((r) => <li key={r} className="flex gap-1.5"><span className="text-gold">·</span><span>{r}</span></li>)}
            </ul>
          </div>
        )}
        <div className="mt-2.5 border-t border-line-soft pt-2 text-[0.78rem] text-muted">{t('news.rel.rules')}</div>
      </div>
    </div>
  )
}

/** Clickable tag on a card (country / topic) that narrows the list. */
export function TagButton({ children, onClick, title, tone, active }: {
  children: ReactNode; onClick: () => void; title: string; tone: 'country' | 'topic'; active?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={clsx(
        'inline-flex items-center rounded-sm border px-2 py-[3px] text-[0.8rem] leading-tight transition-colors',
        tone === 'country'
          ? active ? 'border-forest-700 bg-forest-800 text-ivory' : 'border-forest-100 bg-forest-50 text-forest-800 hover:border-forest-500'
          : active ? 'border-gold-dark bg-gold-pale text-gold-dark' : 'border-line bg-white text-charcoal-soft hover:border-gold hover:text-gold-dark',
      )}
    >
      {children}
    </button>
  )
}

/** Filter chip in the filter bar (with an optional count). */
export function FilterChip({ active, onClick, children, count, title, dim }: {
  active: boolean; onClick: () => void; children: ReactNode; count?: number; title?: string; dim?: boolean
}) {
  return (
    <button
      type="button"
      title={title}
      aria-pressed={active}
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-1 text-[0.92rem] leading-tight transition-colors',
        active ? 'border-forest-700 bg-forest-800 text-ivory'
          : dim ? 'border-line-soft bg-paper text-muted hover:border-forest-300 hover:text-charcoal-soft'
            : 'border-line bg-white text-charcoal-soft hover:border-forest-600 hover:text-forest-800',
      )}
    >
      <span>{children}</span>
      {count !== undefined && (
        <span className={clsx('num text-[0.76rem]', active ? 'text-gold-light' : 'text-muted')}>{count}</span>
      )}
    </button>
  )
}

/** Accessible on/off switch with a label. */
export function Switch({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      title={hint}
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2.5 text-left text-[0.95rem] text-charcoal-soft"
    >
      <span className={clsx('relative inline-flex h-[22px] w-[40px] shrink-0 items-center rounded-full border transition-colors',
        checked ? 'border-forest-800 bg-forest-800' : 'border-line bg-ivory-deep')}>
        <span className={clsx('inline-block h-[16px] w-[16px] rounded-full bg-white shadow-sm transition-transform',
          checked ? 'translate-x-[20px]' : 'translate-x-[2px]')} />
      </span>
      <span className={clsx(checked && 'text-charcoal font-medium')}>{label}</span>
    </button>
  )
}

/** Labelled control group used in the filter bar. */
export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={clsx('flex flex-col gap-1.5 min-w-0', className)}>
      <span className="text-[0.76rem] font-medium uppercase tracking-[0.1em] text-muted">{label}</span>
      {children}
    </div>
  )
}
