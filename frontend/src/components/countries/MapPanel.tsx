// Map panel: choropleth for the selected metric with FIXED classes (choropleth.ts), old figures
// hatched (never coloured as current), legend with contiguous ranges and counts, the year basis and
// the mix of sources under the map (MapLegend.tsx), provenance footer.
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { DemoBadge, Panel } from '@/components/ui'
import { DataMissing, SourcesFooter } from '@/components/trade/bits'
import { useI18n } from '@/i18n'
import { useLabels } from '@/lib/meta'
import { isOld, OLD_AFTER_YEARS } from './choropleth'
import { fillFor, MapBasis, MapLegend, OldDataPattern, summarize } from './MapLegend'
import { fmtMetric, metricSource, metricValue, metricYear, metricYearNum } from './metrics'
import { countryName, useRegion } from './parts'
import type { CountriesResponse, CountryListItem, MapMetric } from './types'
import { escapeHtml, WorldMap } from './WorldMap'

export function MapPanel({ data, metric }: { data: CountriesResponse; metric: MapMetric }) {
  const { t, lang } = useI18n()
  const { dataStatus } = useLabels()
  const navigate = useNavigate()
  const region = useRegion()
  const meta = data.metrics[metric]
  const summary = useMemo(() => summarize(data.countries, metric, lang), [data, metric, lang])
  const newsUnit = t('countries.unit.news')

  const tooltipOf = (c: CountryListItem) => {
    const v = metricValue(c, metric)
    const yr = metricYear(c, metric)
    const src = metricSource(c, metric)
    const name = escapeHtml(countryName(c, lang))
    const head = `<div class="t-name">${name}${src.demo ? `<span class="t-demo">${escapeHtml(t('ui.demo'))}</span>` : ''}</div>`
      + `<div class="t-muted" style="margin-top:0">${escapeHtml(region(c.region))}</div>`
    const label = escapeHtml(t(`countries.metric.${metric}`))
    const old = v !== null && isOld(metricYearNum(c, metric), summary.newest)
    const status = src.status && !['published', 'live', 'demo'].includes(src.status) ? dataStatus(src.status) : null
    const body = v === null
      ? `<div class="t-row"><span class="t-label">${label}</span><span class="t-label">${escapeHtml(t('countries.noData'))}</span></div>`
      : `<div class="t-row"><span class="t-label">${label}${yr ? ` · ${escapeHtml(yr)}` : ''}</span><span class="t-val">${escapeHtml(fmtMetric(v, metric, lang, newsUnit))}</span></div>`
        + (old ? `<div class="t-old">${escapeHtml(t('countries.oldTip', { y: yr ?? '', n: summary.newest ?? '' }))}</div>` : '')
        + (src.name ? `<div class="t-muted">${escapeHtml(t('prov.source'))}: ${escapeHtml(src.name)}${status ? ` · ${escapeHtml(status)}` : ''}</div>` : '')
    return `${head}${body}<div class="t-sep t-cta">${escapeHtml(t('countries.clickHint'))} →</div>`
  }

  // "Dati 2023–2025 · 17 paesi con dati più vecchi (tratteggiati)"
  const oldest = summary.years.length ? summary.years[summary.years.length - 1].year : summary.newest
  const eyebrow = metric === 'news' || summary.newest === null
    ? t(`countries.metric.${metric}`)
    : t('countries.mapBasis', { r: oldest === summary.newest ? String(summary.newest) : `${oldest}–${summary.newest}` })
      + (summary.old.n ? ` · ${t(summary.old.n === 1 ? 'countries.mapOldOne' : 'countries.mapOld', { n: summary.old.n })}` : '')

  return (
    <Panel
      title={t(`countries.metricLong.${metric}`)}
      eyebrow={eyebrow}
      bodyClassName="!p-0"
      className="min-w-0"
      actions={
        <>
          {meta.is_demo && <DemoBadge />}
          <span className="text-[0.85rem] text-muted whitespace-nowrap">{t('countries.mapCountries', { n: summary.count })}</span>
        </>
      }
      footer={
        summary.count > 0 ? (
          <SourcesFooter
            sources={meta.sources}
            extra={<>{metric === 'news' ? t('countries.mapNoteNews') : t('countries.mapNote', { n: OLD_AFTER_YEARS })} {t('countries.zoomHint')}</>}
          />
        ) : undefined
      }
    >
      <OldDataPattern />
      <div className="relative">
        <WorldMap
          items={data.countries}
          styleKey={`${metric}|${summary.count}|${summary.newest}|${summary.classCounts.join(',')}`}
          fillOf={(c) => fillFor(c, metric, summary.newest)}
          tooltipOf={tooltipOf}
          onSelect={(iso3) => navigate(`/paesi/${iso3}`)}
          height={560}
        />
        {summary.count === 0 && (
          <div className="absolute inset-x-0 top-5 z-[500] flex justify-center pl-16 pr-6">
            <div className="max-w-xl rounded-sm border border-line bg-white/95 px-4 shadow-panel">
              <DataMissing compact what={t('countries.mapEmpty')} providers={meta.providers}
                fallback={metric === 'production' ? t('countries.prod.fallback') : metric === 'news' ? t('countries.news.fallback') : t('countries.trade.fallback')} />
            </div>
          </div>
        )}
      </div>
      {summary.count > 0 && <MapLegend metric={metric} summary={summary} />}
      {summary.count > 0 && <MapBasis summary={summary} />}
    </Panel>
  )
}
