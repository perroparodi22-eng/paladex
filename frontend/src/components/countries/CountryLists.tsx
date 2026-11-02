// Beside the map: the 20 priority countries. Below it: every other country with collected data.
import clsx from 'clsx'
import { Link } from 'react-router-dom'
import { DemoBadge, Panel } from '@/components/ui'
import { BasisMarks, fmtT } from '@/components/trade/bits'
import { useI18n } from '@/i18n'
import { fmtNumber } from '@/lib/format'
import { fmtMetric, metricSource, metricValue, metricYear } from './metrics'
import { AvailabilityIcons, AvailabilityLegend, countryName, useRegion } from './parts'
import type { CountriesResponse, CountryListItem, MapMetric } from './types'

function sortByMetric(list: CountryListItem[], metric: MapMetric, lang: 'it' | 'en') {
  return [...list].sort((a, b) => {
    const va = metricValue(a, metric)
    const vb = metricValue(b, metric)
    if (va === null && vb === null) return countryName(a, lang).localeCompare(countryName(b, lang))
    if (va === null) return 1
    if (vb === null) return -1
    return vb - va
  })
}

export function PriorityList({ data, metric }: { data: CountriesResponse; metric: MapMetric }) {
  const { t, lang } = useI18n()
  const region = useRegion()
  const rows = sortByMetric(data.countries.filter((c) => c.priority), metric, lang)
  const newsUnit = t('countries.unit.news')
  const anyDemo = rows.some((c) => metricValue(c, metric) !== null && metricSource(c, metric).demo)
  return (
    <Panel title={t('countries.priority.title')} eyebrow={t('countries.priority.eyebrow')} bodyClassName="!p-0" className="min-w-0"
      actions={anyDemo ? <DemoBadge /> : undefined}
      footer={
        <div className="flex flex-col gap-1.5">
          <span>{t('countries.priority.sortedBy', { m: t(`countries.metric.${metric}`) })}</span>
          <AvailabilityLegend />
        </div>
      }>
      <ol>
        {rows.map((c, i) => {
          const v = metricValue(c, metric)
          const yr = metricYear(c, metric)
          const src = metricSource(c, metric)
          const h = metric === 'exports' ? c.metrics.exports : metric === 'imports' ? c.metrics.imports : null
          const title = [`${countryName(c, lang)} · ${region(c.region)}`, src.name && `${t('prov.source')}: ${src.name}`].filter(Boolean).join('\n')
          return (
            <li key={c.iso3} className="border-b border-line-soft last:border-0">
              <Link to={`/paesi/${c.iso3}`} title={title}
                className="grid grid-cols-[1.3rem_minmax(0,1fr)_auto_6.4rem] items-center gap-x-2 px-4 py-[0.38rem] hover:bg-ivory/60 group">
                <span className="num text-[0.75rem] text-muted">{i + 1}</span>
                <span className="truncate text-[0.97rem] text-charcoal group-hover:text-forest-800">{countryName(c, lang)}</span>
                <AvailabilityIcons a={c.available} keys={LIST_KEYS} size="sm" />
                <span className={clsx('text-right num whitespace-nowrap', v === null ? 'text-muted' : 'text-charcoal')}>
                  {v === null ? <span className="font-sans text-[0.8rem]">{t('countries.noData')}</span> : (
                    <>
                      <span className="text-[0.95rem]">{fmtMetric(v, metric, lang, newsUnit)}</span>
                      {h && <BasisMarks summedPartners={h.summed_from_partners} partners={h.partners_count} summedMonths={h.summed_from_months} />}
                      {yr && <span className="block text-[0.7rem] leading-none text-muted">{yr}</span>}
                    </>
                  )}
                </span>
              </Link>
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}

const LIST_KEYS = ['production', 'exports', 'imports', 'prices', 'news', 'regulations'] as const

export function OtherCountries({ data, metric }: { data: CountriesResponse; metric: MapMetric }) {
  const { t, lang } = useI18n()
  const region = useRegion()
  const has = (c: CountryListItem) => {
    const a = c.available
    return a.production || a.exports || a.imports || a.prices || a.news || a.regulations
  }
  const rows = sortByMetric(data.countries.filter((c) => !c.priority && has(c)), metric, lang)
  if (!rows.length) return null
  const anySummed = rows.some((c) => c.metrics.exports?.summed_from_partners || c.metrics.imports?.summed_from_partners)
  return (
    <Panel title={t('countries.others.title')} bodyClassName="!p-0" className="min-w-0"
      actions={rows.some((c) => c.metrics.production?.is_demo || c.metrics.exports?.is_demo || c.metrics.imports?.is_demo) ? <DemoBadge /> : undefined}
      footer={anySummed ? t('countries.summed') : undefined}>
      <div className="overflow-x-auto">
      <table className="table-clean">
        <thead>
          <tr>
            <th>{t('countries.col.country')}</th>
            <th className="!text-right">{t('countries.metric.exports')} (t)</th>
            <th className="!text-right">{t('countries.metric.imports')} (t)</th>
            <th className="!text-right">{t('countries.metric.production')} (t)</th>
            <th className="!text-right">{t('countries.metric.news')}</th>
            <th>{t('countries.col.data')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const m = c.metrics
            return (
              <tr key={c.iso3}>
                <td>
                  <Link to={`/paesi/${c.iso3}`} className="link no-underline hover:underline">{countryName(c, lang)}</Link>
                  <div className="text-[0.75rem] text-muted">{region(c.region)}</div>
                </td>
                <td className="num text-right" title={m.exports ? `${m.exports.year}` : undefined}>
                  {fmtT(m.exports?.net_weight_kg, lang)}{m.exports && <BasisMarks summedPartners={m.exports.summed_from_partners} partners={m.exports.partners_count} />}
                </td>
                <td className="num text-right" title={m.imports ? `${m.imports.year}` : undefined}>
                  {fmtT(m.imports?.net_weight_kg, lang)}{m.imports && <BasisMarks summedPartners={m.imports.summed_from_partners} partners={m.imports.partners_count} />}
                </td>
                <td className="num text-right" title={m.production?.period_label ?? undefined}>{m.production ? fmtNumber(m.production.value_t, lang) : '—'}</td>
                <td className="num text-right">{m.news_30d ? fmtNumber(m.news_30d.count, lang) : '—'}</td>
                <td><AvailabilityIcons a={c.available} keys={LIST_KEYS} size="sm" /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
      </div>
    </Panel>
  )
}
