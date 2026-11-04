// One region, last 12 months: temperature difference and rainfall in % of normal (charts and table),
// the NASA POWER points behind each value with their exact queries, and the curated context.
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, ExternalLink, Flower2, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_TICK, AXIS_TICK_MONO, GRID_STROKE } from '@/components/trade/bits'
import { Badge, ErrorBlock, Loading, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtNumber, fmtPeriod } from '@/lib/format'
import { CONDITION_COLORS, countryOf, fmtAnomaly, fmtPctOfNormal, monthName, monthSpan, regionName } from './format'
import { ConditionBadge, FlagLine } from './parts'
import type { HarvestRegion, RegionDetailResponse, RegionMonth } from './types'

export function RegionDetail({ regionKey, onClose }: { regionKey: string; onClose: () => void }) {
  const { t } = useI18n()
  const q = useQuery({
    queryKey: ['harvest', 'weather', regionKey],
    queryFn: () => api.get<RegionDetailResponse>(`/harvest/weather/${encodeURIComponent(regionKey)}`),
  })
  const ref = useRef<HTMLDivElement>(null)
  // Picked from the table further down (phone, tablet): bring the panel into view.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const top = el.getBoundingClientRect().top
    if (top < 0 || top > window.innerHeight - 120) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [regionKey])
  return (
    <div ref={ref} className="min-w-0 scroll-mt-4">
    <Panel
      eyebrow={t('harvest.detail.eyebrow')}
      title={q.data ? <RegionTitle r={q.data.region} /> : regionKey}
      className="min-w-0"
      actions={<button type="button" className="btn-ghost !px-2 !py-1" onClick={onClose} aria-label={t('harvest.detail.close')}><X size={18} /></button>}
    >
      {q.isLoading ? <Loading /> : q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} /> : q.data ? (
        <RegionBody r={q.data.region} />
      ) : null}
    </Panel>
    </div>
  )
}

function RegionTitle({ r }: { r: HarvestRegion }) {
  const { lang } = useI18n()
  return <span>{regionName(r, lang)} <span className="font-sans text-[0.9rem] font-normal text-muted">· {countryOf(r, lang)}</span></span>
}

