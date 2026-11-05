// Comparison panel: one horizontal bar per origin (or variety), each bar stating its own period.
// Bars start at zero; a thin whisker marks min–max when a bar averages several series.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Fragment, useState } from 'react'
import { DemoBadge, EmptyState, ErrorBlock, Loading, Panel, Segmented, SourceLine } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { DocLink } from './bits'
import type { CompareResponse, MassUnit } from './types'
import { colorLabel, fmtPeriodLabel, fmtPrice, toUnit, unitLabel } from './utils'

type By = 'origin' | 'variety'

export function ComparePanel({ filters, ccy, unit, className }: {
  filters: Record<string, string | string[] | undefined>
  ccy: string
  unit: MassUnit
  className?: string
}) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  const [by, setBy] = useState<By>('origin')
  const [open, setOpen] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['prices', 'compare', by, filters, ccy],
    queryFn: () => api.get<CompareResponse>('/prices/compare', { ...filters, by, currency: ccy }),
    placeholderData: keepPreviousData,
  })

  const name = (key: string) => (by === 'origin' ? (key === '_none' ? t('prices.originUnknown') : country(key)) : variety(key))
  const uLabel = unitLabel(ccy, unit)
  const d = q.data

  return (
    <Panel
      className={className}
      eyebrow={uLabel}
      title={by === 'origin' ? t('prices.compare.titleOrigin') : t('prices.compare.titleVariety')}
      actions={
        <Segmented<By> size="sm" value={by} onChange={(v) => { setBy(v); setOpen(null) }}
          options={[{ value: 'origin', label: t('prices.compare.byOrigin') }, { value: 'variety', label: t('prices.compare.byVariety') }]} />
      }
      footer={d && d.bars.length > 0 ? (
        <div className="flex flex-col gap-1">
          {uniqueSources(d).map((s) => <SourceLine key={s.key} p={{ source: s, is_demo: d.bars.some((b) => b.is_demo) }} compact />)}
          <span className="text-[0.8rem]">{t('prices.compare.avgNote')}</span>
        </div>
      ) : undefined}
    >
      {q.isLoading ? <Loading /> : q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} /> : !d || d.bars.length === 0 ? (
        <EmptyState title={t('prices.empty.title')} hint={t('prices.empty.compare')} />
      ) : (
        <div>
          <p className="text-[0.9rem] text-muted mb-3">
            {t('prices.compare.subtitle', { n: d.window_months, p: fmtPeriodLabel(d.anchor_period, lang) })} {t('prices.compare.details')}
          </p>
          <BarList d={d} by={by} name={name} unit={unit} open={open} setOpen={setOpen} />
          {d.excluded.length > 0 && (
            <p className="mt-3 text-[0.85rem] text-muted">
              <span className="font-medium text-charcoal-soft">{t('prices.compare.excluded', { n: d.window_months })}:</span>{' '}
              {dedupeExcluded(d).map((e, i) => (
                <Fragment key={e.key}>
                  {i > 0 && ', '}
                  {name(e.key)} <span className="num">({t('prices.compare.lastPeriod', { p: fmtPeriodLabel(e.last_period, lang) })})</span>
                </Fragment>
              ))}
            </p>
          )}
        </div>
      )}
    </Panel>
  )
}

