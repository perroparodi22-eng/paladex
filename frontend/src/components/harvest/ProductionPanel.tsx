// Production by country (official statistics): table of the latest year with the change on the year
// before and the status the source gives, and the selected country's series (one source at a time).
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ExternalLink } from 'lucide-react'
import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ProductionMetric, ProductionPoint } from '@/components/countries/types'
import { AXIS_TICK, AXIS_TICK_MONO, DataMissing, GRID_STROKE, SourcesFooter, YoY } from '@/components/trade/bits'
import { Badge, DemoBadge, ErrorBlock, FreshnessBadge, Loading, Panel, Segmented, SourceLine } from '@/components/ui'
import { FixValue } from '@/components/corrections/QuickFix'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate, fmtNumber, fmtProdUnit } from '@/lib/format'
import type { ProductionCountry, ProductionCountryResponse, ProductionResponse, ProductionValue } from './types'
import type { ProdScope, YearsRange } from './useHarvestParams'
import { pageUrl } from '@/lib/links'

/** Fill of a production bar by status: official figure (forest), estimate (gold), provisional (pale gold),
 * forecast (white, dashed outline). The same marks as the page's reading guide. */
export const PROD_STATUS_STYLE: Record<string, { fill: string; stroke: string; dash?: string }> = {
  published: { fill: '#24604A', stroke: '#24604A' },
  estimate: { fill: '#C9A85A', stroke: '#7D6428' },
  provisional: { fill: '#F1E7CC', stroke: '#A8873A' },
  forecast: { fill: '#FFFFFF', stroke: '#7D6428', dash: '4 2' },
}

export function ProdStatus({ status, flag, notes }: { status: string; flag?: string | null; notes?: string | null }) {
  const { t } = useI18n()
  const known = ['published', 'estimate', 'provisional', 'forecast'].includes(status)
  const tone = status === 'published' ? 'forest' : status === 'demo' ? 'demo' : 'gold'
  return (
    <Badge tone={tone} title={[flag ? t('harvest.prod.flag', { f: flag }) : null, notes].filter(Boolean).join(' · ') || undefined}>
      {known ? t(`harvest.prod.status.${status}`) : status}{flag ? ` · ${flag}` : ''}
    </Badge>
  )
}

function fmtProd(v: ProductionValue, lang: 'it' | 'en', unitT: string): string {
  const u = (v.unit || '').toLowerCase()
  if (u === 't' || u === 'tonnes' || u === 'tonne') return `${fmtNumber(v.value, lang, v.value < 100 ? 1 : 0)} ${unitT}`
  if (u === 'kg') return `${fmtNumber(v.value / 1000, lang, 0)} ${unitT}`
  return `${fmtNumber(v.value, lang, 0)} ${v.unit}`
}

