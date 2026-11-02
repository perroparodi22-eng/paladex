// Trade volume over time: one line per source (never summed or averaged across sources).
import { useMemo } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DemoBadge, FreshnessBadge, Note, SourceLine, StatusBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtPeriod } from '@/lib/format'
import { AXIS_TICK, AXIS_TICK_MONO, fmtT, fmtUv, GRID_STROKE, SERIES_COLORS } from './bits'
import type { SeriesPoint, SeriesResponse } from './types'

type Row = { label: string } & Record<string, number | SeriesPoint | string | null>

export function SeriesChart({ data, height = 300 }: { data: SeriesResponse; height?: number }) {
  const { t, lang } = useI18n()
  const series = data.series
  const keys = series.map((s, i) => s.source?.key ?? `s${i}`)

  const rows: Row[] = useMemo(() => {
    const by = new Map<string, Row>()
    series.forEach((s, i) => {
      for (const p of s.points) {
        const r = by.get(p.period_label) ?? { label: p.period_label }
        r[keys[i]] = p.net_weight_kg === null ? null : p.net_weight_kg / 1000
        r[`${keys[i]}__p`] = p
        by.set(p.period_label, r)
      }
    })
    return [...by.values()].sort((a, b) => (a.label < b.label ? -1 : 1))
  }, [series, keys])

  const monthly = data.freq === 'M'
  const tick = (v: string) => (monthly ? fmtPeriod(v, lang) : v)

  return (
    <div>
      <div style={{ height }} role="img" aria-label={t('trade.series.title')}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 4 }}>
            <CartesianGrid stroke={GRID_STROKE} vertical={false} />
            <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: '#DDD6C4' }} tickFormatter={tick} minTickGap={16} />
            <YAxis width={64} tick={AXIS_TICK_MONO} tickLine={false} axisLine={false}
              tickFormatter={(v: number) => fmtNumber(v, lang, v < 10 && v !== 0 ? 1 : 0)} />
            <Tooltip
              isAnimationActive={false}
              wrapperStyle={{ outline: 'none', zIndex: 20 }}
              cursor={{ stroke: '#A8873A', strokeWidth: 1, strokeDasharray: '3 3' }}
              content={(p) => {
                if (!p.active) return null
                const row = rows.find((r) => r.label === p.label)
                if (!row) return null
                const items = series.map((s, i) => ({ s, i, pt: row[`${keys[i]}__p`] as SeriesPoint | undefined })).filter((x) => x.pt)
                if (!items.length) return null
                return (
                  <div className="bg-white border border-line shadow-[0_4px_16px_rgba(31,33,32,0.10)] rounded-sm px-3 py-2.5 min-w-[260px] max-w-[360px]">
                    <div className="flex items-center justify-between gap-3 mb-1.5">
                      <span className="font-serif font-semibold text-charcoal">{tick(row.label)}</span>
                      {items.some((x) => x.pt!.is_demo) && <DemoBadge />}
                    </div>
                    {items.map(({ s, i, pt }) => (
                      <div key={keys[i]} className="text-[0.82rem] leading-snug mb-1 last:mb-0">
                        <div className="flex items-baseline gap-2">
                          <span className="inline-block h-2 w-2 rounded-full self-center" style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
                          <span className="flex-1 truncate text-charcoal-soft">{s.source?.publisher || s.source?.name}</span>
                          <span className="num text-charcoal text-[0.92rem]">{fmtT(pt!.net_weight_kg, lang)} t</span>
                        </div>
                        <div className="pl-4 text-[0.74rem] text-muted">
                          {pt!.unit_value_usd_per_kg !== null && <span>{t('trade.series.uv', { v: fmtUv(pt!.unit_value_usd_per_kg, lang) })} · </span>}
                          {pt!.summed_from_partners && <span>{t('trade.series.summedPartners')} · </span>}
                          {pt!.summed_from_months && <span>{t('trade.series.summedMonths')} · </span>}
                          {pt!.published_at && <span>{t('prov.published')} {fmtDate(pt!.published_at, lang)}</span>}
                          {pt!.data_status && !['published', 'live', 'demo'].includes(pt!.data_status) && <span className="ml-1"><StatusBadge status={pt!.data_status} /></span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )
              }}
            />
            {series.map((_, i) => (
              <Line key={keys[i]} type="linear" dataKey={keys[i]} stroke={SERIES_COLORS[i % SERIES_COLORS.length]} strokeWidth={2}
                dot={{ r: rows.length > 24 ? 0 : 3, strokeWidth: 0, fill: SERIES_COLORS[i % SERIES_COLORS.length] }}
                activeDot={{ r: 4.5, stroke: '#fff', strokeWidth: 2 }} connectNulls={false} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 flex flex-col gap-1">
        {series.map((s, i) => {
          const last = s.points[s.points.length - 1]
          return (
            <div key={keys[i]} className="flex flex-wrap items-center gap-2">
              <span className="inline-block h-[3px] w-4 rounded-full" style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
              <SourceLine p={{ source: s.source, published_at: last?.published_at, source_url: last?.source_url, is_demo: s.is_demo, period_label: last?.period_label }} />
              {s.freshness && <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />}
            </div>
          )
        })}
        {series.length > 1 && <div className="text-[0.8rem] text-muted">{t('trade.series.oneLinePerSource')}</div>}
        {data.excluded_partial.length > 0 && (
          <div className="text-[0.8rem] text-muted">
            {t('trade.series.excluded', { list: data.excluded_partial.map((e) => t('trade.series.excludedItem', { y: e.period_label, n: e.months_count })).join(', ') })}
          </div>
        )}
        {data.discrepancies.length > 0 && (
          <div className="mt-1"><Note tone="warn">{t('trade.series.discrepancy', { list: data.discrepancies.map((d) => tick(d.period_label)).join(', ') })}</Note></div>
        )}
      </div>
    </div>
  )
}
