// Design-system primitives. Keep pages consistent: Panel, PageHeader, Badge, StatTile,
// SourceLine (provenance), FreshnessBadge, EmptyState, Loading/Error, Select, Segmented.
import clsx from 'clsx'
import { AlertTriangle, ExternalLink, Info, Loader2, Sparkles } from 'lucide-react'
import type { ReactNode, SelectHTMLAttributes } from 'react'
import { useI18n } from '@/i18n'
import { fmtAgo, fmtDate, fmtNumber, fmtPeriod } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { isMirrorMissing } from '@/lib/mirror'
import type { FreshnessStatus, Provenance } from '@/lib/types'

export function PageHeader({ title, subtitle, eyebrow, actions }: { title: string; subtitle?: ReactNode; eyebrow?: string; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4 mb-6">
      <div>
        {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
        <h1 className="text-[2rem] leading-tight font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 text-muted max-w-3xl">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

export function Panel({ title, eyebrow, actions, children, className, bodyClassName, footer }: {
  title?: ReactNode; eyebrow?: string; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string; footer?: ReactNode
}) {
  return (
    <section className={clsx('panel', className)}>
      {(title || actions) && (
        <div className="panel-head">
          <div>
            {eyebrow && <div className="eyebrow">{eyebrow}</div>}
            {title && <h2 className="panel-title">{title}</h2>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={clsx('p-5', bodyClassName)}>{children}</div>
      {footer && <div className="px-5 py-2.5 border-t border-line-soft text-sm text-muted">{footer}</div>}
    </section>
  )
}

type Tone = 'neutral' | 'forest' | 'gold' | 'up' | 'down' | 'warn' | 'demo' | 'ai' | 'outline'

const TONES: Record<Tone, string> = {
  neutral: 'bg-ivory text-charcoal-soft border-line',
  forest: 'bg-forest-50 text-forest-800 border-forest-100',
  gold: 'bg-gold-pale text-gold-dark border-gold-light/50',
  up: 'bg-[#E6F2EA] text-up border-[#CBE4D4]',
  down: 'bg-[#F7E7E3] text-down border-[#EBCDC6]',
  warn: 'bg-[#FBF0DC] text-warn border-[#EED9B0]',
  demo: 'bg-[#FDE8E4] text-[#9A2A17] border-[#E9B4A8] font-semibold tracking-wide',
  ai: 'bg-[#EEEAF6] text-[#4B3F7A] border-[#D7D0EA]',
  outline: 'bg-transparent text-muted border-line',
}

export function Badge({ children, tone = 'neutral', title, className }: { children: ReactNode; tone?: Tone; title?: string; className?: string }) {
  return (
    <span title={title} className={clsx('inline-flex items-center gap-1 whitespace-nowrap border rounded-sm px-1.5 py-0.5 text-[0.72rem] leading-none uppercase tracking-wide', TONES[tone], className)}>
      {children}
    </span>
  )
}

export function DemoBadge() {
  const { t } = useI18n()
  return <Badge tone="demo" title={t('ui.demo')}>{t('ui.demo')}</Badge>
}

export function AiBadge({ label }: { label?: string }) {
  const { t } = useI18n()
  return (
    <Badge tone="ai" title={t('ui.aiGenerated')}>
      <Sparkles size={11} /> {label ?? t('ui.ai')}
    </Badge>
  )
}

/** Data-status badge: published / provisional / estimate / forecast / AI / demo. */
export function StatusBadge({ status }: { status: string }) {
  const { dataStatus } = useLabels()
  const tone: Tone = status === 'demo' ? 'demo' : status === 'ai_assessment' ? 'ai'
    : status === 'estimate' || status === 'forecast' || status === 'provisional' ? 'warn' : 'forest'
  return <Badge tone={tone}>{dataStatus(status)}</Badge>
}

export function ReliabilityBadge({ reliability }: { reliability: string }) {
  const { reliability: label } = useLabels()
  const tone: Tone = reliability === 'official' ? 'forest' : reliability === 'industry' ? 'gold' : reliability === 'demo' ? 'demo' : 'outline'
  return <Badge tone={tone}>{label(reliability)}</Badge>
}

export function FreshnessBadge({ status, ageDays }: { status: FreshnessStatus; ageDays?: number | null }) {
  const { t } = useI18n()
  const tone: Tone = status === 'current' ? 'up' : status === 'aging' ? 'warn' : status === 'stale' ? 'down' : 'outline'
  return (
    <Badge tone={tone} title={ageDays != null ? t('fresh.ageDays', { n: ageDays }) : undefined}>
      <span className={clsx('inline-block h-1.5 w-1.5 rounded-full', {
        'bg-up': status === 'current', 'bg-warn': status === 'aging', 'bg-down': status === 'stale', 'bg-muted': status === 'never' || status === 'unknown',
      })} />
      {t(`fresh.${status}`)}
    </Badge>
  )
}

/** One-line provenance: "Fonte: USDA AMS · Periodo: set 2026 · Pubblicato 15 ott 2026 · Raccolto 2 ore fa · [doc]" */
export function SourceLine({ p, compact = false, className }: { p: Partial<Provenance>; compact?: boolean; className?: string }) {
  const { t, lang } = useI18n()
  return (
    <div className={clsx('flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8rem] text-muted', className)}>
      {p.is_demo && <DemoBadge />}
      {p.source && (
        <span>
          {t('prov.source')}: <span className="text-charcoal-soft font-medium">{p.source.publisher || p.source.name}</span>
        </span>
      )}
      {p.period_label && !compact && <span>· {t('prov.period')}: {fmtPeriod(p.period_label, lang)}</span>}
      {p.published_at && <span>· {t('prov.published')} {fmtDate(p.published_at, lang)}</span>}
      {p.collected_at && !compact && <span>· {t('prov.collected')} {fmtAgo(p.collected_at, lang)}</span>}
      {p.source_url && (
        <a href={p.source_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">
          {t('prov.original')} <ExternalLink size={12} />
        </a>
      )}
    </div>
  )
}

export function StatTile({ label, value, sub, delta, deltaLabel, footer, demo }: {
  label: string; value: ReactNode; sub?: ReactNode; delta?: number | null; deltaLabel?: string; footer?: ReactNode; demo?: boolean
}) {
  const { lang } = useI18n()
  return (
    <div className="panel p-4 flex flex-col gap-1 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span className="eyebrow truncate">{label}</span>
        {demo && <DemoBadge />}
      </div>
      <div className="num text-[1.7rem] leading-tight text-charcoal">{value}</div>
      {sub && <div className="text-sm text-muted">{sub}</div>}
      {delta !== undefined && delta !== null && (
        <div className={clsx('num text-sm', delta > 0 ? 'text-up' : delta < 0 ? 'text-down' : 'text-muted')}>
          {delta > 0 ? '▲' : delta < 0 ? '▼' : '■'} {fmtNumber(Math.abs(delta), lang, 1)}% {deltaLabel}
        </div>
      )}
      {footer && <div className="mt-1 pt-2 border-t border-line-soft">{footer}</div>}
    </div>
  )
}

export function EmptyState({ title, hint, action, icon }: { title?: string; hint?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  const { t } = useI18n()
  return (
    <div className="flex flex-col items-center justify-center text-center py-10 px-6 text-muted">
      <div className="mb-2 text-gold">{icon ?? <Info size={22} />}</div>
      <div className="font-serif text-lg text-charcoal-soft">{title ?? t('ui.noData')}</div>
      <div className="mt-1 max-w-md text-sm">{hint ?? t('ui.noDataHint')}</div>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Loading({ label }: { label?: string }) {
  const { t } = useI18n()
  return (
    <div className="flex items-center gap-2 py-8 justify-center text-muted">
      <Loader2 className="animate-spin" size={18} /> {label ?? t('ui.loading')}
    </div>
  )
}

export function ErrorBlock({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n()
  // Read-only online copy: a view it does not contain is not an error (lib/mirror.ts).
  if (isMirrorMissing(error)) {
    return (
      <div className="flex items-start gap-3 p-4 border border-forest-100 bg-forest-50 rounded-sm text-sm" role="status">
        <Info size={18} className="text-forest-700 mt-0.5 shrink-0" />
        <div className="flex-1">
          <div className="font-medium text-forest-800">{t('mirror.missingTitle')}</div>
          <div className="text-charcoal-soft mt-0.5">{t('mirror.missing')}</div>
        </div>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-3 p-4 border border-[#EBCDC6] bg-[#FBF1EE] rounded-sm text-sm">
      <AlertTriangle size={18} className="text-down mt-0.5 shrink-0" />
      <div className="flex-1">
        <div className="font-medium text-down">{t('ui.error')}</div>
        <div className="text-muted mt-0.5">{error instanceof Error ? error.message : String(error)}</div>
      </div>
      {onRetry && <button className="btn-secondary !py-1" onClick={onRetry}>{t('ui.retry')}</button>}
    </div>
  )
}

/** Wraps a react-query result: loading / error / content. */
export function QueryState<T>({ q, children, empty }: {
  q: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown }
  children: (data: T) => ReactNode
  empty?: (data: T) => boolean
}) {
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
  if (q.data === undefined) return null
  if (empty && empty(q.data)) return <EmptyState />
  return <>{children(q.data)}</>
}

export function Select({ label, className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <label className={clsx('block', className)}>
      {label && <span className="label">{label}</span>}
      <select {...rest} className="field pr-8">{children}</select>
    </label>
  )
}

export function Segmented<T extends string>({ value, onChange, options, size = 'md' }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; size?: 'sm' | 'md'
}) {
  return (
    // max-w-full + overflow-x-auto: on a phone a long row of options scrolls inside itself.
    <div className="inline-flex max-w-full border border-line rounded-sm bg-white overflow-x-auto" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={clsx(
            'border-r last:border-r-0 border-line transition-colors',
            size === 'sm' ? 'px-2.5 py-1 text-sm' : 'px-3.5 py-1.5 text-[0.95rem]',
            o.value === value ? 'bg-forest-800 text-ivory' : 'text-charcoal-soft hover:bg-forest-50',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Explains that a section belongs to a later milestone — honest, never fake content. */
export function ComingSoon({ title, milestone, description }: { title: string; milestone: number; description: string }) {
  const { t } = useI18n()
  return (
    <div>
      <PageHeader title={title} eyebrow={`${t('ui.comingSoon')} · Milestone ${milestone}`} />
      <Panel>
        <EmptyState title={t('ui.comingSoon')} hint={description} />
      </Panel>
    </div>
  )
}

/** A short explanatory note for non-technical users. */
export function Note({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warn' }) {
  return (
    <div className={clsx('flex items-start gap-2 text-sm rounded-sm border px-3 py-2',
      tone === 'warn' ? 'border-[#EED9B0] bg-[#FBF5E8] text-[#7A5414]' : 'border-forest-100 bg-forest-50 text-forest-800')}>
      {tone === 'warn' ? <AlertTriangle size={16} className="mt-0.5 shrink-0" /> : <Info size={16} className="mt-0.5 shrink-0" />}
      <div>{children}</div>
    </div>
  )
}
