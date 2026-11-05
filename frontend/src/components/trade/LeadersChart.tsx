// Horizontal bar chart: the top N countries of one flow for the selected year and metric.
import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DemoBadge, Panel, Segmented } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtNumber } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { AXIS_TICK, AXIS_TICK_MONO, fmtT, fmtUsd, fmtUv, GRID_STROKE, nameOf } from './bits'
import type { LeaderRow, LeadersResponse, TradeFlow, TradeMetric } from './types'

const TOP = 10

interface Datum { name: string; v: number; row: LeaderRow }

export function LeadersChart({ flow, onFlow, data, metric, year }: {
  flow: TradeFlow; onFlow: (f: TradeFlow) => void; data: LeadersResponse | undefined; metric: TradeMetric; year: number | null
}) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const rows: Datum[] = useMemo(() => (data?.rows ?? [])
    .filter((r) => (metric === 'volume' ? r.net_weight_kg : r.usd_value) !== null)
    .slice(0, TOP)
    .map((r) => ({
      name: nameOf(r, lang, country),
      v: metric === 'volume' ? (r.net_weight_kg ?? 0) / 1000 : (r.usd_value ?? 0) / 1e6,
      row: r,
    })), [data, metric, lang, country])
  const unit = metric === 'volume' ? t('trade.chart.unitT') : t('trade.chart.unitUsd')
  const height = Math.max(160, rows.length * 34 + 36)
  const mirror = data?.basis === 'mirror'

  return (
    <Panel
      title={t('trade.chart.title', { y: year ?? '—' })}
      eyebrow={`${t('trade.chart.top', { n: TOP, m: t(`trade.metric.${metric}`).toLowerCase() })} · ${unit}${mirror ? ` · ${t('trade.leaders.basis.mirror')}` : ''}`}
      className="min-w-0"
      actions={
        <>
          {rows.some((r) => r.row.is_demo) && <DemoBadge />}
          <Segmented size="sm" value={flow} onChange={onFlow} options={[
            { value: 'import', label: t('trade.chart.importers') },
            { value: 'export', label: t('trade.chart.exporters') },
          ]} />
        </>
      }
    >
      {rows.length === 0 ? (
        <div className="h-[200px] flex items-center justify-center text-muted border border-dashed border-line rounded-sm text-[0.95rem]">
          {t('ui.noData')}
        </div>
      ) : (
        <div style={{ height }} role="img" aria-label={t('trade.chart.title', { y: year ?? '' })}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 72, bottom: 0, left: 0 }} barCategoryGap={8}>
              <CartesianGrid stroke={GRID_STROKE} horizontal={false} />
              <XAxis type="number" tick={AXIS_TICK_MONO} tickLine={false} axisLine={{ stroke: '#DDD6C4' }}
                tickFormatter={(v: number) => fmtNumber(v, lang, metric === 'value' && v < 10 ? 1 : 0)} />
              <YAxis type="category" dataKey="name" width={150} tick={{ ...AXIS_TICK, fill: '#2B2D2A', fontSize: 14 }} tickLine={false} axisLine={false} interval={0} />
              <Tooltip cursor={{ fill: 'rgba(168,135,58,0.08)' }} isAnimationActive={false} wrapperStyle={{ outline: 'none' }}
                content={(p) => {
                  const d = p.payload?.[0]?.payload as Datum | undefined
                  if (!p.active || !d) return null
                  const r = d.row
                  return (
                    <div className="bg-white border border-line shadow-[0_4px_16px_rgba(31,33,32,0.10)] rounded-sm px-3 py-2 text-[0.85rem] min-w-[220px]">
                      <div className="font-serif font-semibold text-charcoal mb-1">{d.name}</div>
                      <div className="flex justify-between gap-4"><span className="text-muted">{t('trade.leaders.col.volume')}</span><span className="num">{fmtT(r.net_weight_kg, lang)} t</span></div>
                      <div className="flex justify-between gap-4"><span className="text-muted">{t('trade.leaders.col.value')}</span><span className="num">{fmtUsd(r.usd_value, lang)}</span></div>
                      <div className="flex justify-between gap-4"><span className="text-muted">{t('trade.leaders.col.uv')}</span><span className="num">{fmtUv(r.unit_value_usd_per_kg, lang)}</span></div>
                      <div className="mt-1 pt-1 border-t border-line-soft text-[0.75rem] text-muted">
                        {t('prov.source')}: {r.source ? (r.source.publisher || r.source.name) : r.sources_list?.map((s) => s.publisher || s.name).join(', ')} · {r.period_label}
                        {r.is_demo && <span className="ml-1"><DemoBadge /></span>}
                      </div>
                    </div>
                  )
                }}
              />
              <Bar dataKey="v" fill={flow === 'import' ? '#24604A' : '#A8873A'} radius={[0, 3, 3, 0]} maxBarSize={22} isAnimationActive={false}>
                <LabelList dataKey="v" position="right" offset={8}
                  formatter={(v: number) => fmtNumber(v, lang, metric === 'value' ? 1 : 0)}
                  style={{ fontSize: 13, fill: '#2B2D2A', fontFamily: '"IBM Plex Mono", monospace' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Panel>
  )
}
