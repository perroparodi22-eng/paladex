// Archivio · Prezzi: one price series (one price type, never mixed), the average of each year and
// the months of this year against the same months of the two years before.
import clsx from 'clsx'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useMemo } from 'react'
import { DemoBadge, EmptyState, ErrorBlock, FreshnessBadge, Loading, Note, Panel, Segmented, SourceLine, StatusBadge } from '@/components/ui'
import { DocLink } from '@/components/prices/bits'
import { colorLabel, fmtPeriodLabel } from '@/components/prices/utils'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtPct } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { priceChoices, usePriceArchive } from './state'
import type { Ccy, Overlay, OverlayPoint, YearRow } from './types'
import { monthNames, overlayRows, perUnit, seriesLabels, YEAR_COLORS } from './utils'

export function ChangeCell({ pct, note, tip }: { pct: number | null; note?: string; tip?: string }) {
  const { lang } = useI18n()
  if (pct === null) return <span className="text-muted" title={tip}>—</span>
  return (
    <span title={tip} className="whitespace-nowrap">
      <span className={clsx('num', pct > 0 ? 'text-up' : pct < 0 ? 'text-down' : 'text-muted')}>
        <span className="text-[0.7rem] mr-0.5 align-[1px]">{pct > 0 ? '▲' : pct < 0 ? '▼' : '■'}</span>{fmtPct(pct, lang, 1)}
      </span>
      {note && <span className="block text-[0.78rem] text-muted">{note}</span>}
    </span>
  )
}

