// Main price chart: one line per series for ONE price type, optional low–high bands,
// hover tooltip with value, period, source and publication date, clickable legend.
import clsx from 'clsx'
import { useMemo, useState } from 'react'
import {
  Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { DemoBadge, FreshnessBadge, Note, Panel, SourceLine } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber } from '@/lib/format'
import type { Lang } from '@/lib/types'
import { Swatch } from './bits'
import type { Freq, MassUnit, PricePoint, PriceSeries, SeriesResponse } from './types'
import { fmtPeriodLabel, fmtPrice, MAX_VISIBLE, toUnit, unitLabel } from './utils'

type Row = { x: number; label: string } & Record<string, unknown>

const STEP: Record<Freq, number> = { M: 1, Q: 3, A: 12 }
const RANK: Record<Freq, number> = { M: 0, Q: 1, A: 2 }

function monthIndex(iso: string): number {
  return Number(iso.slice(0, 4)) * 12 + Number(iso.slice(5, 7)) - 1
}
function tsOfIndex(idx: number): number {
  return Date.UTC(Math.floor(idx / 12), idx % 12, 1)
}

/** Every period between the first and last point, so a missing month shows as a gap. */
function buildRows(series: PriceSeries[], unit: MassUnit): { rows: Row[]; gridFreq: Freq } {
  const pts = series.flatMap((s) => s.points)
  if (!pts.length) return { rows: [], gridFreq: 'M' }
  const gridFreq = series.reduce<Freq>((f, s) => (RANK[s.freq] < RANK[f] ? s.freq : f), 'A')
  const idxs = pts.map((p) => monthIndex(p.period_start))
  const lo = Math.min(...idxs)
  const hi = Math.max(...idxs)
  const byIdx = new Map<number, Row>()
  for (let i = lo; i <= hi; i += STEP[gridFreq]) byIdx.set(i, { x: tsOfIndex(i), label: '' })
  for (const s of series) {
    for (const p of s.points) {
      const i = monthIndex(p.period_start)
      let r = byIdx.get(i)
      if (!r) { r = { x: tsOfIndex(i), label: '' }; byIdx.set(i, r) }
      r.label = p.period_label
      r[s.id] = toUnit(p.value, unit)
      if (p.low !== null && p.high !== null && p.value !== null) r[`${s.id}__r`] = [toUnit(p.low, unit), toUnit(p.high, unit)]
      r[`${s.id}__p`] = p
    }
  }
  return { rows: [...byIdx.values()].sort((a, b) => a.x - b.x), gridFreq }
}

type TickMode = 'year' | 'quarter' | 'month'

function makeTicks(rows: Row[], gridFreq: Freq): { ticks: number[]; mode: TickMode } {
  if (rows.length < 2) return { ticks: rows.map((r) => r.x), mode: gridFreq === 'A' ? 'year' : gridFreq === 'Q' ? 'quarter' : 'month' }
  const first = new Date(rows[0].x)
  const last = new Date(rows[rows.length - 1].x)
  const span = (last.getUTCFullYear() - first.getUTCFullYear()) * 12 + last.getUTCMonth() - first.getUTCMonth()
  let step: number
  let mode: TickMode
  if (gridFreq === 'A' || span > 36) { step = 12; mode = 'year' }
  else if (gridFreq === 'Q') { step = span > 18 ? 6 : 3; mode = 'quarter' }
  else { step = span > 12 ? 3 : span > 6 ? 2 : 1; mode = 'month' }
  const ticks: number[] = []
  const startIdx = first.getUTCFullYear() * 12 + first.getUTCMonth()
  for (let i = Math.ceil(startIdx / step) * step; i <= startIdx + span; i += step) ticks.push(tsOfIndex(i))
  return { ticks, mode }
}

function tickLabel(ts: number, mode: TickMode, lang: Lang): string {
  const d = new Date(ts)
  const y = d.getUTCFullYear()
  if (mode === 'year') return String(y)
  if (mode === 'quarter') return `${lang === 'it' ? 'T' : 'Q'}${Math.floor(d.getUTCMonth() / 3) + 1} ${String(y).slice(2)}`
  return new Intl.DateTimeFormat(lang === 'it' ? 'it-IT' : 'en-GB', { month: 'short', year: '2-digit', timeZone: 'UTC' }).format(d)
}

