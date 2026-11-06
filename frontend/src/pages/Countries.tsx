// /paesi — country intelligence: offline world map (choropleth by export volume, production or
// recent news) and the 20 priority countries beside it. Click a country for its profile.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ErrorBlock, Loading, PageHeader, Segmented } from '@/components/ui'
import { OtherCountries, PriorityList } from '@/components/countries/CountryLists'
import { MapPanel } from '@/components/countries/MapPanel'
import { MAP_METRICS } from '@/components/countries/metrics'
import type { CountriesResponse, MapMetric } from '@/components/countries/types'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { useView } from '@/lib/view'
import { Details } from '@/components/simple/Details'

export default function Countries() {
  const { t } = useI18n()
  const { simple } = useView()
  const [sp, setSp] = useSearchParams()
  const q = useQuery({ queryKey: ['countries'], queryFn: () => api.get<CountriesResponse>('/countries') })
  const fromUrl = sp.get('misura') as MapMetric | null
  const [metric, setMetricState] = useState<MapMetric | null>(fromUrl && MAP_METRICS.includes(fromUrl) ? fromUrl : null)

  // Default: the first measure that has data (declared exports, then production, imports, news).
  useEffect(() => {
    if (metric || !q.data) return
    setMetricState(MAP_METRICS.find((m) => q.data.metrics[m].countries > 0) ?? 'exports')
  }, [metric, q.data])

  const setMetric = (m: MapMetric) => {
    setMetricState(m)
    setSp((prev) => { const n = new URLSearchParams(prev); n.set('misura', m); return n }, { replace: true })
  }

  return (
    <div>
      <PageHeader
        eyebrow={t('countries.eyebrow')}
        title={t('countries.title')}
        subtitle={t('countries.subtitle')}
        actions={metric ? (
          <div>
            <span className="label">{t('countries.metric')}</span>
            <Segmented value={metric} onChange={setMetric} options={MAP_METRICS.map((m) => ({ value: m, label: t(`countries.metric.${m}`) }))} />
          </div>
        ) : undefined}
      />
      {q.isLoading || (q.data && !metric) ? <Loading /> : q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} /> : q.data && metric ? (
        <>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px] items-start">
            <div className="min-w-0 flex flex-col gap-5">
              <MapPanel data={q.data} metric={metric} />
              {!simple && <div className="hidden xl:block"><OtherCountries data={q.data} metric={metric} /></div>}
            </div>
            <PriorityList data={q.data} metric={metric} />
          </div>
          {/* below the priority list on narrower screens; in the simple view, one click away */}
          {simple ? (
            <Details label={t('simple.countries.others')} hideLabel={t('simple.countries.othersHide')}>
              <OtherCountries data={q.data} metric={metric} />
            </Details>
          ) : <div className="mt-5 xl:hidden"><OtherCountries data={q.data} metric={metric} /></div>}
        </>
      ) : null}
    </div>
  )
}
