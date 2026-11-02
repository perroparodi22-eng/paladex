// Small building blocks shared by the trade page and the country profile.
import clsx from 'clsx'
import { Info } from 'lucide-react'
import type { ReactNode } from 'react'
import { FreshnessBadge, SourceLine } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtNumber, fmtPct } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type { Names, Provider, SourceUsed, TradeFigures } from './types'

/** Categorical colours for one line per source (validated: CVD-safe, ≥3:1 on white). */
export const SERIES_COLORS = ['#1F7A57', '#B0832A', '#3F6DB0', '#B4532F']

export const AXIS_TICK = { fontSize: 13, fill: '#6B6A62' }
export const AXIS_TICK_MONO = { fontSize: 13, fill: '#6B6A62', fontFamily: '"IBM Plex Mono", monospace' }
export const GRID_STROKE = '#ECE6D6'

export function nameOf(n: Partial<Names> & { iso3?: string }, lang: Lang, fallback?: (iso3: string) => string): string {
  const v = lang === 'it' ? n.name_it ?? n.name_en : n.name_en ?? n.name_it
  if (v) return v
  if (n.iso3 && fallback) return fallback(n.iso3)
  return n.iso3 ?? '—'
}

/** 374 232 591 -> "374,2 Mln $" / "$374.2M" */
export function fmtUsd(v: number | null | undefined, lang: Lang): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat(lang === 'it' ? 'it-IT' : 'en-GB', {
    style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1, currencyDisplay: 'narrowSymbol',
  }).format(v)
}

/** USD in millions, without the unit: 374 232 591 -> "374,2" (column header says "Mln USD"). */
export function fmtUsdM(v: number | null | undefined, lang: Lang): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const m = v / 1e6
  return fmtNumber(m, lang, m < 10 ? 2 : 1)
}

/** Tonnes from kg, without the unit: 61 670 824 kg -> "61.671" */
export function fmtT(kg: number | null | undefined, lang: Lang): string {
  if (kg === null || kg === undefined || Number.isNaN(kg)) return '—'
  const t = kg / 1000
  return fmtNumber(t, lang, t < 10 ? 1 : 0)
}

export function fmtUv(v: number | null | undefined, lang: Lang): string {
  return v === null || v === undefined ? '—' : fmtNumber(v, lang, 2)
}

/** ▲ +7,1% (green) / ▼ −3,2% (red) / — with an explanatory tooltip. */
export function YoY({ pct, title, className }: { pct: number | null | undefined; title?: string; className?: string }) {
  const { lang } = useI18n()
  if (pct === null || pct === undefined) return <span className={clsx('num text-muted', className)} title={title}>—</span>
  return (
    <span title={title} className={clsx('num whitespace-nowrap', pct > 0 ? 'text-up' : pct < 0 ? 'text-down' : 'text-muted', className)}>
      <span className="text-[0.68rem] mr-0.5 align-[1px]">{pct > 0 ? '▲' : pct < 0 ? '▼' : '■'}</span>
      {fmtPct(pct, lang, 1)}
    </span>
  )
}

/** Small marks telling how a total was built: Σ (sum of partners), 12 m (sum of months). */
export function BasisMarks({ summedPartners, partners, summedMonths, fxMissing }: {
  summedPartners?: boolean; partners?: number | null; summedMonths?: boolean; fxMissing?: boolean
}) {
  const { t } = useI18n()
  return (
    <>
      {summedPartners && (
        <span title={t('trade.basis.partnersTitle', { n: partners ?? '?' })}
          className="ml-1.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-sm border border-gold-light/60 bg-gold-pale px-1 text-[0.72rem] font-semibold text-gold-dark cursor-help">
          {t('trade.basis.partners')}
        </span>
      )}
      {summedMonths && (
        <span title={t('trade.basis.monthsTitle')}
          className="ml-1.5 inline-flex h-[18px] items-center rounded-sm border border-line px-1 text-[0.68rem] text-muted cursor-help num">
          {t('trade.basis.months')}
        </span>
      )}
      {fxMissing && <span title={t('trade.basis.fxMissing')} className="ml-1 text-warn cursor-help">*</span>}
    </>
  )
}

