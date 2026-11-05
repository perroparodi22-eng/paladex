// Archivio · Commercio: volumes per year for a declaring country and a partner, one source per
// figure (never added together), and the months of the latest year against the same months before.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useMemo } from 'react'
import { DemoBadge, EmptyState, ErrorBlock, FreshnessBadge, Loading, Note, Panel, Segmented, SourceLine, StatusBadge } from '@/components/ui'
import { DocLink } from '@/components/prices/bits'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtCompact, fmtDate, fmtNumber, fmtTonnes } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { ChangeCell } from './PriceArchive'
import { useTradeSelection } from './state'
import type { TradeHistoryResponse } from './types'
import { monthNames } from './utils'

const SOURCE_COLORS = ['#143A2B', '#A8873A', '#2f6fb5', '#8A877C']

export function TradeYearsTable({ d }: { d: TradeHistoryResponse }) {
  const { t, lang } = useI18n()
  const rows = d.annual.flatMap((s) => s.points.map((p) => ({ src: s.source, p })))
    .sort((a, b) => b.p.period_label.localeCompare(a.p.period_label) || (a.src?.key ?? '').localeCompare(b.src?.key ?? ''))
  return (
    <div className="overflow-x-auto -mx-5 px-5">
      <table className="table-clean min-w-[720px]">
        <thead>
          <tr>
            <th>{t('archive.t.col.year')}</th>
            <th>{t('prov.source')}</th>
            <th className="!text-right">{t('archive.t.col.volume')}</th>
            <th>{t('archive.t.col.change')}</th>
            <th className="!text-right">{t('archive.t.col.value')}</th>
            <th>{t('archive.t.col.basis')}</th>
            <th>{t('archive.t.col.published')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ src, p }) => (
            <tr key={`${src?.key}-${p.period_label}`}>
              <td className="num font-medium">{p.period_label}{p.is_demo && <span className="ml-1"><DemoBadge /></span>}</td>
              <td className="text-sm">{src?.publisher || src?.name || '—'}</td>
              <td className="num text-right font-medium whitespace-nowrap">{fmtTonnes(p.net_weight_kg, lang)}</td>
              <td><ChangeCell pct={p.change_pct} /></td>
              <td className="num text-right whitespace-nowrap">{p.usd_value !== null ? `${fmtCompact(p.usd_value, lang)} USD` : '—'}</td>
              <td className="text-sm text-muted">
                {p.summed_from_months ? t('archive.t.summedMonths') : t('archive.t.declared')}
                {p.summed_from_partners && <> · {t('archive.t.summedPartners')}</>}
                {p.data_status && p.data_status !== 'published' && <span className="ml-1"><StatusBadge status={p.data_status} /></span>}
              </td>
              <td className="whitespace-nowrap"><span className="mr-1.5">{fmtDate(p.published_at, lang)}</span><DocLink url={p.source_url} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function YtdBlock({ d }: { d: TradeHistoryResponse }) {
  const { t, lang } = useI18n()
  const months = monthNames(lang)
  if (!d.ytd.length) return null
  return (
    <div className="flex flex-col gap-4">
      {d.ytd.map((s) => {
        const range = s.through_month === 1 ? months[0] : `${months[0]}–${months[s.through_month - 1]}`
        return (
          <div key={s.source?.key ?? 'x'} className="min-w-0">
            <p className="text-sm text-muted mb-2">{t('archive.t.ytdIntro', { range })} — {s.source?.publisher || s.source?.name}</p>
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-3">
              {s.years.map((y) => (
                <div key={y.year} className="border border-line-soft rounded-sm p-3 bg-paper min-w-0">
                  <div className="eyebrow">{range} {y.year}</div>
                  <div className="num text-[1.4rem] leading-tight mt-0.5">{y.complete ? fmtTonnes(y.net_weight_kg, lang) : '—'}</div>
                  {!y.complete && <div className="text-sm text-warn">{t('archive.t.ytdMissing', { n: y.months, m: s.through_month })}</div>}
                  {y.complete && <div className="text-sm"><ChangeCell pct={y.change_pct} /></div>}
                  {y.published_at && <div className="text-[0.78rem] text-muted mt-1">{t('prov.published')} {fmtDate(y.published_at, lang)}</div>}
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function TradeArchive() {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const { set, options, sel } = useTradeSelection()
  const q = useQuery({
    queryKey: ['archive', 'trade', sel],
    queryFn: () => api.get<TradeHistoryResponse>('/archive/trade', { reporter: sel!.reporter, partner: sel!.partner, flow: sel!.flow }),
    enabled: sel !== null,
    placeholderData: keepPreviousData,
  })
  const reps = options.data?.reporters ?? []
  const rep = reps.find((r) => r.iso3 === sel?.reporter)
  const flows = (['import', 'export'] as const).filter((f) => rep?.flows[f])
  const partners = rep?.flows[sel?.flow ?? 'import']?.partners ?? []
  const d = q.data
  const chart = useMemo(() => {
    if (!d) return { rows: [], keys: [] as string[] }
    const keys = d.annual.map((s) => s.source?.key ?? '?')
    const years = [...new Set(d.annual.flatMap((s) => s.points.map((p) => p.period_label)))].sort()
    const rows = years.map((y) => {
      const row: Record<string, string | number | null> = { year: y }
      for (const s of d.annual) row[s.source?.key ?? '?'] = s.points.find((p) => p.period_label === y)?.net_weight_kg ?? null
      return row
    })
    return { rows, keys }
  }, [d])
  const names = Object.fromEntries((d?.annual ?? []).map((s) => [s.source?.key ?? '?', s.source?.publisher || s.source?.name || '?']))

  if (options.isLoading) return <Loading />
  if (options.error) return <ErrorBlock error={options.error} onRetry={() => options.refetch()} />
  if (!reps.length || !sel) return <Panel><EmptyState hint={t('archive.t.noOptions')} /></Panel>

  return (
    <div className="flex flex-col gap-5">
      <Panel bodyClassName="p-4">
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-end">
          <label className="block min-w-0">
            <span className="label">{t('archive.t.reporter')}</span>
            <select className="field" value={sel.reporter} onChange={(e) => set({ dichiarante: e.target.value, partner: null })}>
              {reps.map((r) => <option key={r.iso3} value={r.iso3}>{country(r.iso3)}</option>)}
            </select>
          </label>
          <div>
            <span className="label">{t('archive.t.flow')}</span>
            <Segmented size="sm" value={sel.flow} onChange={(v) => set({ flusso: v, partner: null })}
              options={flows.map((f) => ({ value: f, label: t(`archive.flow.${f}`) }))} />
          </div>
          <label className="block min-w-0">
            <span className="label">{t('archive.t.partner')}</span>
            <select className="field" value={sel.partner} onChange={(e) => set({ partner: e.target.value })}>
              {partners.map((p) => <option key={p} value={p}>{p === 'WLD' ? t('archive.t.partnerTotal') : country(p)}</option>)}
            </select>
          </label>
        </div>
      </Panel>

      {q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
        : !d ? <Panel><Loading /></Panel>
        : !d.available ? <Panel><EmptyState hint={t('archive.t.noData')} /></Panel>
        : (
          <>
            {d.annual.length > 0 && (
              <Panel
                eyebrow={`${t(`archive.flow.${d.flow}`)} · ${country(d.reporter)}${d.partner !== 'WLD' ? ` · ${country(d.partner)}` : ''}`}
                title={t('archive.t.chartTitle')}
                actions={<FreshnessBadge status={d.annual[0].freshness.status} ageDays={d.annual[0].freshness.age_days} />}
                footer={t('archive.t.oneSource')}
              >
                <div className="h-[260px] -ml-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chart.rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke="#E9E3D3" vertical={false} />
                      <XAxis dataKey="year" tick={{ fontSize: 12, fill: '#6B6A62' }} tickLine={false} axisLine={{ stroke: '#DDD6C4' }} />
                      <YAxis tick={{ fontSize: 12, fill: '#6B6A62' }} tickLine={false} axisLine={false} width={74}
                        tickFormatter={(v: number) => `${fmtNumber(v / 1000, lang, 0)} t`} />
                      <Tooltip formatter={(v: number, k: string) => [fmtTonnes(v, lang), names[k] ?? k]} />
                      {chart.keys.length > 1 && <Legend formatter={(k: string) => names[k] ?? k} wrapperStyle={{ fontSize: 13 }} />}
                      {chart.keys.map((k, i) => <Bar key={k} dataKey={k} fill={SOURCE_COLORS[i % SOURCE_COLORS.length]} isAnimationActive={false} maxBarSize={44} />)}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-4"><TradeYearsTable d={d} /></div>
              </Panel>
            )}
            {d.ytd.length > 0 && (
              <Panel title={t('archive.t.ytdTitle')}
                footer={<SourceLine p={{ source: d.ytd[0].source, is_demo: d.ytd[0].is_demo }} />}>
                <YtdBlock d={d} />
              </Panel>
            )}
            {d.excluded_partial.length > 0 && (
              <Note>{t('archive.t.excluded', { list: d.excluded_partial.map((x) => t(x.months_count === 1 ? 'archive.t.excludedItemOne' : 'archive.t.excludedItem', { y: x.period_label, n: x.months_count })).join(', ') })}</Note>
            )}
            {d.discrepancies.map((x) => (
              <Note key={x.period_label} tone="warn">{t('archive.t.discrepancy', { p: x.period_label, d: `${fmtNumber(x.diff_pct, lang, 1)}%` })}</Note>
            ))}
          </>
        )}
    </div>
  )
}