/** Round axis bounds and evenly spaced ticks (1, 2, 2.5 or 5 × 10^n steps). */
function niceScale(vals: number[]): { domain: [number, number]; yTicks: number[] } {
  if (!vals.length) return { domain: [0, 1], yTicks: [0, 0.5, 1] }
  let lo = Math.min(...vals)
  let hi = Math.max(...vals)
  if (hi === lo) { lo -= Math.abs(lo) * 0.1 || 0.5; hi += Math.abs(hi) * 0.1 || 0.5 }
  const raw = (hi - lo) / 5
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag
  const start = Math.max(0, Math.floor(lo / step) * step)
  const end = Math.ceil(hi / step) * step
  const ticks: number[] = []
  for (let v = start; v <= end + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6)
  return { domain: [start, end], yTicks: ticks }
}

function lastValue(s: PriceSeries): PricePoint | null {
  for (let i = s.points.length - 1; i >= 0; i--) if (s.points[i].value !== null) return s.points[i]
  return null
}

interface Props {
  data: SeriesResponse
  labels: Record<string, string>
  colorOf: (id: string) => string | undefined
  toggle: (id: string) => void
  hideAll: () => void
  restore: () => void
  visibleCount: number
  limitHit: boolean
  unit: MassUnit
  typeLabel: string
}

