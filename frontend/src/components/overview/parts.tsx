// Small building blocks shared by the overview panels.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowRight, CircleSlash, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtAgo, fmtDate, fmtPct } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type { Provider } from './types'

/** "07:42" in the user's language. Timestamps from the backend are naive UTC. */
export function fmtClock(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return '—'
  const s = /Z|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return '—'
  return new Intl.DateTimeFormat(lang === 'it' ? 'it-IT' : 'en-GB', { hour: '2-digit', minute: '2-digit' }).format(d)
}

/** "Lunedì 2 novembre 2026" */
export function fmtLongDate(isoDate: string | null | undefined, lang: Lang): string {
  const d = isoDate ? new Date(`${isoDate}T12:00:00`) : new Date()
  const s = new Intl.DateTimeFormat(lang === 'it' ? 'it-IT' : 'en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  }).format(d)
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** Starts a collection (same endpoint as the top-bar button); the shell refreshes every view when it ends. */
export function useCollectNow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post('/collect', {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['collect-status'] }),
  })
}

export function RefreshButton({ running, variant = 'primary' }: { running?: boolean; variant?: 'primary' | 'secondary' }) {
  const { t } = useI18n()
  const collect = useCollectNow()
  const busy = running || collect.isPending
  return (
    <button
      className={clsx(variant === 'primary' ? 'btn-primary' : 'btn-secondary', '!py-1.5')}
      onClick={() => collect.mutate()}
      disabled={busy}
    >
      <RefreshCw size={15} className={clsx(busy && 'animate-spin')} />
      {busy ? t('overview.refreshing') : t('overview.refresh')}
    </button>
  )
}

export function SectionLink({ to, label, className }: { to: string; label?: string; className?: string }) {
  const { t } = useI18n()
  return (
    <Link to={to} className={clsx('inline-flex items-center gap-1 text-sm text-forest-700 hover:text-forest-900 whitespace-nowrap', className)}>
      {label ?? t('overview.viewAll')} <ArrowRight size={14} />
    </Link>
  )
}

const MAX_PROVIDER_NAMES = 3

/** Honest empty state for one block: what will appear here and which source will provide it. */
export function BlockEmpty({ what, providers, fallbackSources, extra, compact = false }: {
  what: string; providers: Provider[]; fallbackSources: string; extra?: ReactNode; compact?: boolean
}) {
  const { t } = useI18n()
  // Short publisher names ("Apimondia (International Federation…)" -> "Apimondia"), de-duplicated.
  const names = Array.from(new Set(providers.filter((p) => p.enabled)
    .map((p) => (p.publisher || p.name).replace(/\s*\(.*?\)/g, '').split(',')[0].trim())))
  const max = compact ? 2 : MAX_PROVIDER_NAMES
  const shown = names.slice(0, max).join(', ')
  const sources = !names.length ? fallbackSources
    : names.length > max ? t(names.length - max === 1 ? 'overview.andOne' : 'overview.andMore', { list: shown, n: names.length - max }) : shown
  return (
    <div className={clsx('flex items-start gap-3', compact ? 'py-1' : 'py-2')}>
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border border-line-soft bg-paper text-gold">
        <CircleSlash size={16} />
      </div>
      <div className="min-w-0 text-[0.92rem] leading-snug">
        <div className="font-serif text-[1.05rem] text-charcoal-soft">{t('overview.noData')}</div>
        <p className="mt-0.5 text-muted">{what}</p>
        <p className="mt-1 text-muted">
          <span className="text-charcoal-soft">{t('overview.expectedFrom', { sources })}</span>{!compact && <> {t('overview.refreshHint')}</>}
        </p>
        {extra && <div className="mt-2">{extra}</div>}
      </div>
    </div>
  )
}

/** Footer line telling when the data in a block arrived and was last published. */
export function BlockStamp({ updatedAt, publishedAt, children, className }: {
  updatedAt: string | null | undefined; publishedAt?: string | null; children?: ReactNode; className?: string
}) {
  const { t, lang } = useI18n()
  return (
    <div className={clsx('flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8rem] text-muted', className)}>
      {children}
      {updatedAt ? (
        <span>
          {t('overview.updatedAgo', { ago: fmtAgo(updatedAt, lang) })}
          {publishedAt && <> · {t('overview.publishedOn', { date: fmtDate(publishedAt, lang) })}</>}
        </span>
      ) : (
        <span>{t('overview.notYet')}</span>
      )}
    </div>
  )
}

/** Signed % change with direction colour and arrow (text stays readable without colour). */
export function Delta({ value, suffix, title, className }: { value: number | null | undefined; suffix?: string; title?: string; className?: string }) {
  const { lang } = useI18n()
  if (value === null || value === undefined) {
    return <span className={clsx('num text-muted', className)} title={title}>— {suffix}</span>
  }
  const tone = value > 0.05 ? 'text-up' : value < -0.05 ? 'text-down' : 'text-muted'
  const arrow = value > 0.05 ? '▲' : value < -0.05 ? '▼' : '■'
  return (
    <span className={clsx('num whitespace-nowrap', tone, className)} title={title}>
      <span className="text-[0.7em] align-[0.08em]">{arrow}</span> {fmtPct(value, lang)}{suffix ? <span className="text-muted"> {suffix}</span> : null}
    </span>
  )
}

/** Panel header with an eyebrow, a serif title and optional right-hand content. */
export function BlockHead({ eyebrow, title, right, sub }: { eyebrow: string; title: ReactNode; right?: ReactNode; sub?: ReactNode }) {
  return (
    <div className="border-b border-line-soft px-5 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="eyebrow">{eyebrow}</div>
          <h2 className="panel-title leading-snug">{title}</h2>
        </div>
        {right && <div className="flex shrink-0 items-center gap-2 pt-0.5">{right}</div>}
      </div>
      {sub && <div className="mt-0.5 text-[0.82rem] text-muted">{sub}</div>}
    </div>
  )
}
