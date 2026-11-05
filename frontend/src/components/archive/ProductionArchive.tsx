// Archivio · Produzione: honey production (or colonies) of a country per year, per source, with the
// publisher's own flag (official figure, estimate, imputed value ...).
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DemoBadge, EmptyState, ErrorBlock, Loading, Panel, Segmented, SourceLine } from '@/components/ui'
import { DocLink } from '@/components/prices/bits'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate, fmtNumber } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import type { Lang } from '@/lib/types'
import { ChangeCell } from './PriceArchive'
import { readProduction, useArchiveParams } from './state'
import type { ProductionPoint, ProductionResponse } from './types'

export function fmtProduction(v: number | null, unit: string, lang: Lang): string {
  if (v === null) return '—'
  if (unit === 't') return `${fmtNumber(v, lang, 0)} t`
  if (unit === 'number') return fmtNumber(v, lang, 0)
  return `${fmtNumber(v, lang, 1)} ${unit}`
}

export function ProductionTable({ points, unit }: { points: ProductionPoint[]; unit: string }) {
  const { t, lang } = useI18n()
  const flag = (f: string | null) => {
    if (!f) return '—'
    const k = `archive.pr.flag.${f}`
    const s = t(k)
    return s === k ? f : `${s} (${f})`
  }
  return (
    <div className="overflow-x-auto -mx-5 px-5">
      <table className="table-clean min-w-[600px]">
        <thead>
          <tr>
            <th>{t('archive.pr.col.year')}</th>
            <th className="!text-right">{t('archive.pr.col.value')}</th>
            <th>{t('archive.pr.col.change')}</th>
            <th>{t('archive.pr.col.flag')}</th>
            <th>{t('archive.pr.col.published')}</th>
          </tr>
        </thead>
        <tbody>
          {[...points].reverse().map((p) => (
            <tr key={p.period_label}>
              <td className="num font-medium">{p.period_label}{p.is_demo && <span className="ml-1"><DemoBadge /></span>}</td>
              <td className="num text-right font-medium whitespace-nowrap">{fmtProduction(p.value, unit, lang)}</td>
              <td><ChangeCell pct={p.change_pct} /></td>
              <td className="text-sm">{flag(p.flag)}</td>
              <td className="whitespace-nowrap"><span className="mr-1.5">{fmtDate(p.published_at, lang)}</span><DocLink url={p.source_url} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ProductionArchive() {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const { sp, set } = useArchiveParams()
  const sel = readProduction(sp)
  const q = useQuery({
    queryKey: ['archive', 'production', sel.country, sel.metric],
    queryFn: () => api.get<ProductionResponse>('/archive/production', sel),
    placeholderData: keepPreviousData,
  })
  const d = q.data
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
  if (!d) return null
  if (!d.countries.length && !d.available) return <Panel><EmptyState hint={t('archive.pr.noCountries')} /></Panel>
  const metricLabel = (k: string) => {
    const s = t(`archive.pr.metric.${k}`)
    return s === `archive.pr.metric.${k}` ? k : s
  }
  const metrics = (d.metrics.length ? [...d.metrics] : [{ key: sel.metric, rows: 0 }])
    .sort((a, b) => Number(b.key === 'production') - Number(a.key === 'production'))
  return (
    <div className="flex flex-col gap-5">
      <Panel bodyClassName="p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block min-w-[14rem] flex-1 sm:flex-none">
            <span className="label">{t('archive.pr.country')}</span>
            <select className="field" value={sel.country} onChange={(e) => set({ paese: e.target.value })}>
              {!d.countries.some((c) => c.iso3 === sel.country) && <option value={sel.country}>{country(sel.country)}</option>}
              {d.countries.map((c) => <option key={c.iso3} value={c.iso3}>{country(c.iso3)}</option>)}
            </select>
          </label>
          <div>
            <span className="label">{t('archive.pr.metric')}</span>
            <Segmented size="sm" value={sel.metric} onChange={(v) => set({ dato: v === 'production' ? null : v })}
              options={metrics.map((m) => ({ value: m.key, label: metricLabel(m.key) }))} />
          </div>
        </div>
      </Panel>
      {!d.available ? <Panel><EmptyState hint={t('archive.pr.noData')} /></Panel> : d.series.map((s) => {
        const last = s.points.at(-1)
        return (
          <Panel key={`${s.source?.key}-${s.unit}`} eyebrow={`${metricLabel(d.metric)} · ${country(d.country)}`} title={t('archive.pr.chartTitle')}
            footer={<SourceLine p={{ source: s.source, published_at: last?.published_at, collected_at: last?.collected_at, source_url: last?.source_url, is_demo: s.is_demo }} />}>
            {last && <p className="text-sm text-muted mb-3">{t('archive.pr.latest', { y: last.period_label })}</p>}
            <div className="h-[240px] -ml-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={s.points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#E9E3D3" vertical={false} />
                  <XAxis dataKey="period_label" tick={{ fontSize: 12, fill: '#6B6A62' }} tickLine={false} axisLine={{ stroke: '#DDD6C4' }} minTickGap={12} />
                  <YAxis tick={{ fontSize: 12, fill: '#6B6A62' }} tickLine={false} axisLine={false} width={70}
                    tickFormatter={(v: number) => fmtNumber(v, lang, 0)} />
                  <Tooltip formatter={(v: number) => [fmtProduction(v, s.unit, lang), metricLabel(d.metric)]} />
                  <Bar dataKey="value" fill="#A8873A" isAnimationActive={false} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-4"><ProductionTable points={s.points} unit={s.unit} /></div>
          </Panel>
        )
      })}
    </div>
  )
}
