// /prezzi, simple view: first a short table per price type (one series per main origin: latest price,
// a month before, a year before, the trend, each row with its source chip), then a chart of those
// origins; every filter and long table stays under "Mostra dettagli" (the full page).
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DemoBadge, ErrorBlock, Loading, Segmented } from '@/components/ui'
import type { Ccy, FacetsResponse, LatestResponse, LatestRow, SeriesResponse } from '@/components/prices/types'
import { colorLabel, PRICE_TYPE_ORDER, rangeFrom, SERIES_COLORS } from '@/components/prices/utils'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtNumber, fmtPeriod } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { perKg, PLAIN_PRICE_TYPE_HINT, PLAIN_PRICE_TYPE_TITLE, plainVariety, plainWhere } from '@/lib/plain'
import { Trend, useGapNote } from './bits'
import { MAIN_ORIGINS, pickPriceRows } from './pickPrices'
import { SourceChip } from './SourceChip'

/** Currency of the simple tables: euro unless the address says dollars (?valuta=USD). The choice is
 * written in the address, so the full page under "Mostra dettagli" (and the full view) use it too. */
export function useSimpleCcy(): [Ccy, (c: Ccy) => void] {
  const [sp, setSp] = useSearchParams()
  const ccy: Ccy = sp.get('valuta') === 'USD' ? 'USD' : 'EUR'
  const set = useCallback((c: Ccy) => setSp((prev) => { const n = new URLSearchParams(prev); n.set('valuta', c); return n }, { replace: true }), [setSp])
  const missing = !sp.get('valuta')
  useEffect(() => { if (missing) set('EUR') }, [missing, set])
  return [ccy, set]
}

function latestParams(type: string, ccy: Ccy) {
  return { price_type: type, origin: MAIN_ORIGINS, currency: ccy }
}

function useSimpleLatest(type: string, ccy: Ccy) {
  return useQuery({
    queryKey: ['prices', 'simple-latest', type, ccy],
    queryFn: () => api.get<LatestResponse>('/prices/latest', latestParams(type, ccy)),
  })
}

function Money({ v, ccy, big = false }: { v: number | null | undefined; ccy: string; big?: boolean }) {
  const { lang } = useI18n()
  if (v === null || v === undefined) return <span className="text-muted">—</span>
  return (
    <span className={clsx('tabular-nums whitespace-nowrap', big ? 'text-[1.45rem] font-semibold leading-none text-charcoal' : 'text-[1.02rem] text-charcoal-soft')}>
      {fmtNumber(v, lang, 2)} <span className={big ? 'text-[0.85rem]' : 'text-[0.8rem]'}>{perKg(ccy)}</span>
    </span>
  )
}

/** A table cell; on a phone (no column headers) it names itself, unless `hideLabel` (then only for screen readers). */
function Cell({ label, children, className, hideLabel = false }: { label: string; children: ReactNode; className?: string; hideLabel?: boolean }) {
  return (
    <div className={clsx('min-w-0', className)}>
      <span className={clsx('text-[0.85rem] text-muted', hideLabel ? 'sr-only' : 'sm:hidden')}>{label}: </span>
      {children}
    </div>
  )
}