export function PriceChart({ data, labels, colorOf, toggle, hideAll, restore, visibleCount, limitHit, unit, typeLabel }: Props) {
  const { t, lang } = useI18n()
  const series = data.series
  const visible = series.filter((s) => colorOf(s.id))
  const anyRange = series.some((s) => s.has_range)
  const [rangeOn, setRangeOn] = useState<boolean | null>(null)
  const showRange = anyRange && (rangeOn ?? visible.length <= 3)
  const uLabel = unitLabel(data.currency, unit)

  const { rows, gridFreq } = useMemo(() => buildRows(series, unit), [series, unit])
  const { ticks, mode: tickMode } = useMemo(() => makeTicks(rows, gridFreq), [rows, gridFreq])
  const lastIdx = useMemo(() => {
    const m: Record<string, number> = {}
    rows.forEach((r, i) => series.forEach((s) => { if (r[s.id] !== null && r[s.id] !== undefined) m[s.id] = i }))
    return m
  }, [rows, series])

  const { domain, yTicks } = useMemo(() => {
    const vals: number[] = []
    for (const r of rows) for (const s of visible) {
      const v = r[s.id] as number | null | undefined
      if (v !== null && v !== undefined) vals.push(v)
      const rg = r[`${s.id}__r`] as [number, number] | undefined
      if (showRange && rg) vals.push(rg[0], rg[1])
    }
    return niceScale(vals)
  }, [rows, visible, showRange])

  const dotFor = (id: string, color: string) => (props: { cx?: number; cy?: number; index?: number; key?: string }) => {
    const { cx, cy, index = 0, key } = props
    const has = (i: number) => rows[i] && rows[i][id] !== null && rows[i][id] !== undefined
    if (cx === undefined || cy === undefined || !has(index)) return <g key={key} />
    const p = rows[index][`${id}__p`] as PricePoint | undefined
    // an average built from only some of the months is drawn hollow
    if (p && p.expected_points && p.n_points < p.expected_points) {
      return <circle key={key} cx={cx} cy={cy} r={3.5} fill="#fff" stroke={color} strokeWidth={1.75} />
    }
    if (index === lastIdx[id]) return <circle key={key} cx={cx} cy={cy} r={4} fill={color} stroke="#fff" strokeWidth={2} />
    if (!has(index - 1) && !has(index + 1)) return <circle key={key} cx={cx} cy={cy} r={3} fill={color} stroke="#fff" strokeWidth={1.5} />
    return <g key={key} />
  }

  // the latest period most series share; a legend value from an older period is flagged
  const commonLast = useMemo(() => {
    const counts = new Map<string, number>()
    series.forEach((s) => { const p = lastValue(s)?.period_label; if (p) counts.set(p, (counts.get(p) ?? 0) + 1) })
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? 1 : -1))[0]?.[0] ?? null
  }, [series])

  const aggregated = data.freq !== 'M' || series.some((s) => s.freq !== 'M')
  const anyPartial = visible.some((s) => s.points.some((p) => p.expected_points !== null && p.n_points < p.expected_points))
  const fxMissing = series.reduce((n, s) => n + s.fx_missing_points, 0)
  const anyDemo = series.some((s) => s.is_demo)

  return (
    <Panel
      className="mb-5"
      eyebrow={`${typeLabel} · ${t('prices.chart.unitLine', { unit: uLabel, freq: t(`prices.freqAdj.${gridFreq}`) })}`}
      title={t('prices.chart.title')}
      actions={
        <>
          {anyDemo && <DemoBadge />}
          {anyRange && (
            <label className="flex items-center gap-2 text-sm text-charcoal-soft cursor-pointer select-none whitespace-nowrap">
              <input type="checkbox" className="accent-forest-700 h-4 w-4" checked={showRange} onChange={(e) => setRangeOn(e.target.checked)} />
              {t('prices.chart.range')}
            </label>
          )}
        </>
      }
      footer={
        <div className="flex flex-col gap-1.5">
          {data.sources.map((s) => (
            <div key={s.key} className="flex flex-wrap items-center gap-2">
              <SourceLine p={{ source: s, published_at: s.published_at, collected_at: s.collected_at, source_url: s.source_url, is_demo: s.is_demo }} />
              {s.freshness && <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />}
            </div>
          ))}
          <div className="text-[0.8rem] text-muted">
            {aggregated ? t('prices.chart.aggNote') : t('prices.chart.monthNote')}
            {anyPartial && <> <span className="inline-block h-2.5 w-2.5 rounded-full border-[1.5px] border-charcoal-soft align-[-1px] mx-0.5" /> {t('prices.chart.partialDot')}</>}
            {' '}{t('prices.chart.table')}
          </div>
        </div>
      }
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0">
          {fxMissing > 0 && <div className="mb-3"><Note tone="warn">{t('prices.f.fxMissing', { ccy: data.currency })}</Note></div>}
          {visible.length === 0 ? (
            <div className="h-[440px] flex items-center justify-center text-muted border border-dashed border-line rounded-sm">{t('prices.chart.noVisible')}</div>
          ) : (
            <div className="h-[440px]" role="img" aria-label={`${t('prices.chart.title')} — ${typeLabel}`}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#ECE6D6" strokeDasharray="0" vertical={false} />
                  <XAxis
                    dataKey="x" type="number" scale="time" domain={['dataMin', 'dataMax']} ticks={ticks}
                    tickFormatter={(v: number) => tickLabel(v, tickMode, lang)}
                    tick={{ fontSize: 13, fill: '#6B6A62' }} tickLine={false} axisLine={{ stroke: '#DDD6C4' }} minTickGap={12}
                  />
                  <YAxis
                    domain={domain} ticks={yTicks} width={56} allowDecimals interval={0}
                    tickFormatter={(v: number) => fmtNumber(v, lang, 2)}
                    tick={{ fontSize: 13, fill: '#6B6A62', fontFamily: '"IBM Plex Mono", monospace' }} tickLine={false} axisLine={false}
                  />
                  <Tooltip
                    cursor={{ stroke: '#A8873A', strokeWidth: 1, strokeDasharray: '3 3' }}
                    content={(p) => <ChartTooltip active={p.active} x={p.label as number} rows={rows} visible={visible} labels={labels} colorOf={colorOf} uLabel={uLabel} unit={unit} />}
                    wrapperStyle={{ outline: 'none', zIndex: 20 }}
                    isAnimationActive={false}
                  />
                  {showRange && visible.filter((s) => s.has_range).map((s) => (
                    <Area key={`${s.id}-r`} type="linear" dataKey={`${s.id}__r`} stroke="none" fill={colorOf(s.id)} fillOpacity={0.1}
                      isAnimationActive={false} activeDot={false} connectNulls={false} />
                  ))}
                  {visible.map((s) => (
                    <Line key={s.id} type="linear" dataKey={s.id} stroke={colorOf(s.id)} strokeWidth={2} connectNulls={false}
                      dot={dotFor(s.id, colorOf(s.id)!)} activeDot={{ r: 4, stroke: '#fff', strokeWidth: 2 }} isAnimationActive={false} />
                  ))}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <aside className="min-w-0 xl:border-l xl:border-line-soft xl:pl-5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="eyebrow">{t('prices.chart.legend')}</span>
            <span className="text-[0.78rem] text-charcoal-soft whitespace-nowrap">{t('prices.chart.visibleOf', { v: visible.length, n: series.length })}</span>
          </div>
          <p className="text-[0.8rem] text-muted mt-0.5 mb-2">{t('prices.chart.legendHint')}</p>
          {limitHit && <p className="text-[0.8rem] text-warn mb-2">{t('prices.chart.maxVisible', { n: MAX_VISIBLE })}</p>}
          <ul className="grid grid-cols-2 xl:grid-cols-1 gap-x-5 max-h-[300px] xl:max-h-[392px] overflow-y-auto -mx-1 pr-1">
            {series.map((s) => {
              const c = colorOf(s.id)
              const lp = lastValue(s)
              const stalePeriod = lp && commonLast && lp.period_label !== commonLast
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => toggle(s.id)}
                    aria-pressed={Boolean(c)}
                    title={`${labels[s.id]} — ${t('prices.chart.latest')}: ${fmtPrice(toUnit(lp?.value, unit), lang)} ${uLabel} (${fmtPeriodLabel(lp?.period_label, lang)})`}
                    className={clsx('w-full flex items-center gap-2 px-1 py-[2px] rounded-sm text-left hover:bg-ivory/70', !c && 'text-muted')}
                  >
                    <Swatch color={c} on={Boolean(c)} />
                    <span className="flex-1 min-w-0 truncate text-[0.88rem]">{labels[s.id]}</span>
                    {stalePeriod && <span className="text-[0.7rem] text-warn num shrink-0">{fmtPeriodLabel(lp.period_label, lang)}</span>}
                    <span className={clsx('num text-[0.88rem] shrink-0', c ? 'text-charcoal' : 'text-muted')}>{fmtPrice(toUnit(lp?.value, unit), lang)}</span>
                  </button>
                </li>
              )
            })}
          </ul>
          <div className="flex gap-3 mt-2 pt-2 border-t border-line-soft text-[0.85rem]">
            <button type="button" className="link" onClick={restore}>{t('prices.chart.restore')}</button>
            {visibleCount > 0 && <button type="button" className="link" onClick={hideAll}>{t('prices.chart.hideAll')}</button>}
          </div>
        </aside>
      </div>
    </Panel>
  )
}

