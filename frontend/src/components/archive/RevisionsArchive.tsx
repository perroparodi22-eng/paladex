// Archivio · Revisioni: every value stored for a series, period by period, so the owner sees what a
// source changed and when (Paladex keeps superseded and withdrawn values, it never overwrites them).
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { Badge, DemoBadge, EmptyState, ErrorBlock, Loading, Note, Panel, Segmented } from '@/components/ui'
import { DocLink } from '@/components/prices/bits'
import { colorLabel, fmtPeriodLabel } from '@/components/prices/utils'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate, fmtDateTime, fmtNumber, fmtTonnes } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import type { Lang } from '@/lib/types'
import { ChangeCell } from './PriceArchive'
import { fmtProduction } from './ProductionArchive'
import { priceParams, readProduction, useArchiveParams, usePriceArchive, useTradeSelection } from './state'
import type { RevisionEntry, RevisionsResponse } from './types'
import { seriesLabels } from './utils'

type Kind = RevisionsResponse['kind']
const KINDS: Kind[] = ['price', 'trade', 'production']

export function fmtRevisionValue(e: RevisionEntry, kind: Kind, lang: Lang): string {
  if (kind === 'trade') return fmtTonnes(e.value, lang)
  if (kind === 'production') return fmtProduction(e.value, e.unit ?? '', lang)
  const v = `${fmtNumber(e.value, lang, 3)} ${e.currency ?? ''}/${e.unit ?? ''}`
  return e.low != null && e.high != null ? `${v} (${fmtNumber(e.low, lang, 3)}–${fmtNumber(e.high, lang, 3)})` : v
}

export function RevisionsView({ d }: { d: RevisionsResponse }) {
  const { t, lang } = useI18n()
  const c = d.counts
  if (c.periods === 0) return <EmptyState hint={t('archive.r.noRows')} />
  return (
    <div>
      <p className="text-[0.95rem] text-charcoal-soft mb-3">
        {t('archive.r.summary', { p: c.periods, v: c.stored_values, r: c.revised, w: c.withdrawn })}
      </p>
      {d.periods.length === 0 ? (
        <EmptyState title={t('archive.r.none', { p: c.periods })} hint={t('archive.r.noneHint')} />
      ) : (
        <div className="flex flex-col gap-4">
          {d.periods.map((p) => (
            <section key={`${p.source?.key}-${p.period_start}-${p.label}-${p.revisions[0]?.id}`} className="border border-line-soft rounded-sm min-w-0">
              <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 border-b border-line-soft bg-paper">
                <span className="num font-medium">{fmtPeriodLabel(p.period_label, lang)}</span>
                <Badge tone={p.status === 'withdrawn' ? 'down' : 'warn'}>{p.status === 'withdrawn' ? t('archive.r.withdrawn') : t('archive.r.revised')}</Badge>
                {p.label && <span className="text-sm text-muted break-words min-w-0">{p.label}</span>}
                <span className="text-sm text-muted ml-auto">{p.source?.publisher || p.source?.name}</span>
              </div>
              <div className="overflow-x-auto">
                <table className="table-clean min-w-[640px]">
                  <thead>
                    <tr>
                      <th>{t('archive.r.col.version')}</th>
                      <th className="!text-right">{t('archive.r.col.value')}</th>
                      <th>{t('archive.r.col.change')}</th>
                      <th>{t('archive.r.col.published')}</th>
                      <th>{t('archive.r.col.collected')}</th>
                      <th>{t('archive.r.col.state')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.revisions.map((e, i) => {
                      const last = i === p.revisions.length - 1
                      const state = e.is_current ? t('archive.r.current') : last ? t('archive.r.retired') : t('archive.r.superseded')
                      return (
                        <tr key={e.id} className={e.is_current ? 'font-medium' : 'text-charcoal-soft'}>
                          <td className="num">{t('archive.r.versionN', { n: i + 1 })}{e.is_demo && <span className="ml-1"><DemoBadge /></span>}</td>
                          <td className="num text-right whitespace-nowrap">{fmtRevisionValue(e, d.kind, lang)}</td>
                          <td><ChangeCell pct={e.change_pct} /></td>
                          <td className="whitespace-nowrap"><span className="mr-1.5">{fmtDate(e.published_at, lang)}</span><DocLink url={e.source_url} /></td>
                          <td className="whitespace-nowrap">{fmtDateTime(e.collected_at, lang)}</td>
                          <td><Badge tone={e.is_current ? 'up' : 'outline'}>{state}</Badge></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

export function RevisionsArchive() {
  const { t } = useI18n()
  const { country, variety, priceType } = useLabels()
  const { sp, set } = useArchiveParams()
  const raw = sp.get('rserie')
  const kind: Kind = KINDS.includes(raw as Kind) ? (raw as Kind) : 'price'
  const price = usePriceArchive()
  const trade = useTradeSelection()
  const prod = readProduction(sp)
  const selected = price.history.data?.selected ?? null
  const labels = useMemo(() => seriesLabels(price.history.data?.series ?? [], {
    country: (c) => country(c), color: (c) => colorLabel(c, t), t,
  }), [price.history.data, country, t])

  const params = kind === 'price'
    ? (price.sel && selected ? { kind, ...priceParams(price.sel, price.ccy, selected.id) } : null)
    : kind === 'trade'
      ? (trade.sel ? { kind, reporter: trade.sel.reporter, partner: trade.sel.partner, flow: trade.sel.flow } : null)
      : { kind, country: prod.country, metric: prod.metric }
  const q = useQuery({
    queryKey: ['archive', 'revisions', params],
    queryFn: () => api.get<RevisionsResponse>('/archive/revisions', params!),
    enabled: params !== null,
    placeholderData: keepPreviousData,
  })
  const metricLabel = (k: string) => {
    const s = t(`archive.pr.metric.${k}`)
    return s === `archive.pr.metric.${k}` ? k : s
  }
  const what = kind === 'price'
    ? (selected ? `${priceType(selected.price_type)} · ${country(selected.origin_iso3)} · ${variety(selected.variety)} · ${labels[selected.id] ?? ''}` : '—')
    : kind === 'trade'
      ? (trade.sel ? `${t(`archive.flow.${trade.sel.flow}`)} · ${country(trade.sel.reporter)} · ${trade.sel.partner === 'WLD' ? t('archive.t.partnerTotal') : country(trade.sel.partner)}` : '—')
      : `${metricLabel(prod.metric)} · ${country(prod.country)}`
  const waiting = kind === 'price' ? (price.options.isLoading || price.history.isLoading) : kind === 'trade' ? trade.options.isLoading : false

  return (
    <div className="flex flex-col gap-5">
      <Panel bodyClassName="p-4">
        <span className="label">{t('archive.r.kind')}</span>
        <Segmented<Kind> size="sm" value={kind} onChange={(v) => set({ rserie: v === 'price' ? null : v })}
          options={KINDS.map((k) => ({ value: k, label: t(`archive.r.kind.${k}`) }))} />
        <p className="text-sm text-muted mt-2 break-words">{t('archive.r.selected', { x: what })}</p>
      </Panel>
      <Panel footer={t('archive.r.howTo')}>
        {waiting || (params !== null && q.isLoading) ? <Loading />
          : q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
          : params === null ? <Note>{t('archive.r.noRows')}</Note>
          : q.data ? <RevisionsView d={q.data} /> : null}
      </Panel>
    </div>
  )
}