function PriceRowView({ r, ccy }: { r: LatestRow; ccy: Ccy }) {
  const { t, lang } = useI18n()
  const { country, variety, priceType } = useLabels()
  const v = plainVariety(r.variety, lang, variety)
  const color = r.color_grade ? colorLabel(r.color_grade, t) : null
  const what = [v, color].filter(Boolean).map((x) => (lang === 'it' ? (x as string).toLowerCase() : x)).join(', ')
  const monthly = r.freq === 'M'
  const prev = monthly ? r.previous : null
  const gapNote = useGapNote()
  // The exact month before is missing: the newest earlier figure of the SAME series, with its own
  // date (never called "a month before"), unless it is the year-before figure shown next to it.
  const earlier = monthly && !prev && r.earlier && r.earlier.value != null && r.earlier.period_label !== r.year_ago?.period_label ? r.earlier : null
  const prevNote = monthly && !prev ? gapNote(r.missing?.previous) : null
  const yearNote = !r.year_ago ? gapNote(r.missing?.year_ago) : null
  const o = r.latest.original
  const technical = [priceType(r.price_type), variety(r.variety), color, r.terms,
    o ? `${fmtNumber(o.value, lang, 2)} ${o.currency}/${o.unit}` : null].filter(Boolean).join(' · ')
  return (
    <li className="grid grid-cols-2 gap-x-4 gap-y-1.5 border-b border-line-soft py-3.5 last:border-0 sm:grid-cols-[minmax(0,1.9fr)_minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)] sm:items-baseline"
      data-simple-price={r.origin_iso3 ?? ''}>
      <div className="col-span-2 min-w-0 sm:order-1 sm:col-span-1">
        <div className="text-[1.12rem] font-semibold leading-snug text-charcoal">{r.origin_iso3 ? country(r.origin_iso3) : r.origin_label}</div>
        <div className="text-[0.95rem] leading-snug text-charcoal-soft">{[plainWhere(r, lang, country), what].filter(Boolean).join(' · ')}</div>
      </div>
      <Cell label={t('simple.pt.latest')} className="sm:order-2" hideLabel>
        <Money v={r.latest.value} ccy={ccy} big />
        <div className="tabular-nums text-[0.88rem] text-muted">{fmtPeriod(r.period_label, lang)}</div>
      </Cell>
      <div className="text-right sm:order-5 sm:text-left">
        <Trend month={monthly ? r.change_prev_pct : null} year={r.change_yoy_pct}
          earlier={r.earlier && r.change_earlier_pct != null ? { pct: r.change_earlier_pct, period_label: r.earlier.period_label } : null}
          className="text-[0.95rem]" />
      </div>
      <Cell label={t('simple.pt.monthAgo')} className="sm:order-3">
        {earlier ? (
          <>
            <Money v={earlier.value} ccy={ccy} />
            <div className="text-[0.85rem] text-warn" data-earlier>{t('simple.pt.earlier', { p: fmtPeriod(earlier.period_label, lang) })}</div>
          </>
        ) : <Money v={prev?.value} ccy={ccy} />}
        {prev && <div className="tabular-nums text-[0.85rem] text-muted">{fmtPeriod(prev.period_label, lang)}</div>}
        {prevNote && <div className="text-[0.82rem] leading-snug text-muted" data-gap>{prevNote}</div>}
      </Cell>
      <Cell label={t('simple.pt.yearAgo')} className="sm:order-4">
        <Money v={r.year_ago?.value} ccy={ccy} />
        {r.year_ago && <div className="tabular-nums text-[0.85rem] text-muted">{fmtPeriod(r.year_ago.period_label, lang)}</div>}
        {yearNote && <div className="text-[0.82rem] leading-snug text-muted" data-gap>{yearNote}</div>}
      </Cell>
      <SourceChip className="col-span-2 sm:order-6 sm:col-span-5" p={{
        source: r.source, period_label: r.period_label, published_at: r.published_at, collected_at: r.collected_at,
        source_url: r.source_url, data_status: r.data_status, is_demo: r.is_demo, technical,
        note: [r.latest.value === null ? t('simple.pt.noFx') : null, monthly ? null : t('simple.pt.annual'),
          r.latest.row_id ? null : t('simple.pt.average')].filter(Boolean).join(' ') || null,
        correction: r.latest.correction ?? null,
      }} figure={r.latest.row_id && o ? {
        table: 'price_observations', row_id: r.latest.row_id, value: o.value, unit: o.unit, currency: o.currency,
        label: `${r.origin_iso3 ? country(r.origin_iso3) : r.origin_label} · ${[plainWhere(r, lang, country), what].filter(Boolean).join(' · ')} · ${fmtPeriod(r.period_label, lang)}`,
        country_iso3: r.origin_iso3, period_label: r.period_label,
      } : null} />
    </li>
  )
}