export function RegionBody({ r }: { r: HarvestRegion & { months: RegionMonth[] } }) {
  const { t, lang } = useI18n()
  const ctx = r.context
  const pointNo = new Map(r.points.map((p, i) => [p.key, i + 1]))
  const rows = r.months.map((m) => ({
    label: monthName(Number(m.period_label.slice(5)), lang), m,
    temp: m.temp_anomaly_c, rain: m.precip_pct,
  }))
  return (
    <div className="flex flex-col gap-4">
      {r.flags.length > 0 ? (
        <div className="flex flex-col gap-1.5">{r.flags.map((f) => <FlagLine key={`${f.rule}-${f.months[0]}`} flag={f} />)}</div>
      ) : (
        <div><ConditionBadge condition={r.condition} /></div>
      )}

      {!r.has_data ? <p className="text-muted">{t('harvest.map.tipNoData')}</p> : (
        <div>
          {/* side by side only where the panel is wide (full-width on tablets); stacked beside the map */}
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
            <MiniChart title={t('harvest.detail.chartTemp')} rows={rows} dataKey="temp" refs={[0, 2]}
              fmt={(v) => fmtAnomaly(v, lang)} color={(v) => (v !== null && v >= 2 ? CONDITION_COLORS.heat_stress : '#8C8A80')} />
            <MiniChart title={t('harvest.detail.chartRain')} rows={rows} dataKey="rain" refs={[60, 100, 160]}
              fmt={(v) => fmtPctOfNormal(v, lang)}
              color={(v) => (v !== null && v < 60 ? CONDITION_COLORS.drought_watch : v !== null && v > 160 ? CONDITION_COLORS.wet_season : '#8C8A80')} />
          </div>
          <div className="mt-1 text-[0.75rem] text-muted">{t('harvest.detail.chartLegend')}</div>
        </div>
      )}

      {r.has_data && (
        <div className="-mx-5 overflow-x-auto px-5">
          <table className="w-full min-w-[360px] text-[0.88rem]">
            <thead>
              <tr className="border-b border-line bg-paper text-left text-[0.68rem] uppercase tracking-wider text-muted">
                <th className="py-1.5 px-2 font-medium">{t('harvest.detail.month')}</th>
                <th className="py-1.5 px-2 font-medium text-right">{t('harvest.detail.tempAnom')}</th>
                <th className="py-1.5 px-2 font-medium text-right">{t('harvest.detail.rainPct')}</th>
                <th className="py-1.5 px-2 font-medium" title={t('harvest.detail.queriesTitle')}>{t('harvest.detail.queries')}</th>
              </tr>
            </thead>
            <tbody>
              {[...r.months].reverse().map((m) => (
                <tr key={m.period_label} className="border-b border-line-soft align-top last:border-0">
                  <td className="py-1.5 px-2">
                    <span className="whitespace-nowrap">
                      {fmtPeriod(m.period_label, lang)}
                      {m.flowering && <Flower2 size={13} className="ml-1 inline text-gold-dark" aria-label={t('harvest.table.inFlowering')} />}
                    </span>
                    {m.points_with_data > 0 && (
                      <span className="block text-[0.74rem]">
                        {m.data_status === 'provisional'
                          ? <span className="text-warn" title={t('harvest.table.provisionalTitle')}>{t('harvest.detail.provisional')}</span>
                          : <span className="text-forest-700">{t('harvest.detail.final')}</span>}
                        {m.points_with_data < m.points_total && (
                          <span className="text-muted"> · {t('harvest.table.pointsPartial', { n: m.points_with_data, total: m.points_total })}</span>
                        )}
                      </span>
                    )}
                  </td>
                  {m.points_with_data ? (
                    <>
                      <td className="py-1.5 px-2 text-right">
                        <span className="num whitespace-nowrap">{fmtAnomaly(m.temp_anomaly_c, lang)}</span>
                        <span className="block text-[0.74rem] text-muted">
                          <span className="num whitespace-nowrap">{fmtNumber(m.temp_mean_c, lang, 1)} °C</span>{' '}
                          <span className="whitespace-nowrap">({t('harvest.detail.normalShort')} <span className="num">{fmtNumber(m.normal_temp_c, lang, 1)}</span>)</span>
                        </span>
                      </td>
                      <td className="py-1.5 px-2 text-right">
                        <span className="num whitespace-nowrap">{fmtPctOfNormal(m.precip_pct, lang)}</span>
                        {m.exceptional_points.length > 0 && (
                          <span title={t('harvest.table.exceptionalTitle', { points: m.exceptional_points.join(', ') })}>
                            <AlertTriangle size={12} className="ml-1 inline text-warn" />
                          </span>
                        )}
                        <span className="block text-[0.74rem] text-muted">
                          <span className="num whitespace-nowrap">{fmtNumber(m.precip_mm, lang, 0)} mm</span>{' '}
                          <span className="whitespace-nowrap">({t('harvest.detail.normalShort')} <span className="num">{fmtNumber(m.precip_normal_mm, lang, 0)}</span>)</span>
                        </span>
                      </td>
                      <td className="py-1.5 px-2">
                        <div className="flex flex-wrap gap-x-2 gap-y-0.5">
                          {(m.points ?? []).map((p) => p.source_url && (
                            <a key={p.point} href={p.source_url} target="_blank" rel="noreferrer"
                              className={clsx('link inline-flex items-center gap-0.5 whitespace-nowrap text-[0.8rem]', p.exceptional && 'text-warn')}
                              aria-label={`${t('prov.original')}: ${p.name}`}
                              title={`${p.name}: ${fmtNumber(p.precip_mm, lang, 0)} mm, ${fmtAnomaly(p.temp_anomaly_c, lang)} · ${t(`harvest.detail.basis.${p.basis ?? 'monthly'}`)}`}>
                              {pointNo.get(p.point) ?? '?'}<ExternalLink size={11} />
                            </a>
                          ))}
                        </div>
                      </td>
                    </>
                  ) : (
                    <td colSpan={3} className="py-1.5 px-2 text-muted">{t('harvest.table.noData')}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="text-[0.82rem] text-muted">
        <span className="font-medium text-charcoal-soft">{t('harvest.detail.points')}:</span>{' '}
        {r.points.map((p, i) => `${i + 1} ${p.name} (${fmtNumber(p.lat, lang, 2)}, ${fmtNumber(p.lon, lang, 2)})`).join(' · ')}
      </div>

      <div className="rounded-sm border border-dashed border-line bg-paper px-3 py-2.5">
        <div className="mb-1 flex items-center gap-2">
          <Badge tone="outline">{t('harvest.table.contextShort')}</Badge>
          <span className="text-[0.85rem] font-medium text-charcoal-soft">{t('harvest.detail.contextTitle')}</span>
        </div>
        <dl className="grid gap-x-4 gap-y-1 text-[0.85rem] sm:grid-cols-[auto_minmax(0,1fr)]">
          <dt className="text-muted">{t('harvest.detail.varieties')}</dt>
          <dd className="text-charcoal-soft">{(lang === 'it' ? ctx.varieties_it : ctx.varieties_en).join(', ')}</dd>
          <dt className="text-muted">{t('harvest.detail.floweringMonths')}</dt>
          <dd className="text-charcoal-soft">{monthSpan(ctx.flowering_months, lang)}</dd>
          <dt className="text-muted">{t('harvest.detail.harvest')}</dt>
          <dd className="text-charcoal-soft">{monthSpan(ctx.harvest_months, lang)}</dd>
        </dl>
        {(lang === 'it' ? ctx.note_it : ctx.note_en) && <p className="mt-1 text-[0.85rem] text-charcoal-soft">{lang === 'it' ? ctx.note_it : ctx.note_en}</p>}
      </div>
    </div>
  )
}

type ChartRow = { label: string; m: RegionMonth; temp: number | null; rain: number | null }

function MiniChart({ title, rows, dataKey, refs, fmt, color }: {
  title: string; rows: ChartRow[]; dataKey: 'temp' | 'rain'; refs: number[]
  fmt: (v: number | null) => string; color: (v: number | null) => string
}) {
  const { t, lang } = useI18n()
  return (
    <div className="min-w-0">
      <div className="eyebrow mb-1">{title}</div>
      <div className="h-[170px]" role="img" aria-label={title}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 6, right: 4, bottom: 0, left: -8 }}>
            <CartesianGrid stroke={GRID_STROKE} vertical={false} />
            <XAxis dataKey="label" tick={{ ...AXIS_TICK, fontSize: 11 }} tickLine={false} interval={0} axisLine={{ stroke: '#DDD6C4' }} />
            <YAxis width={44} tick={{ ...AXIS_TICK_MONO, fontSize: 11 }} tickLine={false} axisLine={false}
              tickFormatter={(v: number) => fmtNumber(v, lang, 0)} />
            {refs.map((v) => <ReferenceLine key={v} y={v} stroke={v === 0 || v === 100 ? '#B9B4A6' : '#D9CFB4'} strokeDasharray={v === 0 || v === 100 ? undefined : '4 3'} />)}
            <Tooltip
              isAnimationActive={false}
              cursor={{ fill: 'rgba(168,135,58,0.08)' }}
              content={(p) => {
                if (!p.active || !p.payload?.length) return null
                const row = p.payload[0].payload as ChartRow
                return (
                  <div className="rounded-sm border border-line bg-white px-2.5 py-1.5 text-[0.8rem] shadow-[0_4px_16px_rgba(31,33,32,0.10)]">
                    <div className="font-medium text-charcoal">{fmtPeriod(row.m.period_label, lang)}{row.m.flowering ? ` · ${t('harvest.table.inFlowering')}` : ''}</div>
                    <div className="num">{fmt(row[dataKey])}</div>
                    {row.m.data_status === 'provisional' && <div className="text-warn">{t('harvest.table.provisionalTitle')}</div>}
                  </div>
                )
              }}
            />
            <Bar dataKey={dataKey} isAnimationActive={false} maxBarSize={22} radius={[2, 2, 0, 0]}>
              {rows.map((r) => (
                <Cell key={r.m.period_label} fill={color(r[dataKey])} fillOpacity={r.m.flowering ? 1 : 0.45}
                  stroke={r.m.data_status === 'provisional' ? '#7A5414' : undefined} strokeDasharray={r.m.data_status === 'provisional' ? '3 2' : undefined} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
