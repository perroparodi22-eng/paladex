// Map legend and what it says about the data (no Leaflet here, so it renders and tests anywhere):
// fixed classes with counts, the hatched "old figure" entry, the year basis and the mix of sources.
import { useI18n } from '@/i18n'
import { fmtNumber } from '@/lib/format'
import {
  classIndex, colorFor, fixedClasses, isOld, NO_DATA, OLD_AFTER_YEARS, OLD_BASE, OLD_FILL, OLD_PATTERN_ID,
  OLD_STRIPE, OLD_SWATCH_CSS,
} from './choropleth'
import { fmtClassRange, metricSourceBrief, metricValue, metricYearNum, shortSourceName } from './metrics'
import type { CountryListItem, MapMetric } from './types'

const LEGEND_SOURCES = 4

/** The hatch used as fill for old figures; referenced by the map's SVG paths as url(#…). */
export function OldDataPattern() {
  return (
    <svg width="0" height="0" aria-hidden="true" style={{ position: 'absolute' }}>
      <defs>
        <pattern id={OLD_PATTERN_ID} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill={OLD_BASE} />
          <rect width="1.6" height="6" fill={OLD_STRIPE} />
        </pattern>
      </defs>
    </svg>
  )
}

export interface MapSummary {
  /** countries with a figure */
  count: number
  /** newest year among the figures (null for news) */
  newest: number | null
  /** countries per class (current figures only), class 0 = lowest */
  classCounts: number[]
  /** current figures per year, newest first */
  years: { year: number; n: number }[]
  /** old figures: how many and which years */
  old: { n: number; from: number | null; to: number | null }
  /** countries per source (short name), most used first */
  sources: { name: string; n: number }[]
}

/** What the legend says about the data on the map (pure, tested). */
export function summarize(items: CountryListItem[], metric: MapMetric, lang: 'it' | 'en'): MapSummary {
  const classes = fixedClasses(metric)
  const rows = items.map((c) => ({ c, v: metricValue(c, metric), y: metricYearNum(c, metric) })).filter((r) => r.v !== null)
  const years = rows.map((r) => r.y).filter((y): y is number => y !== null)
  const newest = years.length ? Math.max(...years) : null
  const current = rows.filter((r) => !isOld(r.y, newest))
  const old = rows.filter((r) => isOld(r.y, newest))
  const classCounts = classes.colors.map(() => 0)
  for (const r of current) classCounts[classIndex(r.v as number, classes)] += 1
  const byYear = new Map<number, number>()
  for (const r of current) if (r.y !== null) byYear.set(r.y, (byYear.get(r.y) ?? 0) + 1)
  const oldYears = old.map((r) => r.y as number)
  const bySource = new Map<string, number>()
  if (metric !== 'news') {
    for (const r of rows) {
      const name = shortSourceName(metricSourceBrief(r.c, metric), lang)
      bySource.set(name, (bySource.get(name) ?? 0) + 1)
    }
  }
  return {
    count: rows.length,
    newest,
    classCounts,
    years: [...byYear.entries()].sort((a, b) => b[0] - a[0]).map(([year, n]) => ({ year, n })),
    old: { n: old.length, from: oldYears.length ? Math.min(...oldYears) : null, to: oldYears.length ? Math.max(...oldYears) : null },
    sources: [...bySource.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name, n]) => ({ name, n })),
  }
}

/** Fill of one country on the map: grey without data, hatched when old, else its class colour. */
export function fillFor(c: CountryListItem, metric: MapMetric, newest: number | null): string {
  const v = metricValue(c, metric)
  if (v === null) return NO_DATA
  if (isOld(metricYearNum(c, metric), newest)) return OLD_FILL
  return colorFor(v, fixedClasses(metric))
}

export function MapLegend({ metric, summary }: { metric: MapMetric; summary: MapSummary }) {
  const { t, lang } = useI18n()
  const classes = fixedClasses(metric)
  // lowest class first: the strip reads left to right like the ramp
  const items = classes.colors.map((color, i) => ({ color, lo: classes.lows[i], hi: classes.highs[i], n: summary.classCounts[i] }))
  const cut = summary.newest !== null ? summary.newest - OLD_AFTER_YEARS : null
  const swatch = 'inline-block h-3 w-5 shrink-0 rounded-[1px] border'
  // Under the map, not over it: an overlay hid South America (Argentina, Brazil, Uruguay).
  return (
    <div className="border-t border-line-soft px-4 py-2.5" data-map-legend>
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[0.8rem] text-charcoal-soft">
        <li className="eyebrow">{t(`countries.metric.${metric}`)}{metric !== 'news' ? ' · t' : ''}</li>
        {items.map((c, i) => (
          <li key={i} className="flex items-center gap-1.5" title={t('countries.legend.countTitle', { n: c.n })}>
            <span className={`${swatch} border-black/5`} style={{ background: c.color }} />
            <span className="num whitespace-nowrap">{fmtClassRange(c.lo, c.hi, metric, lang)}</span>
            <span className="num text-muted">({c.n})</span>
          </li>
        ))}
        {cut !== null && summary.old.n > 0 && (
          <li className="flex items-center gap-1.5" data-legend="old">
            <span className={`${swatch} border-black/10`} style={{ background: OLD_SWATCH_CSS }} />
            <span className="whitespace-nowrap">{t('countries.legend.old', { y: cut })}</span>
            <span className="num text-muted">({summary.old.n})</span>
          </li>
        )}
        <li className="flex items-center gap-1.5">
          <span className={`${swatch} border-black/5`} style={{ background: NO_DATA }} />
          <span>{t('countries.noDataLegend')}</span>
        </li>
      </ul>
    </div>
  )
}

/** Under the map: which years the colours stand for, and which sources they come from. */
export function MapBasis({ summary }: { summary: MapSummary }) {
  const { t, lang } = useI18n()
  if (!summary.years.length && !summary.sources.length) return null
  const shown = summary.sources.slice(0, LEGEND_SOURCES)
  const rest = summary.sources.slice(LEGEND_SOURCES)
  const restN = rest.reduce((a, s) => a + s.n, 0)
  return (
    <div className="flex flex-col gap-0.5 px-4 pb-2.5 text-[0.8rem] text-muted" data-map-basis>
      {summary.years.length > 0 && (
        <div>
          <span className="font-medium text-charcoal-soft">{t('countries.legend.years')}:</span>{' '}
          {summary.years.map((y, i) => (
            <span key={y.year} className="num">{i > 0 ? ' · ' : ''}{y.year} ({t(y.n === 1 ? 'countries.legend.nOne' : 'countries.legend.n', { n: fmtNumber(y.n, lang) })})</span>
          ))}
          {summary.old.n > 0 && summary.old.from !== null && (
            <span>{' · '}{t(summary.old.n === 1 ? 'countries.legend.oldYearsOne' : 'countries.legend.oldYears', {
              n: summary.old.n, r: summary.old.from === summary.old.to ? String(summary.old.from) : `${summary.old.from}–${summary.old.to}`,
            })}</span>
          )}
        </div>
      )}
      {summary.sources.length > 0 && (
        <div>
          <span className="font-medium text-charcoal-soft">{t('countries.legend.sources')}:</span>{' '}
          {shown.map((s, i) => <span key={s.name}>{i > 0 ? ' · ' : ''}{s.name} <span className="num">({s.n})</span></span>)}
          {rest.length > 0 && <span>{' · '}{t('countries.legend.moreSources', { k: rest.length, n: restN })}</span>}
        </div>
      )}
    </div>
  )
}
