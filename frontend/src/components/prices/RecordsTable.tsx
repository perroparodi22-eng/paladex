// "Storico delle rilevazioni": raw observations exactly as published, paginated, with CSV export.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronLeft, ChevronRight, Download } from 'lucide-react'
import { useEffect, useState } from 'react'
import { EmptyState, ErrorBlock, Loading, Panel, StatusBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api, qs } from '@/lib/api'
import { fmtAgo, fmtDate, fmtNumber } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { isMirror } from '@/lib/mirror'
import { DocLink, ScrollHint, useOverflows } from './bits'
import type { Ccy, MassUnit, ObservationsResponse } from './types'
import { colorLabel, fmtPeriodLabel, fmtPrice, rowValuePerKg, toUnit, unitLabel } from './utils'

const PAGE_SIZE = 20

/* Below xl (tablet) status, source, publication date and document share one cell pinned to the
 * right edge, so provenance stays on screen even if the numeric columns have to scroll under it.
 * `FULL` cells exist only from xl up, `COMPACT` cells only below it. */
const FULL = 'hidden xl:table-cell'
const COMPACT = 'xl:hidden'
// Phones: not pinned (the price must stay visible next to its origin); provenance follows it.
const PINNED = 'sticky right-0 z-[1] border-l border-line-soft max-sm:static max-sm:min-w-[12rem]'

