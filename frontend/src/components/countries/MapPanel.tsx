// Map panel: choropleth for the selected metric, legend (with "no data"), provenance footer.
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { DemoBadge, Panel } from '@/components/ui'
import { DataMissing, SourcesFooter } from '@/components/trade/bits'
import { useI18n } from '@/i18n'
import { fmtNumber } from '@/lib/format'
import { colorFor, NO_DATA, quantileClasses } from './choropleth'
import { fmtBound, fmtMetric, metricSource, metricValue, metricYear } from './metrics'
import { countryName, useRegion } from './parts'
import type { CountriesResponse, MapMetric } from './types'
import { escapeHtml, WorldMap } from './WorldMap'

export function MapPanel({ data, metric }: { data: CountriesResponse; metric: MapMetric }) {
  const { t, lang } = useI18n()
  const navigate = useNavigate()
  const region = useRegion()
  const meta = data.metrics[metric]
  const values = useMemo(() => data.countries.map((c) => metricValue(c, metric)).filter((v): v is number => v !== null),
    [data, metric])
  const classes = useMemo(() => quantileClasses(values), [values])
  const newsUnit = t('countries.unit.news')

  const tooltipOf = (c: (typeof data.countries)[number]) => {
    const v = metricValue(c, metric)
    const yr = metricYear(c, metric)
    const src = metricSource(c, metric)
    const name = escapeHtml(countryName(c, lang))
    const head = `<div class="t-name">${name}${src.demo ? `<span class="t-demo">${escapeHtml(t('ui.demo'))}</span>` : ''}</div>`
      + `<div class="t-muted" style="margin-top:0">${escapeHtml(region(c.region))}</div>`
    const label = escapeHtml(t(`countries.metric.${metric}`))
    const body = v === null
      ? `<div class="t-row"><span class="t-label">${label}</span><span class="t-label">${escapeHtml(t('countries.noData'))}</span></div>`
      : `<div class="t-row"><span class="t-label">${label}${yr ? ` · ${escapeHtml(yr)}` : ''}</span><span class="t-val">${escapeHtml(fmtMetric(v, metric, lang, newsUnit))}</span></div>`
        + (src.name ? `<div class="t-muted">${escapeHtml(t('prov.source'))}: ${escapeHtml(src.name)}</div>` : '')
    return `${head}${body}<div class="t-sep t-cta">${escapeHtml(t('countries.clickHint'))} →</div>`
  }

  return (
    <Panel
      title={t(`countries.metricLong.${metric}`)}
      eyebrow={meta.years.length ? t('countries.mapYears', { list: meta.years.join(', ') }) : t(`countries.metric.${metric}`)}
      bodyClassName="!p-0"
      className="min-w-0"
      actions={
        <>
          {meta.is_demo && <DemoBadge />}
          <span className="text-[0.85rem] text-muted whitespace-nowrap">{t('countries.mapCountries', { n: values.length })}</span>
        </>
      }
      footer={
        values.length > 0 ? (
          <SourcesFooter
            sources={meta.sources}
            extra={<>{metric === 'news' ? t('countries.mapNoteNews') : t('countries.mapNote')} {t('countries.zoomHint')}</>}
          />
        ) : undefined
      }
    >
      <div className="relative">
        <WorldMap
          items={data.countries}
          styleKey={`${metric}|${values.length}|${values.reduce((a, b) => a + b, 0)}`}
          fillOf={(c) => colorFor(metricValue(c, metric), classes)}
          tooltipOf={tooltipOf}
          onSelect={(iso3) => navigate(`/paesi/${iso3}`)}
          height={560}
        />
        <div className="pointer-events-none absolute left-3 bottom-3 z-[500] rounded-sm border border-line bg-white/95 px-3 py-2 shadow-panel">
          <div className="eyebrow mb-1.5">{t(`countries.metric.${metric}`)}{metric !== 'news' ? ' · t' : ''}</div>
          <ul className="flex flex-col gap-1 text-[0.8rem] text-charcoal-soft">
            {classes && [...classes.lows].map((lo, i) => ({ lo, hi: classes.highs[i], color: classes.colors[i] })).reverse().map((c, i) => (
              <li key={i} className="flex items-center gap-2">
                <span className="inline-block h-3 w-5 rounded-[1px] border border-black/5" style={{ background: c.color }} />
                <span className="num">
                  {c.lo === c.hi ? fmtBound(c.lo, metric, lang) : `${fmtBound(c.lo, metric, lang)} – ${fmtBound(c.hi, metric, lang)}`}
                </span>
              </li>
            ))}
            <li className="flex items-center gap-2">
              <span className="inline-block h-3 w-5 rounded-[1px] border border-black/5" style={{ background: NO_DATA }} />
              <span>{t('countries.noDataLegend')}</span>
            </li>
          </ul>
        </div>
        {values.length === 0 && (
          <div className="absolute inset-x-0 top-6 z-[500] flex justify-center px-6">
            <div className="max-w-xl rounded-sm border border-line bg-white/95 px-4 shadow-panel">
              <DataMissing compact what={t('countries.mapEmpty')} providers={meta.providers}
                fallback={metric === 'production' ? t('countries.prod.fallback') : metric === 'news' ? t('countries.news.fallback') : t('countries.trade.fallback')} />
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}

export function fmtCount(n: number, lang: 'it' | 'en') {
  return fmtNumber(n, lang)
}