/** Thin proportional bar used for shares and in-table magnitudes. */
export function ShareBar({ pct, tone = 'gold', className }: { pct: number | null | undefined; tone?: 'gold' | 'forest'; className?: string }) {
  const w = Math.max(0, Math.min(100, pct ?? 0))
  return (
    <div className={clsx('h-[5px] rounded-full bg-forest-50', className)}>
      <div className={clsx('h-[5px] rounded-full', tone === 'gold' ? 'bg-gold-light' : 'bg-forest-500')} style={{ width: `${Math.max(w > 0 ? 1.5 : 0, w)}%` }} />
    </div>
  )
}

/** Short, de-duplicated source names ("UN Comtrade — commercio…" -> "UN Comtrade"). */
export function providerNames(providers: Provider[], max = 3): { names: string[]; more: number } {
  const short = (p: Provider) => {
    const n = p.name.split(/\s+[—–:·-]\s+|:\s/)[0].trim()
    return n.length > 2 && n.length <= 40 ? n : (p.publisher || p.name).replace(/\s*\(.*?\)/g, '').split(',')[0].trim()
  }
  const names = Array.from(new Set(providers.filter((p) => p.enabled).map(short)))
  return { names: names.slice(0, max), more: Math.max(0, names.length - max) }
}

export function useProviderText() {
  const { t } = useI18n()
  return (providers: Provider[], fallback: string, max = 3) => {
    const { names, more } = providerNames(providers, max)
    if (!names.length) return fallback
    const list = names.join(', ')
    return more ? t(more === 1 ? 'trade.andOne' : 'trade.andMore', { list, n: more }) : list
  }
}

/** Honest empty state: "Dato non disponibile" + which source would provide it. */
export function DataMissing({ title, what, providers, fallback, children, compact = false }: {
  title?: string; what?: ReactNode; providers: Provider[]; fallback: string; children?: ReactNode; compact?: boolean
}) {
  const { t } = useI18n()
  const text = useProviderText()
  return (
    <div className={clsx('flex items-start gap-3 text-muted', compact ? 'py-2' : 'py-6 px-2')}>
      <Info size={compact ? 16 : 20} className="mt-0.5 shrink-0 text-gold" />
      <div className="min-w-0">
        <div className={clsx('font-serif text-charcoal-soft', compact ? 'text-[1rem]' : 'text-lg')}>{title ?? t('ui.noData')}</div>
        {what && <div className="mt-0.5 text-[0.9rem]">{what}</div>}
        <div className="mt-0.5 text-[0.85rem]">{t('trade.expectedFrom', { sources: text(providers, fallback) })}</div>
        {children && <div className="mt-2">{children}</div>}
      </div>
    </div>
  )
}

/** One provenance line per source, with its freshness. */
export function SourcesFooter({ sources, extra }: { sources: SourceUsed[]; extra?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      {sources.map((s) => (
        <div key={s.key} className="flex flex-wrap items-center gap-2">
          <SourceLine p={{ source: s, published_at: s.latest_published_at, is_demo: s.reliability === 'demo' }} />
          {s.freshness && <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />}
        </div>
      ))}
      {extra && <div className="text-[0.8rem] text-muted leading-snug">{extra}</div>}
    </div>
  )
}

/** Volume in tonnes with unit suffix for headline figures. */
export function Tonnes({ kg, className }: { kg: number | null | undefined; className?: string }) {
  const { lang } = useI18n()
  return <span className={clsx('num', className)}>{fmtT(kg, lang)}<span className="text-muted text-[0.8em] ml-1">t</span></span>
}

export function figureTitle(f: TradeFigures, lang: Lang): string {
  const parts: string[] = []
  if (f.value !== null && f.currency) parts.push(`${fmtNumber(f.value, lang, 0)} ${f.currency}${f.value_basis ? ` ${f.value_basis}` : ''}`)
  return parts.join(' · ')
}