function TypeTable({ type, ccy }: { type: string; ccy: Ccy }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const q = useSimpleLatest(type, ccy)
  const picked = useMemo(() => (q.data ? pickPriceRows(q.data.rows, q.data.today) : null), [q.data])
  const title = PLAIN_PRICE_TYPE_TITLE[type]?.[lang] ?? type
  return (
    <section className="panel" data-simple-type={type}>
      <div className="px-4 pb-1 pt-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-serif text-[1.35rem] font-semibold leading-tight text-forest-900">{title}</h2>
          {picked?.rows.some((r) => r.is_demo) && <DemoBadge />}
        </div>
        <p className="mt-0.5 text-[0.95rem] text-muted">{PLAIN_PRICE_TYPE_HINT[type]?.[lang]}</p>
      </div>
      <div className="px-4 pb-3 sm:px-6">
        {q.isLoading ? <Loading /> : q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} /> : picked && (
          picked.rows.length === 0 ? (
            <p className="py-3 text-[1rem] text-muted">{t('simple.pt.noneCurrent')}</p>
          ) : (
            <>
              <div className="mt-2 hidden grid-cols-[minmax(0,1.9fr)_minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)] gap-x-4 border-b border-line pb-1.5 text-[0.78rem] uppercase tracking-wider text-muted sm:grid">
                <span>{t('simple.pt.origin')}</span><span>{t('simple.pt.latest')}</span><span>{t('simple.pt.monthAgo')}</span>
                <span>{t('simple.pt.yearAgo')}</span><span>{t('simple.pt.trend')}</span>
              </div>
              <ul>{picked.rows.map((r) => <PriceRowView key={r.series_id} r={r} ccy={ccy} />)}</ul>
            </>
          )
        )}
        {picked && picked.old.length > 0 && (
          <p className="mt-2 text-[0.92rem] text-muted" data-simple-old>
            {t('simple.pt.old', { list: picked.old.map((r) => `${r.origin_iso3 ? country(r.origin_iso3) : r.origin_label} (${fmtPeriod(r.period_label, lang)})`).join(', ') })}
          </p>
        )}
      </div>
    </section>
  )
}

