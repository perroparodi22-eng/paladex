// Profile · Produzione: one chart + table per metric; one series per source and unit (never merged).
import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DemoBadge, FreshnessBadge, Panel, Segmented, SourceLine, StatusBadge } from '@/components/ui'
import { CorrectionBadge } from '@/components/corrections/CorrectionBadge'
import { FixValue } from '@/components/corrections/QuickFix'
import { AXIS_TICK, AXIS_TICK_MONO, DataMissing, GRID_STROKE, SERIES_COLORS } from '@/components/trade/bits'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtProdUnit } from '@/lib/format'
import { fmtMonthLong } from '@/components/trade/ytd'
import type { CountryProfile, ProductionMetric, ProductionPoint, ProductionSeries } from './types'

const TABLE_ROWS = 8

/** "ultimo anno FAO (il 2025 è previsto a dicembre 2026)": the newest year of a series whose source
 * publishes on a known calendar is the latest available, not an old figure. */
export function useNextRelease() {
  const { t, lang } = useI18n()
  return (s: Pick<ProductionSeries, 'next_release' | 'source'>): string | null => {
    const n = s.next_release
    if (!n) return null
    const fao = s.source?.key === 'faostat'
    const key = `countries.prod.${fao ? 'nextReleaseFao' : 'nextRelease'}${n.overdue ? 'Late' : ''}`
    return t(key, { n: n.year, m: fmtMonthLong(n.expected, lang) })
  }
}

export function ProfileProduction({ data }: { data: CountryProfile['production'] }) {
  const { t } = useI18n()
  const [sel, setSel] = useState<string | null>(null)
  const metric = data.metrics.find((m) => m.metric === sel) ?? data.metrics[0]
  const label = (m: string) => (t(`countries.prod.metric.${m}`) === `countries.prod.metric.${m}` ? m : t(`countries.prod.metric.${m}`))
  return (
    <Panel
      title={t('countries.prod.title')}
      eyebrow={t('countries.prod.eyebrow')}
      className="min-w-0"
      actions={
        <>
          {metric?.series.some((s) => s.is_demo) && <DemoBadge />}
          {data.metrics.length > 1 && (
            <Segmented size="sm" value={metric.metric} onChange={setSel}
              options={data.metrics.map((m) => ({ value: m.metric, label: label(m.metric) }))} />
          )}
        </>
      }
    >
      {!data.available || !metric ? (
        <DataMissing providers={data.providers} fallback={t('countries.prod.fallback')} what={t('countries.missing.production')} />
      ) : (
        <MetricView m={metric} title={label(metric.metric)} />
      )}
    </Panel>
  )
}

type Row = { label: string } & Record<string, number | ProductionPoint | string | null>