export function ProductionTable({ data, selected, onSelect, scope, onScope }: {
  data: ProductionResponse; selected: string; onSelect: (iso3: string) => void; scope: ProdScope; onScope: (s: ProdScope) => void
}) {
  const { t } = useI18n()
  const latestYear = data.years.length ? data.years[data.years.length - 1] : null
  return (
    <div className="min-w-0">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Segmented size="sm" value={scope} onChange={onScope}
          options={[{ value: 'monitored', label: `${t('harvest.prod.monitored')} (${data.monitored_with_data})` },
            { value: 'all', label: `${t('harvest.prod.all')} (${data.countries_with_data})` }]} />
      </div>
      {latestYear !== null && <p className="mb-2 text-[0.82rem] text-muted">{t('harvest.prod.lag', { year: latestYear })}</p>}
      <div className={clsx('overflow-x-auto', scope === 'all' && 'max-h-[560px] overflow-y-auto')}>
        <table className="w-full min-w-[470px] text-[0.9rem]">
          <thead className="sticky top-0 z-[1]">
            <tr className="border-b border-line text-left text-[0.82rem] text-muted">
              <th className="py-2 px-2 font-medium">{t('harvest.prod.col.country')}</th>
              <th className="py-2 px-2 font-medium">{t('harvest.prod.col.year')}</th>
              <th className="py-2 px-2 font-medium text-right">{t('harvest.prod.col.value')}</th>
              <th className="py-2 px-2 font-medium text-right">{t('harvest.prod.col.change')}</th>
              <th className="py-2 px-2 font-medium">{t('harvest.prod.col.status')}</th>
            </tr>
          </thead>
          <tbody>
            {data.countries.map((c) => (
              <ProdRow key={c.iso3} c={c} selected={c.iso3 === selected} onSelect={onSelect} mainSource={data.sources[0]?.key} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[0.8rem] text-muted">{t('harvest.prod.pickHint')}</p>
      {data.sources.length > 0 && <div className="mt-2 border-t border-line-soft pt-2"><SourcesFooter sources={data.sources} /></div>}
    </div>
  )
}

function ProdRow({ c, selected, onSelect, mainSource }: {
  c: ProductionCountry; selected: boolean; onSelect: (iso3: string) => void; mainSource: string | undefined
}) {
  const { t, lang } = useI18n()
  const s = c.series[0]
  const v = s?.latest
  const name = (lang === 'it' ? c.name_it ?? c.name_en : c.name_en ?? c.name_it) ?? c.iso3
  return (
    <tr className={clsx('border-b border-line-soft align-top', selected && 'bg-gold-pale/40')} aria-current={selected ? 'true' : undefined}>
      <td className="py-1.5 px-2">
        <button type="button" className="link text-left" onClick={() => onSelect(c.iso3)}>{name}</button>
        {c.is_demo && <span className="ml-1"><DemoBadge /></span>}
        {c.series.length > 1 && <div className="text-[0.72rem] text-muted">{t('harvest.prod.otherSources', { n: c.series.length - 1 })}</div>}
      </td>
      <td className="py-1.5 px-2 num">{v?.period_label ?? '—'}</td>
      <td className="py-1.5 px-2 num text-right whitespace-nowrap">
        {v ? (
          <FixValue correction={v.correction} figure={v.row_id && !v.is_demo ? {
            table: 'production_stats', row_id: v.row_id, value: v.value, unit: v.unit, currency: null,
            label: `${name} · ${v.period_label} · ${s?.source?.publisher || s?.source?.name || ''}`, country_iso3: c.iso3, period_label: v.period_label,
          } : null}><span>{fmtProd(v, lang, t('harvest.prod.unitT'))}</span></FixValue>
        ) : '—'}
        {v?.source_url && (
          <a href={pageUrl(v.source_url) ?? undefined} target="_blank" rel="noreferrer" className="ml-1 inline-block align-[-1px] text-forest-700"
            title={`${t('prov.original')} · ${s?.source?.name ?? ''}`} aria-label={t('prov.original')}>
            <ExternalLink size={12} />
          </a>
        )}
        {s?.forecast && (
          <div className="text-[0.72rem] text-gold-dark">
            {t('harvest.prod.forecast', { year: s.forecast.year, value: fmtProd(s.forecast, lang, t('harvest.prod.unitT')) })}
          </div>
        )}
      </td>
      <td className="py-1.5 px-2 text-right">
        <YoY pct={s?.change_pct} title={s?.previous && v ? t('harvest.prod.changeTitle', { year: v.year, prev: s.previous.year }) : t('harvest.prod.noPrev')} />
      </td>
      <td className="py-1.5 px-2">
        {v && <ProdStatus status={v.data_status} flag={v.flag_raw} notes={v.notes} />}
        {s?.source && s.source.key !== mainSource && (
          <div className="mt-0.5 max-w-[160px] truncate text-[0.72rem] text-muted">{s.source.publisher || s.source.name}</div>
        )}
      </td>
    </tr>
  )
}

type Row = { label: string; value: number; p: ProductionPoint }

export function ProductionChart({ iso3, metric, years, onMetric, onYears }: {
  iso3: string; metric: string; years: YearsRange; onMetric: (m: string) => void; onYears: (y: YearsRange) => void
}) {
  const { t, lang } = useI18n()
  const q = useQuery({
    queryKey: ['harvest', 'production', 'country', iso3],
    queryFn: () => api.get<ProductionCountryResponse>(`/harvest/production/${iso3}`),
    enabled: Boolean(iso3),
  })
  if (!iso3) return <p className="text-muted">{t('harvest.prod.pickHint')}</p>
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
  const d = q.data
  if (!d || !d.metrics.length) return <p className="py-6 text-muted">{t('harvest.prod.noChart')}</p>
  const m: ProductionMetric = d.metrics.find((x) => x.metric === metric) ?? d.metrics[0]
  const name = (lang === 'it' ? d.name_it : d.name_en) ?? iso3
  const metricLabel = (k: string) => (t(`harvest.prod.metric.${k}`) === `harvest.prod.metric.${k}` ? k : t(`harvest.prod.metric.${k}`))
  return (
    <div className="min-w-0">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="font-serif text-[1.05rem] font-semibold text-charcoal">
          {/* the title names the figure on screen: production, hives, yield, value (IBGE, R$)… */}
          {m.metric === 'production' ? t('harvest.prod.chartTitle', { country: name })
            : m.metric === 'colonies' ? t('harvest.prod.chartColonies', { country: name })
              : t('harvest.prod.chartMetric', { country: name, metric: metricLabel(m.metric).toLocaleLowerCase(lang === 'it' ? 'it-IT' : 'en-GB') })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {d.metrics.length > 1 && (
            <Segmented size="sm" value={m.metric} onChange={onMetric} options={d.metrics.map((x) => ({ value: x.metric, label: metricLabel(x.metric) }))} />
          )}
          <Segmented size="sm" value={years} onChange={onYears}
            options={[{ value: '20', label: t('harvest.prod.years.20') }, { value: 'all', label: t('harvest.prod.years.all') }]} />
        </div>
      </div>
      {/* one chart per source: never summed or mixed */}
      {m.series.map((s, i) => <SeriesChart key={`${s.source?.key}-${s.unit}-${i}`} s={s} years={years} />)}
      {m.series.length > 1 && <p className="mt-1 text-[0.8rem] text-muted">{t('harvest.prod.oneSource')}</p>}
    </div>
  )
}

function SeriesChart({ s, years }: { s: ProductionMetric['series'][number]; years: YearsRange }) {
  const { t, lang } = useI18n()
  const rows: Row[] = useMemo(() => {
    const all = s.points.map((p) => ({ label: p.period_label, value: p.value, p }))
    return years === 'all' ? all : all.slice(-20)
  }, [s, years])
  const statuses = Array.from(new Set(rows.map((r) => r.p.data_status ?? 'published')))
  const digits = (v: number) => (Math.abs(v) < 100 ? 1 : 0)
  return (
    <div className="mb-3 min-w-0">
      <div className="eyebrow mb-1">{s.source?.publisher || s.source?.name} · {fmtProdUnit(s.unit, lang)}</div>
      <div className="h-[230px]" role="img" aria-label={`${s.source?.name ?? ''} · ${fmtProdUnit(s.unit, lang)}`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID_STROKE} vertical={false} />
            <XAxis dataKey="label" tick={{ ...AXIS_TICK, fontSize: 11 }} tickLine={false} axisLine={{ stroke: '#DDD6C4' }} minTickGap={6} />
            <YAxis width={58} tick={{ ...AXIS_TICK_MONO, fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => fmtNumber(v, lang, 0)} />
            <Tooltip
              isAnimationActive={false}
              cursor={{ fill: 'rgba(168,135,58,0.08)' }}
              content={(p) => {
                if (!p.active || !p.payload?.length) return null
                const r = p.payload[0].payload as Row
                return (
                  <div className="min-w-[200px] rounded-sm border border-line bg-white px-3 py-2 text-[0.82rem] shadow-[0_4px_16px_rgba(31,33,32,0.10)]">
                    <div className="font-serif font-semibold text-charcoal">{r.label}</div>
                    <div className="num text-charcoal">{fmtNumber(r.value, lang, digits(r.value))} {fmtProdUnit(s.unit, lang)}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <ProdStatus status={r.p.data_status ?? 'published'} flag={r.p.flag_raw} />
                      {r.p.published_at && <span className="text-muted">{t('prov.published')} {fmtDate(r.p.published_at, lang)}</span>}
                    </div>
                  </div>
                )
              }}
            />
            <Bar dataKey="value" isAnimationActive={false} maxBarSize={30} radius={[2, 2, 0, 0]}>
              {rows.map((r) => {
                const st = PROD_STATUS_STYLE[r.p.data_status ?? 'published'] ?? PROD_STATUS_STYLE.published
                return <Cell key={r.label} fill={st.fill} stroke={st.stroke} strokeDasharray={st.dash} />
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.78rem] text-muted">
        {statuses.map((st) => {
          const style = PROD_STATUS_STYLE[st] ?? PROD_STATUS_STYLE.published
          return (
            <span key={st} className="inline-flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-4 rounded-[1px]" style={{ background: style.fill, border: `1px ${style.dash ? 'dashed' : 'solid'} ${style.stroke}` }} />
              {t(`harvest.prod.status.${st}`)}
            </span>
          )
        })}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <SourceLine p={{ source: s.source, published_at: s.latest.published_at, source_url: s.latest.source_url, is_demo: s.is_demo }} />
        {s.freshness && <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />}
      </div>
    </div>
  )
}

export function ProductionPanel({ country, scope, metric, years, onCountry, onScope, onMetric, onYears }: {
  country: string; scope: ProdScope; metric: string; years: YearsRange
  onCountry: (iso3: string) => void; onScope: (s: ProdScope) => void; onMetric: (m: string) => void; onYears: (y: YearsRange) => void
}) {
  const { t } = useI18n()
  const q = useQuery({
    queryKey: ['harvest', 'production', scope],
    queryFn: () => api.get<ProductionResponse>('/harvest/production', { scope }),
  })
  const d = q.data
  // the chart follows the page's country, else the first country of the table
  const chartIso = d && d.countries.some((c) => c.iso3 === country) ? country : d?.countries[0]?.iso3 ?? country
  return (
    <Panel title={t('harvest.prod.title')} eyebrow={t('harvest.prod.eyebrow')} className="min-w-0">
      {q.isLoading ? <Loading /> : q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} /> : d && !d.available ? (
        <DataMissing providers={d.providers} fallback={t('harvest.prod.fallback')} what={t('harvest.prod.missing')} />
      ) : d ? (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <ProductionTable data={d} selected={chartIso} onSelect={onCountry} scope={scope} onScope={onScope} />
          <ProductionChart iso3={chartIso} metric={metric} years={years} onMetric={onMetric} onYears={onYears} />
        </div>
      ) : null}
    </Panel>
  )
}
