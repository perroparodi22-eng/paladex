// /raccolti — harvest & production intelligence: production by country (official statistics), the
// last 12 months of NASA POWER weather in the honey regions with rule-based signals (automatic
// assessments, never data), and harvest reports and news. The view (country, region, signal filter,
// production list, chart) lives in the address: /raccolti?paese=ARG&regione=ARG-BA&segnale=any.
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { MapPanel } from '@/components/harvest/MapPanel'
import { ProductionPanel } from '@/components/harvest/ProductionPanel'
import { ReadingGuide, WeatherAttribution, WeatherStatusNote } from '@/components/harvest/parts'
import { RegionDetail } from '@/components/harvest/RegionDetail'
import { ReportsPanel } from '@/components/harvest/ReportsPanel'
import { RulesPanel } from '@/components/harvest/RulesPanel'
import { SignalsSummary } from '@/components/harvest/SignalsSummary'
import type { WeatherResponse } from '@/components/harvest/types'
import { useHarvestParams } from '@/components/harvest/useHarvestParams'
import { matchesSignal, WeatherTable } from '@/components/harvest/WeatherTable'
import { ErrorBlock, Loading, PageHeader, Select } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { useLabels } from '@/lib/meta'

export default function Harvest() {
  const { t } = useI18n()
  const { state, update } = useHarvestParams()
  const weather = useQuery({
    queryKey: ['harvest', 'weather'],
    queryFn: () => api.get<WeatherResponse>('/harvest/weather'),
    // while the first collection runs, regions arrive one after another
    refetchInterval: (q) => (q.state.data?.collection.state === 'running' ? 30_000 : false),
  })
  const w = weather.data
  return (
    <div>
      <PageHeader
        eyebrow={t('harvest.eyebrow')}
        title={t('nav.harvest')}
        subtitle={t('harvest.subtitle')}
        actions={<CountrySelect data={w} value={state.country} onChange={(c) => update({ country: c, region: '' })} />}
      />
      <div className="flex min-w-0 flex-col gap-5">
        <ReadingGuide />
        {weather.isLoading ? <Loading /> : weather.error ? <ErrorBlock error={weather.error} onRetry={() => weather.refetch()} /> : w ? (
          <WeatherSection data={w} />
        ) : null}
        <ProductionPanel
          country={state.country} scope={state.scope} metric={state.metric} years={state.years}
          onCountry={(c) => update({ country: c, region: '' })} onScope={(s) => update({ scope: s })}
          onMetric={(m) => update({ metric: m })} onYears={(y) => update({ years: y })}
        />
        <ReportsPanel />
        {/* before the first weather data: the rules still say how the signals will be made */}
        {w && !w.available && <RulesPanel meta={w} />}
        {w && w.available && <WeatherAttribution meta={w} className="border-t border-line pt-3" />}
      </div>
    </div>
  )
}

function WeatherSection({ data }: { data: WeatherResponse }) {
  const { state, update } = useHarvestParams()
  const visible = useMemo(() => new Set(data.regions
    .filter((r) => (!state.country || r.country_iso3 === state.country) && matchesSignal(r, state.signal))
    .map((r) => r.key)), [data, state.country, state.signal])
  const region = data.regions.some((r) => r.key === state.region) ? state.region : ''
  const select = (key: string) => update({ region: key === region ? '' : key })
  return (
    <>
      <WeatherStatusNote meta={data} regionsWithData={data.regions_with_data} regionsTotal={data.regions.length} />
      {data.available && (
        <>
          <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
            <MapPanel data={data} visible={visible} selected={region} onSelect={select} />
            {region ? <RegionDetail regionKey={region} onClose={() => update({ region: '' })} />
              : <SignalsSummary data={data} country={state.country} onSelect={select} onSignal={(s) => update({ signal: s })} />}
          </div>
          <WeatherTable data={data} country={state.country} signal={state.signal} selected={region}
            onSignal={(s) => update({ signal: s })} onSelect={select} />
          <RulesPanel meta={data} />
        </>
      )}
    </>
  )
}

function CountrySelect({ data, value, onChange }: { data: WeatherResponse | undefined; value: string; onChange: (iso3: string) => void }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const options = (data?.countries ?? []).map((c) => ({ iso3: c.iso3, name: (lang === 'it' ? c.name_it : c.name_en) ?? c.iso3 }))
  if (value && !options.some((o) => o.iso3 === value)) options.push({ iso3: value, name: country(value) })
  options.sort((a, b) => a.name.localeCompare(b.name, lang))
  return (
    <Select label={t('harvest.country')} value={value} onChange={(e) => onChange(e.target.value)} className="w-full sm:w-64">
      <option value="">{t('harvest.allCountries')}</option>
      {options.map((o) => <option key={o.iso3} value={o.iso3}>{o.name}</option>)}
    </Select>
  )
}