function BarList({ d, by, name, unit, open, setOpen }: {
  d: CompareResponse; by: By; name: (k: string) => string; unit: MassUnit; open: string | null; setOpen: (k: string | null) => void
}) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  const max = Math.max(...d.bars.map((b) => b.max))
  const pct = (v: number) => `${(v / max) * 100}%`
  return (
    <ul className="flex flex-col">
      {d.bars.map((b) => {
        const barId = b.id ?? `${b.key}|${b.market_iso3 ?? ''}|${b.is_demo ? 'demo' : ''}`
        const isOpen = open === barId
        // Several bars can share an origin (one per market): name the market so they are distinguishable.
        const sharesKey = d.bars.filter((x) => x.key === b.key).length > 1
        return (
          <li key={barId} className="border-b border-line-soft last:border-b-0">
            <button
              type="button"
              onClick={() => setOpen(isOpen ? null : barId)}
              aria-expanded={isOpen}
              className="w-full grid grid-cols-[minmax(5.5rem,11rem)_minmax(0,1fr)_4rem_5.5rem] gap-2 sm:grid-cols-[minmax(7rem,11rem)_minmax(0,1fr)_4.5rem_6.5rem] items-center sm:gap-3 py-2 text-left hover:bg-ivory/50"
            >
              <span className="flex items-center gap-1 min-w-0 font-medium text-charcoal">
                {isOpen ? <ChevronDown size={15} className="shrink-0 text-muted" /> : <ChevronRight size={15} className="shrink-0 text-muted" />}
                <span className="truncate">
                  {name(b.key)}
                  {sharesKey && b.market_iso3 && (
                    <span className="text-muted font-normal"> → {country(b.market_iso3)}</span>
                  )}
                </span>
                {b.is_demo && <span className="shrink-0"><DemoBadge /></span>}
              </span>
              <span className="relative h-[18px]" aria-hidden>
                <span className="absolute inset-y-0 left-0 bg-forest-600 rounded-r-[3px]" style={{ width: pct(b.value) }} />
                {b.n_series > 1 && b.max > b.min && (
                  <span className="absolute top-1/2 h-[2px] -translate-y-1/2 bg-charcoal/70" style={{ left: pct(b.min), width: `calc(${pct(b.max)} - ${pct(b.min)})` }}>
                    <span className="absolute -left-px -top-[4px] h-[10px] w-[2px] bg-charcoal/70" />
                    <span className="absolute -right-px -top-[4px] h-[10px] w-[2px] bg-charcoal/70" />
                  </span>
                )}
              </span>
              <span className="num text-right text-[1rem] text-charcoal">{fmtPrice(toUnit(b.value, unit), lang)}</span>
              <span className="text-[0.8rem] leading-tight text-muted">
                <span className={clsx('num', b.mixed_periods && 'text-warn')}>{fmtPeriodLabel(b.period_label, lang)}</span>
                <span className="block">{b.n_series > 1 ? t('prices.compare.avgOf', { n: b.n_series }) : (b.sources[0]?.publisher || b.sources[0]?.name)}</span>
              </span>
            </button>
            {isOpen && (
              <div className="pl-6 pr-2 pb-3">
                <table className="w-full text-[0.85rem]">
                  <tbody>
                    {b.components.map((c) => (
                      <tr key={c.series_id} className="border-t border-line-soft first:border-t-0">
                        <td className="py-1.5 pr-3 text-charcoal-soft">
                          {by === 'origin' ? variety(c.variety) : (c.origin_iso3 ? country(c.origin_iso3) : t('prices.originUnknown'))}
                          {c.color_grade && <span className="text-muted"> · {colorLabel(c.color_grade, t)}</span>}
                          {c.organic && <span className="text-muted"> · {t('prices.organic')}</span>}
                        </td>
                        <td className="py-1.5 pr-3 num text-right whitespace-nowrap">{fmtPrice(toUnit(c.value, unit), lang)}</td>
                        <td className="py-1.5 pr-3 num whitespace-nowrap">{fmtPeriodLabel(c.period_label, lang)}</td>
                        <td className="py-1.5 pr-3 text-muted">
                          {c.source?.publisher || c.source?.name}
                          {c.published_at && <> · {t('prov.published')} {fmtDate(c.published_at, lang)}</>}
                        </td>
                        <td className="py-1.5 text-right whitespace-nowrap">
                          {c.is_demo && <span className="mr-2"><DemoBadge /></span>}
                          <DocLink url={c.source_url} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function uniqueSources(d: CompareResponse) {
  const m = new Map<string, NonNullable<CompareResponse['bars'][number]['sources'][number]>>()
  d.bars.forEach((b) => b.sources.forEach((s) => s && m.set(s.key, s)))
  return [...m.values()]
}

function dedupeExcluded(d: CompareResponse) {
  const have = new Set(d.bars.map((b) => b.key))
  const seen = new Map<string, CompareResponse['excluded'][number]>()
  for (const e of d.excluded) {
    if (have.has(e.key)) continue
    const prev = seen.get(e.key)
    if (!prev || e.last_period > prev.last_period) seen.set(e.key, e)
  }
  return [...seen.values()]
}