export function RecordsTable({ filters, from, ccy, unit }: {
  filters: Record<string, string | string[] | undefined>
  from: string | null
  ccy: Ccy
  unit: MassUnit
}) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  const [page, setPage] = useState(1)
  const params = { ...filters, from: from ?? undefined }
  const paramsKey = JSON.stringify(params)
  useEffect(() => setPage(1), [paramsKey])

  const q = useQuery({
    queryKey: ['prices', 'observations', params, page],
    queryFn: () => api.get<ObservationsResponse>('/prices/observations', { ...params, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const csvHref = `/api/prices/observations${qs({ ...params, format: 'csv', lang })}`
  const d = q.data
  const anyColour = Boolean(d?.rows.some((r) => r.color_grade))
  const [wrap, overflows] = useOverflows<HTMLDivElement>(d)

  return (
    <Panel
      className="mb-5"
      title={t('prices.rec.title')}
      eyebrow={d ? t('prices.rec.total', { n: fmtNumber(d.total, lang) }) : undefined}
      bodyClassName="p-0"
      actions={isMirror() ? undefined : (
        <a href={csvHref} download className="btn-secondary !py-1.5" aria-disabled={!d?.total}>
          <Download size={16} /> {t('prices.rec.export')}
        </a>
      )}
      footer={
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>{t('prices.rec.subtitle')}</span>
          {d && d.pages > 1 && (
            <div className="flex items-center gap-2">
              <button type="button" className="btn-secondary !px-2.5 !py-1" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                <ChevronLeft size={16} /> {t('prices.rec.prev')}
              </button>
              <span className="num text-charcoal-soft px-1">{t('prices.rec.pageOf', { p: page, n: d.pages })}</span>
              <button type="button" className="btn-secondary !px-2.5 !py-1" disabled={page >= d.pages} onClick={() => setPage((p) => p + 1)}>
                {t('prices.rec.next')} <ChevronRight size={16} />
              </button>
            </div>
          )}
        </div>
      }
    >
      {q.isLoading ? <Loading /> : q.error ? <div className="p-5"><ErrorBlock error={q.error} onRetry={() => q.refetch()} /></div> : !d || d.total === 0 ? (
        <EmptyState title={t('prices.empty.title')} hint={t('prices.empty.period')} />
      ) : (
        <>
        {overflows && <ScrollHint />}
        <div ref={wrap} className="relative overflow-x-auto">
          <table className="table-clean [&_th]:whitespace-nowrap [&_th]:!px-2 [&_td]:!px-2 xl:[&_th]:!px-2.5 xl:[&_td]:!px-2.5 [&_td]:!py-2">
            <thead>
              <tr>
                <th>{t('prices.rec.col.period')}</th>
                <th>{t('prices.rec.col.origin')}</th>
                <th>{t('prices.rec.col.variety')}</th>
                {anyColour && <th className={FULL}>{t('prices.rec.col.colour')}</th>}
                <th className="!text-right max-xl:!whitespace-normal">{t('prices.rec.col.published')}</th>
                <th className="!text-right !whitespace-normal leading-tight max-xl:!tracking-normal">
                  {t('prices.rec.col.converted')}
                  <span className="block normal-case tracking-normal text-[0.75rem]">{unitLabel(ccy, unit)}</span>
                </th>
                <th className={FULL}>{t('prices.rec.col.status')}</th>
                <th className={FULL}>{t('prices.rec.col.source')}</th>
                <th className={clsx(FULL, '!text-center')}>{t('prices.rec.col.doc')}</th>
                <th className={clsx(COMPACT, PINNED, 'bg-paper !whitespace-normal')}>{t('prices.latest.col.sourceStatus')}</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => {
                const conv = rowValuePerKg(r, ccy)
                const status = (
                  <>
                    <StatusBadge status={r.data_status} />
                    {r.revision > 1 && <span className="ml-1.5 text-[0.72rem] text-muted">{t('prices.rec.revision', { n: r.revision })}</span>}
                  </>
                )
                const source = <span className="text-charcoal-soft">{r.source?.publisher || r.source?.name}</span>
                const provTitle = `${r.source?.name ?? ''} · ${t('prov.collected')} ${fmtAgo(r.collected_at, lang)}`
                return (
                  <tr key={r.id}>
                    <td className="num whitespace-nowrap">{fmtPeriodLabel(r.period_label, lang)}</td>
                    <td className="whitespace-nowrap" title={r.origin_label ?? undefined}>{r.origin_iso3 ? country(r.origin_iso3) : r.origin_label || '—'}</td>
                    <td className="min-w-[6rem] xl:min-w-[8rem]" title={r.variety_raw ?? undefined}>
                      {variety(r.variety)}{r.organic && <span className="text-muted"> · {t('prices.organic')}</span>}
                      {anyColour && r.color_grade && <span className="xl:hidden block text-[0.8rem] text-charcoal-soft">{colorLabel(r.color_grade, t)}</span>}
                    </td>
                    {anyColour && <td className={clsx(FULL, 'whitespace-nowrap text-charcoal-soft')}>{r.color_grade ? colorLabel(r.color_grade, t) : '—'}</td>}
                    <td className="text-right whitespace-nowrap" title={r.terms ?? undefined}>
                      <span className="num">
                        {r.price_low !== null && r.price_high !== null && r.price_low !== r.price_high
                          ? `${fmtPrice(r.price_low, lang)}–${fmtPrice(r.price_high, lang)}`
                          : fmtPrice(r.price_value, lang)}
                      </span>
                      <span className="text-muted text-[0.8rem] max-xl:block"> {r.currency}/{r.unit}</span>
                    </td>
                    <td className="text-right num whitespace-nowrap" title={r.fx_date ? `FX ${fmtDate(r.fx_date, lang)}` : undefined}>
                      {conv === null ? <span className="text-muted" title={t('prices.chart.noFx')}>—</span> : fmtPrice(toUnit(conv, unit), lang)}
                    </td>
                    <td className={clsx(FULL, 'whitespace-nowrap')}>{status}</td>
                    <td className={clsx(FULL, 'text-[0.85rem] whitespace-nowrap')} title={provTitle} data-prov="">
                      {source}
                      <span className="text-muted num text-[0.8rem]" title={t('prov.published')}> · {fmtDate(r.published_at, lang)}</span>
                    </td>
                    <td className={clsx(FULL, 'text-center')}><DocLink url={r.source_url} /></td>
                    <td className={clsx(COMPACT, PINNED, 'bg-white text-[0.85rem] leading-snug')} title={provTitle} data-prov="">
                      {source}
                      <span className="block text-muted num text-[0.8rem]" title={t('prov.published')}>{fmtDate(r.published_at, lang)}</span>
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        {status}
                        <DocLink url={r.source_url} />
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        </>
      )}
    </Panel>
  )
}
