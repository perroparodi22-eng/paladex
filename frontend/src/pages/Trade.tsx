// /commercio — international honey trade (HS 0409): leading exporters and importers, where each
// market buys from, trends over time. Customs declarations, one source per figure.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ErrorBlock, Loading, Note, PageHeader, Panel, Segmented, Select } from '@/components/ui'
import { DataMissing } from '@/components/trade/bits'
import { FlowsPanel } from '@/components/trade/FlowsPanel'
import { LeadersChart } from '@/components/trade/LeadersChart'
import { LeadersTable } from '@/components/trade/LeadersTable'
import { TradeNotes } from '@/components/trade/TradeNotes'
import type { FacetsResponse, LeadersResponse, TradeFlow, TradeMetric } from '@/components/trade/types'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'

export default function Trade() {
  const { t } = useI18n()
  const facets = useQuery({ queryKey: ['trade', 'facets'], queryFn: () => api.get<FacetsResponse>('/trade/facets') })
  const [yearSel, setYearSel] = useState<number | null>(null)
  const [metric, setMetric] = useState<TradeMetric>('volume')
  const [expBasis, setExpBasis] = useState<'declared' | 'mirror'>('declared')
  const [chartFlow, setChartFlow] = useState<TradeFlow>('import')

  const f = facets.data
  const defaultYear = f ? (f.default_year.import ?? f.default_year.export ?? f.years.at(-1)?.year ?? null) : null
  const year = yearSel ?? defaultYear
  const hasData = Boolean(f && f.total_rows > 0)

  const leaders = (flow: TradeFlow, basis: 'declared' | 'mirror') => ({
    queryKey: ['trade', 'leaders', flow, basis, year, metric],
    queryFn: () => api.get<LeadersResponse>('/trade/leaders', { flow, year: year ?? undefined, metric, basis, limit: 100 }),
    enabled: hasData && year !== null,
    placeholderData: keepPreviousData,
  })
  const imp = useQuery(leaders('import', 'declared'))
  const exp = useQuery(leaders('export', expBasis))

  const years = (f?.years ?? []).filter((y) => y.import_complete + y.export_complete > 0 || y.year === year)
  const yearEntry = f?.years.find((y) => y.year === year)
  const prevEntry = f?.years.find((y) => y.year === (year ?? 0) - 1)
  const partialYear = Boolean(yearEntry && prevEntry
    && yearEntry.import_complete + yearEntry.export_complete < 0.6 * (prevEntry.import_complete + prevEntry.export_complete))

  return (
    <div>
      <PageHeader
        eyebrow={t('trade.eyebrow')}
        title={t('trade.title')}
        subtitle={t('trade.subtitle')}
        actions={hasData ? (
          <div className="flex items-end gap-3">
            <Select label={t('trade.year')} value={year ?? ''} onChange={(e) => setYearSel(Number(e.target.value))} className="w-[150px]">
              {[...years].reverse().map((y) => {
                const yPrev = f?.years.find((p) => p.year === y.year - 1)
                const partial = yPrev && y.import_complete + y.export_complete < 0.6 * (yPrev.import_complete + yPrev.export_complete)
                return <option key={y.year} value={y.year}>{partial ? t('trade.yearPartial', { y: y.year }) : y.year}</option>
              })}
            </Select>
            <div>
              <span className="label">{t('trade.metric')}</span>
              <Segmented value={metric} onChange={setMetric} options={[
                { value: 'volume', label: t('trade.metric.volume') },
                { value: 'value', label: t('trade.metric.value') },
              ]} />
            </div>
          </div>
        ) : undefined}
      />

      {facets.isLoading ? <Loading /> : facets.error ? <ErrorBlock error={facets.error} onRetry={() => facets.refetch()} /> : !hasData ? (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px] items-start">
          <Panel>
            <DataMissing title={t('trade.empty.title')} what={t('trade.empty.hint')}
              providers={f?.providers ?? []} fallback={t('trade.empty.fallbackSources')} />
            {(f?.providers.length ?? 0) > 0 && (
              <div className="mt-2 border-t border-line-soft pt-3 px-2">
                <div className="eyebrow mb-1.5">{t('trade.empty.schedule')}</div>
                <ul className="flex flex-col gap-1.5 text-[0.88rem]">
                  {f!.providers.map((p) => (
                    <li key={p.key}>
                      <span className="text-charcoal-soft font-medium">{p.publisher || p.name}</span>
                      {p.expected_update && <span className="text-muted"> — {p.expected_update}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>
          {f && <TradeNotes facets={f} />}
        </div>
      ) : (
        <>
          <div className="mb-5">
            <Note tone={partialYear ? 'warn' : 'info'}>{defaultYear ? t('trade.lagNote', { y: defaultYear }) : t('trade.lagNoteNoYear')}</Note>
          </div>

          <div className="grid gap-5 xl:grid-cols-2 items-start mb-5">
            <LeadersTable flow="import" data={imp.data} isLoading={imp.isLoading} error={imp.error} refetch={() => imp.refetch()}
              basis="declared" metric={metric} year={year} />
            <LeadersTable flow="export" data={exp.data} isLoading={exp.isLoading} error={exp.error} refetch={() => exp.refetch()}
              basis={expBasis} onBasis={setExpBasis} metric={metric} year={year} />
          </div>

          <div className="mb-5">
            <LeadersChart flow={chartFlow} onFlow={setChartFlow} data={chartFlow === 'import' ? imp.data : exp.data} metric={metric} year={year} />
          </div>

          <div className="mb-5">
            <FlowsPanel facets={f!} year={year} metric={metric} />
          </div>

          <TradeNotes facets={f!} wide />
        </>
      )}
    </div>
  )
}