function ChartTooltip({ active, x, rows, visible, labels, colorOf, uLabel, unit }: {
  active?: boolean; x: number; rows: Row[]; visible: PriceSeries[]; labels: Record<string, string>
  colorOf: (id: string) => string | undefined; uLabel: string; unit: MassUnit
}) {
  const { t, lang } = useI18n()
  if (!active) return null
  const row = rows.find((r) => r.x === x)
  if (!row) return null
  const items = visible
    .map((s) => ({ s, p: row[`${s.id}__p`] as PricePoint | undefined }))
    .filter((i): i is { s: PriceSeries; p: PricePoint } => Boolean(i.p))
    .sort((a, b) => (b.p.value ?? -1) - (a.p.value ?? -1))
  if (!items.length) return null
  return (
    <div className="bg-white border border-line shadow-[0_4px_16px_rgba(31,33,32,0.10)] rounded-sm px-3 py-2.5 min-w-[300px] max-w-[400px]">
      <div className="flex items-center justify-between gap-3 mb-1.5">
        <span className="font-serif font-semibold text-charcoal">{fmtPeriodLabel(row.label, lang)}</span>
        {items.some((i) => i.p.is_demo) && <DemoBadge />}
      </div>
      <ul className="flex flex-col gap-1.5">
        {items.map(({ s, p }) => (
          <li key={s.id} className="text-[0.82rem] leading-snug">
            <div className="flex items-baseline gap-2">
              <span className="self-center"><Swatch color={colorOf(s.id)} on size={9} /></span>
              <span className="flex-1 text-charcoal-soft truncate">{labels[s.id]}</span>
              <span className="num text-charcoal text-[0.92rem]">
                {p.value === null ? t('prices.chart.noFx') : `${fmtPrice(toUnit(p.value, unit), lang)}`}
              </span>
            </div>
            <div className="pl-[17px] text-muted text-[0.75rem]">
              {p.low !== null && p.high !== null && <span className="num">{fmtPrice(toUnit(p.low, unit), lang)}–{fmtPrice(toUnit(p.high, unit), lang)} · </span>}
              {p.period_label !== row.label && <span>{fmtPeriodLabel(p.period_label, lang)} · </span>}
              {p.expected_points && p.n_points < p.expected_points && <span>{t(p.n_points === 1 ? 'prices.chart.partialOne' : 'prices.chart.partial', { n: p.n_points, m: p.expected_points })} · </span>}
              <span>{s.source?.publisher || s.source?.name}</span>
              {p.published_at && <span> · {t('prov.published')} {fmtDate(p.published_at, lang)}</span>}
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-1.5 pt-1.5 border-t border-line-soft text-[0.72rem] text-muted">{uLabel}</div>
    </div>
  )
}