export function YearsTable({ years, unitText, unit }: { years: YearRow[]; unitText: string; unit: 'kg' | 'lb' }) {
  const { t, lang } = useI18n()
  const v = (x: number | null | undefined) => fmtNumber(perUnit(x, unit), lang, 2)
  return (
    <div className="overflow-x-auto -mx-5 px-5">
      <table className="table-clean min-w-[760px]">
        <thead>
          <tr>
            <th>{t('archive.p.col.year')}</th>
            <th className="!text-right">{t('archive.p.col.average')} <span className="normal-case tracking-normal">({unitText})</span></th>
            <th>{t('archive.p.col.months')}</th>
            <th className="!text-right">{t('archive.p.col.min')}</th>
            <th className="!text-right">{t('archive.p.col.max')}</th>
            <th>{t('archive.p.col.change')}</th>
            <th>{t('archive.p.col.published')}</th>
            <th>{t('archive.p.col.status')}</th>
          </tr>
        </thead>
        <tbody>
          {[...years].reverse().map((y) => (
            <tr key={y.year}>
              <td className="num font-medium">{y.year}{y.is_demo && <span className="ml-1"><DemoBadge /></span>}</td>
              <td className="num text-right font-medium" title={y.weighting === 'volume' ? t('archive.p.weighted') : t('archive.p.simple')}>{v(y.average)}</td>
              <td className="whitespace-nowrap">
                <span className="num">{t('archive.p.monthsOf', { n: y.periods, m: y.expected_periods })}</span>
                {!y.complete && <span className="block text-[0.78rem] text-warn">{t('archive.p.partial')} · {fmtPeriodLabel(y.first_period, lang)}–{fmtPeriodLabel(y.last_period, lang)}</span>}
              </td>
              <td className="num text-right whitespace-nowrap">{v(y.min.value)}<span className="block text-[0.78rem] text-muted">{fmtPeriodLabel(y.min.period_label, lang)}</span></td>
              <td className="num text-right whitespace-nowrap">{v(y.max.value)}<span className="block text-[0.78rem] text-muted">{fmtPeriodLabel(y.max.period_label, lang)}</span></td>
              <td>
                <ChangeCell pct={y.change_pct} tip={y.change_pct === null ? t('archive.p.noChange') : t('archive.p.changeTip')}
                  note={y.change_pct !== null && y.change_same_periods_only
                    ? (y.change_periods === 1 ? t('archive.p.sameMonthsOne') : t('archive.p.sameMonths', { n: y.change_periods })) : undefined} />
              </td>
              <td className="whitespace-nowrap">
                <span className="mr-1.5">{fmtDate(y.published_at, lang)}</span>
                <DocLink url={y.source_url} />
              </td>
              <td>{y.data_status && <StatusBadge status={y.data_status} />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function OverlayTooltip({ active, payload, unitText, unit }: {
  active?: boolean; payload?: { dataKey: string; color: string; payload: Record<string, unknown> }[]; unitText: string; unit: 'kg' | 'lb'
}) {
  const { t, lang } = useI18n()
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  const month = monthNames(lang, 'long')[((row.month as number) ?? 1) - 1]
  return (
    <div className="bg-white border border-line rounded-sm shadow-sm px-3 py-2 text-sm max-w-[18rem]">
      <div className="font-medium mb-1 first-letter:uppercase">{month}</div>
      {payload.map((p) => {
        const year = p.dataKey.slice(1)
        const pt = row[`p${year}`] as OverlayPoint | undefined
        if (!pt) return null
        return (
          <div key={p.dataKey} className="flex flex-col py-0.5">
            <span className="flex items-center gap-2">
              <span className="inline-block h-2 w-3 rounded-[1px]" style={{ background: p.color }} />
              <span className="num font-medium">{year}: {fmtNumber(perUnit(pt.value, unit), lang, 2)} {unitText}</span>
            </span>
            <span className="text-[0.78rem] text-muted pl-5">
              {pt.n_points && pt.n_points > 1 ? `${t('archive.p.pointOf', { n: pt.n_points })} · ` : ''}
              {t('prov.published')} {fmtDate(pt.published_at, lang)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export function OverlayChart({ ov, unit, unitText }: { ov: Overlay; unit: 'kg' | 'lb'; unitText: string }) {
  const { t, lang } = useI18n()
  const rows = useMemo(() => overlayRows(ov, unit, lang), [ov, unit, lang])
  return (
    <div>
      <div className="h-[300px] sm:h-[340px] -ml-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#E9E3D3" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 12, fill: '#6B6A62' }} tickLine={false} axisLine={{ stroke: '#DDD6C4' }} interval={0} />
            <YAxis tick={{ fontSize: 12, fill: '#6B6A62' }} tickLine={false} axisLine={false} width={46} domain={['auto', 'auto']}
              tickFormatter={(v: number) => fmtNumber(v, lang, 2)} />
            <Tooltip content={<OverlayTooltip unitText={unitText} unit={unit} />} />
            {ov.years.map((y, i) => (
              <Line key={y.year} dataKey={`y${y.year}`} name={String(y.year)} stroke={YEAR_COLORS[i] ?? '#8A877C'}
                strokeWidth={i === 0 ? 2.6 : 1.8} strokeDasharray={i === 2 ? '5 4' : undefined} connectNulls={false}
                dot={{ r: i === 0 ? 3 : 2.5, strokeWidth: 0, fill: YEAR_COLORS[i] ?? '#8A877C' }} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
        {ov.years.map((y, i) => (
          <span key={y.year} className="inline-flex items-center gap-2">
            <svg width="22" height="8" aria-hidden><line x1="0" y1="4" x2="22" y2="4" stroke={YEAR_COLORS[i]} strokeWidth={i === 0 ? 3 : 2} strokeDasharray={i === 2 ? '5 4' : undefined} /></svg>
            <span className="num font-medium">{y.year}</span>
            <span className="text-muted">{y.months === 1 ? t('archive.p.monthsShownOne') : t('archive.p.monthsShown', { n: y.months })}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

export function PriceArchive() {
  const { t, lang } = useI18n()
  const { country, variety, priceType } = useLabels()
  const { set, options, sel, ccy, unit, history } = usePriceArchive()
  const o = options.data
  const choices = priceChoices(o?.combos ?? [], sel)
  const data = history.data
  const s = data?.selected ?? null
  const labels = useMemo(() => seriesLabels(data?.series ?? [], {
    country: (c) => country(c), color: (c) => colorLabel(c, t), t,
  }), [data, country, t])

  if (options.isLoading) return <Loading />
  if (options.error) return <ErrorBlock error={options.error} onRetry={() => options.refetch()} />
  if (!o || !o.price_types.length) return <Panel><EmptyState hint={t('archive.p.noTypes')} /></Panel>

  const unitText = `${s?.currency ?? (ccy === 'ORIGINAL' ? '' : ccy)}/${unit}`
  const field = 'block min-w-0'
  return (
    <div className="flex flex-col gap-5">
      <Panel bodyClassName="p-4">
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 items-end">
          <label className={field}>
            <span className="label">{t('archive.p.type')}</span>
            <select className="field" value={o.price_type ?? ''} onChange={(e) => set({ tipo: e.target.value, origine: null, varieta: null, mercato: null, colore: null, serie: null })}>
              {o.price_types.map((p) => <option key={p.key} value={p.key}>{priceType(p.key)}</option>)}
            </select>
          </label>
          <label className={field}>
            <span className="label">{t('archive.p.origin')}</span>
            <select className="field" value={sel?.origin ?? ''} onChange={(e) => set({ origine: e.target.value, varieta: null, mercato: null, colore: null, serie: null })}>
              {choices.origins.map((c) => <option key={c} value={c}>{country(c)}</option>)}
            </select>
          </label>
          <label className={field}>
            <span className="label">{t('archive.p.variety')}</span>
            <select className="field" value={sel?.variety ?? ''} onChange={(e) => set({ varieta: e.target.value, mercato: null, colore: null, serie: null })}>
              {choices.varieties.map((v) => <option key={v} value={v}>{variety(v)}</option>)}
            </select>
          </label>
          <label className={field}>
            <span className="label">{t('archive.p.market')}</span>
            <select className="field" value={sel?.market ?? 'tutti'} onChange={(e) => set({ mercato: e.target.value, colore: null, serie: null })}>
              <option value="tutti">{t('archive.p.anyMarket')}</option>
              {choices.markets.map((m) => <option key={m} value={m}>{country(m)}</option>)}
            </select>
          </label>
          {choices.colors.length > 0 && (
            <label className={field}>
              <span className="label">{t('archive.p.color')}</span>
              <select className="field" value={sel?.color_grade ?? ''} onChange={(e) => set({ colore: e.target.value || null, serie: null })}>
                <option value="">{t('archive.p.anyColor')}</option>
                {choices.colors.map((c) => <option key={c} value={c}>{colorLabel(c, t)}</option>)}
              </select>
            </label>
          )}
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-x-5 gap-y-3">
          {data && data.series.length > 1 && (
            <label className="block min-w-0 w-full lg:w-auto lg:flex-1 lg:max-w-3xl">
              <span className="label">{t('archive.p.series')}</span>
              <select className="field" value={s?.id ?? ''} onChange={(e) => set({ serie: e.target.value })}>
                {data.series.map((x) => <option key={x.id} value={x.id}>{labels[x.id]} ({x.first_period.slice(0, 4)}–{x.last_period.slice(0, 4)})</option>)}
              </select>
            </label>
          )}
          <div>
            <span className="label">{t('archive.p.currency')}</span>
            <Segmented<Ccy> size="sm" value={ccy} onChange={(v) => set({ valuta: v === 'ORIGINAL' ? null : v })}
              options={(['ORIGINAL', 'USD', 'EUR'] as Ccy[]).map((c) => ({ value: c, label: t(`archive.p.ccy.${c}`) }))} />
          </div>
          <div>
            <span className="label">{t('archive.p.unit')}</span>
            <Segmented<'kg' | 'lb'> size="sm" value={unit} onChange={(v) => set({ unita: v === 'kg' ? null : v })}
              options={[{ value: 'kg', label: 'kg' }, { value: 'lb', label: 'lb' }]} />
          </div>
        </div>
      </Panel>

      {history.error ? <ErrorBlock error={history.error} onRetry={() => history.refetch()} />
        : !data ? <Panel><Loading /></Panel>
        : !s ? <Panel><EmptyState hint={t('archive.p.noSeries')} /></Panel>
        : (
          <>
            <Panel
              eyebrow={`${priceType(s.price_type)} · ${country(s.origin_iso3)} · ${variety(s.variety)}`}
              title={s.overlay ? t('archive.p.chartTitle', { y: s.overlay.latest_year }) : t('archive.p.yearsTitle')}
              actions={<FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />}
              footer={<SourceLine p={{ source: s.source, published_at: s.published_at, collected_at: s.collected_at, source_url: s.source_url, is_demo: s.is_demo }} />}
            >
              <div className="text-sm text-muted mb-3">
                {labels[s.id]} · {t('archive.p.from', { a: fmtPeriodLabel(s.first_period, lang), b: fmtPeriodLabel(s.last_period, lang) })}
              </div>
              {s.overlay ? <OverlayChart ov={s.overlay} unit={unit} unitText={unitText} /> : <Note>{t('archive.p.annualOnly')}</Note>}
              {ccy !== 'ORIGINAL' && <p className="text-sm text-muted mt-3">{t('archive.p.fxNote')}</p>}
            </Panel>
            <Panel title={t('archive.p.yearsTitle')} footer={t('archive.p.howTo')}>
              <YearsTable years={s.years} unitText={unitText} unit={unit} />
            </Panel>
          </>
        )}
    </div>
  )
}