function MetricView({ m, title }: { m: ProductionMetric; title: string }) {
  const { t, lang } = useI18n()
  const nextRelease = useNextRelease()
  const keys = m.series.map((s, i) => `${s.source?.key ?? 's'}|${s.unit}|${i}`)
  const units = Array.from(new Set(m.series.map((s) => s.unit)))
  // Different units are never put on one axis: chart the first unit, list everything in the table.
  const charted = m.series.map((s, i) => ({ s, i })).filter(({ s }) => s.unit === units[0])
  const rows: Row[] = useMemo(() => {
    const by = new Map<string, Row>()
    charted.forEach(({ s, i }) => s.points.forEach((p) => {
      const r = by.get(p.period_label) ?? { label: p.period_label }
      r[keys[i]] = p.value
      r[`${keys[i]}__p`] = p
      by.set(p.period_label, r)
    }))
    return [...by.values()].sort((a, b) => (a.label < b.label ? -1 : 1))
  }, [charted, keys])
  const digits = (v: number) => (Math.abs(v) < 100 ? 1 : 0)
  const tableRows = m.series.flatMap((s, i) => s.points.map((p) => ({ p, s, i })))
    .sort((a, b) => (a.p.period_label < b.p.period_label ? 1 : a.p.period_label > b.p.period_label ? -1 : a.i - b.i))
    .slice(0, TABLE_ROWS)

  return (
    <div className="grid gap-5 2xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="min-w-0">
        {/* "Alveari" needs no unit after it; the others read "· t", "· kg per alveare", "· migliaia di BRL" */}
        <div className="eyebrow mb-1">{units[0] === 'number' ? title : `${title} · ${fmtProdUnit(units[0], lang)}`}</div>
        <div className="h-[250px]" role="img" aria-label={title}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 4 }} barGap={2}>
              <CartesianGrid stroke={GRID_STROKE} vertical={false} />
              <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: '#DDD6C4' }} />
              <YAxis width={64} tick={AXIS_TICK_MONO} tickLine={false} axisLine={false} tickFormatter={(v: number) => fmtNumber(v, lang, 0)} />
              <Tooltip
                isAnimationActive={false}
                cursor={{ fill: 'rgba(168,135,58,0.08)' }}
                wrapperStyle={{ outline: 'none' }}
                content={(p) => {
                  if (!p.active) return null
                  const row = rows.find((r) => r.label === p.label)
                  if (!row) return null
                  return (
                    <div className="bg-white border border-line shadow-[0_4px_16px_rgba(31,33,32,0.10)] rounded-sm px-3 py-2 text-[0.82rem] min-w-[220px]">
                      <div className="font-serif font-semibold text-charcoal mb-1">{row.label}</div>
                      {charted.map(({ s, i }) => {
                        const pt = row[`${keys[i]}__p`] as ProductionPoint | undefined
                        if (!pt) return null
                        return (
                          <div key={keys[i]} className="mb-1 last:mb-0">
                            <div className="flex items-baseline justify-between gap-3">
                              <span className="text-charcoal-soft truncate">{s.source?.publisher || s.source?.name}</span>
                              <span className="num text-charcoal">{fmtNumber(pt.value, lang, digits(pt.value))} {fmtProdUnit(pt.unit, lang)}</span>
                            </div>
                            <div className="flex items-center gap-1.5 text-[0.74rem] text-muted mt-0.5">
                              <StatusBadge status={pt.data_status ?? 'published'} />
                              {pt.published_at && <span>{t('prov.published')} {fmtDate(pt.published_at, lang)}</span>}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )
                }}
              />
              {charted.length > 1 && <Legend wrapperStyle={{ fontSize: 13 }} formatter={(v: string) => {
                const idx = keys.indexOf(v)
                return m.series[idx]?.source?.publisher || m.series[idx]?.source?.name || v
              }} />}
              {charted.map(({ i }) => (
                <Bar key={keys[i]} dataKey={keys[i]} fill={SERIES_COLORS[i % SERIES_COLORS.length]} radius={[3, 3, 0, 0]} maxBarSize={34} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-2 flex flex-col gap-1">
          {m.series.map((s, i) => (
            <div key={keys[i]} className="flex flex-wrap items-center gap-2">
              {m.series.length > 1 && <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />}
              <SourceLine p={{ source: s.source, published_at: s.latest.published_at, source_url: s.latest.source_url, is_demo: s.is_demo, correction: s.latest.correction }} />
              {s.freshness && <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />}
              {nextRelease(s) && <span className="text-[0.8rem] text-muted">· {nextRelease(s)}</span>}
            </div>
          ))}
          {m.series.length > 1 && <div className="text-[0.8rem] text-muted">{t('countries.prod.oneSource')}</div>}
        </div>
      </div>
      {/* Phones: with a "Fonte" column the table is wider than the panel; it scrolls inside its box. */}
      <div className="min-w-0 overflow-x-auto">
        <table className="w-full text-[0.92rem]">
          <thead>
            <tr className="border-b border-line text-left text-[0.82rem] text-muted">
              <th className="py-2 px-2 font-medium">{t('countries.prod.col.year')}</th>
              <th className="py-2 px-2 font-medium text-right">{t('countries.prod.col.value')}</th>
              <th className="py-2 px-2 font-medium">{t('countries.prod.col.status')}</th>
              {m.series.length > 1 && <th className="py-2 px-2 font-medium">{t('countries.prod.col.source')}</th>}
            </tr>
          </thead>
          <tbody>
            {tableRows.map(({ p, s, i }) => (
              <tr key={`${keys[i]}-${p.period_label}`} className="border-b border-line-soft last:border-0">
                <td className="py-1.5 px-2 num">{p.period_label}</td>
                <td className="py-1.5 px-2 num text-right whitespace-nowrap" title={p.flag_raw ? t('countries.prod.flag', { f: p.flag_raw }) : undefined}>
                  <FixValue correction={p.correction} figure={p.row_id && !p.is_demo ? {
                    table: 'production_stats', row_id: p.row_id, value: p.value, unit: p.unit, currency: null,
                    label: `${title} · ${p.period_label} · ${s.source?.publisher || s.source?.name || ''}`,
                    period_label: p.period_label,
                  } : null}>
                    <span>{fmtNumber(p.value, lang, digits(p.value))} <span className="text-muted text-[0.8em]">{fmtProdUnit(p.unit, lang)}</span></span>
                  </FixValue>
                </td>
                <td className="py-1.5 px-2">
                  <StatusBadge status={p.data_status ?? 'published'} />
                  {p.correction && <span className="ml-2 inline-block align-middle"><CorrectionBadge c={p.correction} compact /></span>}
                </td>
                {m.series.length > 1 && (
                  <td className="py-1.5 px-2 text-[0.82rem] text-muted" title={s.source?.publisher || s.source?.name}>
                    {/* max-width does not apply to a table cell itself, only to a block inside it */}
                    <div className="max-w-[140px] truncate">{s.source?.publisher || s.source?.name}</div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