/** One line per origin of that type's table (the same rows), monthly, over the last three years. */
function SimpleChart({ type, ccy }: { type: string; ccy: Ccy }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const latest = useSimpleLatest(type, ccy)
  const shown = useMemo(() => (latest.data ? pickPriceRows(latest.data.rows, latest.data.today).rows : [])
    .filter((r) => r.freq === 'M').slice(0, SERIES_COLORS.length), [latest.data])
  const ids = useMemo(() => shown.map((r) => r.series_id).sort(), [shown])
  const q = useQuery({
    queryKey: ['prices', 'simple-series', type, ccy, ids],
    queryFn: () => api.get<SeriesResponse>('/prices/series', {
      price_type: type, origin: MAIN_ORIGINS, from: rangeFrom('3y') ?? undefined, freq: 'M', currency: ccy, ids: ids.join(','),
    }),
    enabled: ids.length > 0,
  })
  const data = useMemo(() => {
    const series = (q.data?.series ?? []).filter((s) => ids.includes(s.id) && !s.points_omitted)
    const labels = new Set<string>()
    for (const s of series) for (const p of s.points) if (p.value !== null) labels.add(p.period_label)
    const sorted = [...labels].sort()
    if (!sorted.length) return []
    // every month between the first and last, so a missing month is a gap, not a straight line
    const [y0, m0] = sorted[0].split('-').map(Number)
    const [y1, m1] = sorted[sorted.length - 1].split('-').map(Number)
    const out: Record<string, number | string | null>[] = []
    for (let i = y0 * 12 + m0 - 1; i <= y1 * 12 + m1 - 1; i++) {
      const label = `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}`
      const row: Record<string, number | string | null> = { label }
      for (const s of series) row[s.id] = s.points.find((p) => p.period_label === label)?.value ?? null
      out.push(row)
    }
    return out
  }, [q.data, ids])
  if (!ids.length) return null
  const name = (r: LatestRow) => (r.origin_iso3 ? country(r.origin_iso3) : r.origin_label ?? '')
  return (
    <div data-simple-chart>
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1.5 text-[0.95rem]">
        {shown.map((r, i) => (
          <li key={r.series_id} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-[3px] w-5 rounded-full" style={{ background: SERIES_COLORS[i] }} aria-hidden />
            {name(r)}
          </li>
        ))}
      </ul>
      {q.isLoading ? <Loading /> : q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} /> : (
        <div className="h-[280px] w-full sm:h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <CartesianGrid stroke="#E9E3D3" vertical={false} />
              <XAxis dataKey="label" tickFormatter={(l: string) => fmtPeriod(l, lang)} tick={{ fontSize: 13, fill: '#6B6A62' }} minTickGap={24} />
              <YAxis width={48} tick={{ fontSize: 13, fill: '#6B6A62' }} tickFormatter={(v: number) => fmtNumber(v, lang, 1)} domain={['auto', 'auto']} />
              <Tooltip
                formatter={(v: number, id: string) => {
                  const r = shown.find((x) => x.series_id === id)
                  return [`${fmtNumber(v, lang, 2)} ${perKg(ccy)}`, r ? name(r) : id]
                }}
                labelFormatter={(l: string) => fmtPeriod(l, lang)}
              />
              {shown.map((r, i) => (
                <Line key={r.series_id} dataKey={r.series_id} stroke={SERIES_COLORS[i]} strokeWidth={2.2} dot={false} connectNulls={false} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-1 text-[0.88rem] text-muted">{t('simple.chart.note', { unit: perKg(ccy) })}</p>
    </div>
  )
}

export function SimplePrices({ details }: { details: ReactNode }) {
  const { t, lang } = useI18n()
  const [ccy, setCcy] = useSimpleCcy()
  const all = useQuery({ queryKey: ['prices', 'facets', 'all'], queryFn: () => api.get<FacetsResponse>('/prices/facets') })
  const types = useMemo(() => {
    const n = Object.fromEntries((all.data?.price_types ?? []).map((p) => [p.key, p.count])) as Record<string, number>
    return PRICE_TYPE_ORDER.filter((k) => (n[k] ?? 0) > 0)
  }, [all.data])
  const [chartType, setChartType] = useState<string | null>(null)
  const ct = chartType ?? types[0] ?? null
  return (
    <div data-view="simple">
      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-[1rem] text-charcoal-soft">{t('simple.pt.currency')}</span>
        <Segmented value={ccy} onChange={setCcy} options={[{ value: 'EUR', label: '€/kg' }, { value: 'USD', label: '$/kg' }]} />
        <span className="text-[0.9rem] text-muted">{t('simple.pt.fx')}</span>
      </div>
      {all.isLoading ? <Loading /> : all.error ? <ErrorBlock error={all.error} onRetry={() => all.refetch()} /> : types.length === 0 ? (
        <p className="panel px-5 py-4 text-[1rem] text-muted">{t('simple.prices.none')}</p>
      ) : (
        <div className="space-y-5">
          {types.map((ty) => <TypeTable key={ty} type={ty} ccy={ccy} />)}
          {ct && (
            <section className="panel px-4 py-4 sm:px-6">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <h2 className="font-serif text-[1.35rem] font-semibold text-forest-900">{t('simple.chart.title')}</h2>
                {types.length > 1 && (
                  <Segmented size="sm" value={ct} onChange={setChartType}
                    options={types.map((ty) => ({ value: ty, label: PLAIN_PRICE_TYPE_TITLE[ty]?.[lang] ?? ty }))} />
                )}
              </div>
              <SimpleChart type={ct} ccy={ccy} />
            </section>
          )}
        </div>
      )}
      {details}
    </div>
  )
}
