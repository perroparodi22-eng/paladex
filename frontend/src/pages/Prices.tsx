// /prezzi — price intelligence for a bulk-honey buyer.
// One price type at a time (never mixed); every block shows its sources and freshness.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'
import { DemoBadge, ErrorBlock, Loading, PageHeader, Panel } from '@/components/ui'
import { ComparePanel } from '@/components/prices/ComparePanel'
import { DiscrepancyNotice, DiscrepancyPanel } from '@/components/prices/DiscrepancyPanel'
import { FilterBar } from '@/components/prices/FilterBar'
import { LatestTable } from '@/components/prices/LatestTable'
import { PriceChart } from '@/components/prices/PriceChart'
import { NoDataForType, NoDataInView } from '@/components/prices/PricesEmpty'
import { RecordsTable } from '@/components/prices/RecordsTable'
import type { FacetsResponse, LatestResponse, SeriesResponse } from '@/components/prices/types'
import { usePriceFilters } from '@/components/prices/useFilters'
import { useSeriesSlots } from '@/components/prices/useSeriesSlots'
import { disambiguateLabels, fmtPeriodLabel, PRICE_TYPE_ORDER, seriesLabel, varyingDims } from '@/components/prices/utils'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { useLabels } from '@/lib/meta'

export default function Prices() {
  const { t, lang } = useI18n()
  const { country, variety, priceType } = useLabels()
  const { state, update, reset, apiFilters, from, hasDimFilters } = usePriceFilters()

  // Price-type counts (independent of the other filters) decide the default type.
  const all = useQuery({ queryKey: ['prices', 'facets', 'all'], queryFn: () => api.get<FacetsResponse>('/prices/facets') })
  const typeCounts = useMemo(
    () => Object.fromEntries((all.data?.price_types ?? []).map((p) => [p.key, p.count])) as Record<string, number>,
    [all.data],
  )
  useEffect(() => {
    if (!state.type && all.data) update({ type: PRICE_TYPE_ORDER.find((k) => (typeCounts[k] ?? 0) > 0) ?? 'wholesale_bulk' })
  }, [state.type, all.data, typeCounts, update])

  const type = state.type
  const hasType = Boolean(type && (typeCounts[type] ?? 0) > 0)

  const facets = useQuery({
    queryKey: ['prices', 'facets', apiFilters],
    queryFn: () => api.get<FacetsResponse>('/prices/facets', apiFilters),
    enabled: hasType,
    placeholderData: keepPreviousData,
  })
  const series = useQuery({
    queryKey: ['prices', 'series', apiFilters, from, state.freq, state.ccy],
    queryFn: () => api.get<SeriesResponse>('/prices/series', { ...apiFilters, from: from ?? undefined, freq: state.freq, currency: state.ccy }),
    enabled: hasType,
    placeholderData: keepPreviousData,
  })
  const latest = useQuery({
    queryKey: ['prices', 'latest', apiFilters, state.ccy],
    queryFn: () => api.get<LatestResponse>('/prices/latest', { ...apiFilters, currency: state.ccy }),
    enabled: hasType,
    placeholderData: keepPreviousData,
  })

  // Never show data of the previous price type while the new one loads.
  const seriesData = series.data?.price_type === type ? series.data : undefined
  const latestData = latest.data?.price_type === type ? latest.data : undefined

  const idsInOrder = useMemo(() => {
    const ids = (seriesData?.series ?? []).map((s) => s.id)
    for (const r of latestData?.rows ?? []) if (!ids.includes(r.series_id)) ids.push(r.series_id)
    return ids
  }, [seriesData, latestData])
  const slots = useSeriesSlots(idsInOrder, type ?? '')

  const labels = useMemo(() => {
    const items = [...(seriesData?.series ?? []), ...(latestData?.rows ?? [])]
    const dims = varyingDims(items)
    const out: Record<string, string> = {}
    for (const s of seriesData?.series ?? []) out[s.id] = seriesLabel(s, dims, { country, variety, t })
    return disambiguateLabels(seriesData?.series ?? [], out)
  }, [seriesData, latestData, country, variety, t])

  const latestPeriod = useMemo(() => {
    const labelsSorted = (latestData?.rows ?? []).map((r) => r.period_label).sort()
    return labelsSorted.at(-1) ?? null
  }, [latestData])
  const anyDemo = (latestData?.rows ?? []).some((r) => r.is_demo)
  const typeLabel = type ? priceType(type) : ''
  const lastAvailable = facets.data?.period.max ? fmtPeriodLabel(facets.data.period.max.slice(0, 7), lang) : null

  return (
    <div>
      <PageHeader
        eyebrow={t('prices.eyebrow')}
        title={t('prices.title')}
        subtitle={t('prices.subtitle')}
        actions={hasType && latestData ? (
          <div className="flex items-center gap-4 text-right">
            {anyDemo && <DemoBadge />}
            <div>
              <div className="eyebrow">{t('prices.summary.latest')}</div>
              <div className="num text-[1.15rem] text-charcoal">{fmtPeriodLabel(latestPeriod, lang)}</div>
            </div>
            <div className="border-l border-line pl-4">
              <div className="eyebrow">{typeLabel}</div>
              <div className="num text-[1.15rem] text-charcoal">{t('prices.summary.series', { n: latestData.rows.length })}</div>
            </div>
          </div>
        ) : undefined}
      />

      <FilterBar facets={hasType ? facets.data : undefined} typeCounts={typeCounts} state={state} update={update} reset={reset} hasDimFilters={hasDimFilters} />

      {all.isLoading || !type ? <Loading /> : all.error ? <ErrorBlock error={all.error} onRetry={() => all.refetch()} /> : !hasType ? (
        <NoDataForType type={type} />
      ) : facets.data && facets.data.total === 0 && !facets.isPlaceholderData ? (
        <Panel className="mb-5"><NoDataInView reason="filters" onReset={reset} /></Panel>
      ) : (
        <>
          <DiscrepancyNotice items={seriesData?.discrepancies ?? []} />

          {series.error ? <div className="mb-5"><ErrorBlock error={series.error} onRetry={() => series.refetch()} /></div>
            : !seriesData ? <Panel className="mb-5"><Loading /></Panel>
            : seriesData.series.length === 0 ? (
              <Panel className="mb-5" title={t('prices.chart.title')} eyebrow={typeLabel}>
                <NoDataInView reason="period" lastPeriod={lastAvailable} onShowAll={state.range !== 'all' ? () => update({ range: 'all' }) : undefined} />
              </Panel>
            ) : (
              <PriceChart
                key={type}
                data={seriesData}
                labels={labels}
                colorOf={slots.colorOf}
                toggle={slots.toggle}
                hideAll={slots.hideAll}
                restore={slots.restore}
                visibleCount={slots.visibleCount}
                limitHit={slots.limitHit}
                unit={state.unit}
                typeLabel={typeLabel}
              />
            )}

          {latest.error ? <div className="mb-5"><ErrorBlock error={latest.error} onRetry={() => latest.refetch()} /></div>
            : latestData && latestData.rows.length > 0 && (
              <LatestTable rows={latestData.rows} unit={state.unit} colorOf={slots.colorOf} toggle={slots.toggle} />
            )}

          <div className={(seriesData?.discrepancies.length ?? 0) > 0 ? 'grid gap-5 mb-5 2xl:grid-cols-2 items-start' : 'mb-5'}>
            <ComparePanel filters={apiFilters} ccy={state.ccy} unit={state.unit} />
            <DiscrepancyPanel items={seriesData?.discrepancies ?? []} unit={state.unit} />
          </div>

          <RecordsTable filters={apiFilters} from={from} ccy={state.ccy} unit={state.unit} />
        </>
      )}
    </div>
  )
}
