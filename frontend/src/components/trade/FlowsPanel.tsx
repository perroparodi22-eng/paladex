// "Flussi": choose a market -> its top origins (or destinations) with share and unit value,
// and the trend of the selected partner (or of the total), one line per source.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { DemoBadge, ErrorBlock, FreshnessBadge, Loading, Note, Panel, Segmented, Select, SourceLine } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtNumber, fmtPct } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { BasisMarks, DataMissing, fmtT, fmtUsd, fmtUv, nameOf, ShareBar, YoY } from './bits'
import { SeriesChart } from './SeriesChart'
import type { FacetsResponse, FlowsResponse, SeriesResponse, TradeFlow, TradeFreq, TradeMetric } from './types'

/** Markets shown first in the selector (Parodi Group's own markets, then the big buyers). */
const MARKET_ORDER = ['ITA', 'DEU', 'USA', 'EU27', 'FRA', 'ESP', 'GBR', 'BEL', 'NLD', 'JPN', 'CHN', 'SAU']

export function FlowsPanel({ facets, year, metric }: { facets: FacetsResponse; year: number | null; metric: TradeMetric }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  // Deep links (e.g. from a data-quality issue: /commercio?reporter=USA&partner=ARG&flow=import)
  // open this panel on that market, flow and partner.
  const [sp] = useSearchParams()
  const linked = {
    reporter: sp.get('reporter')?.toUpperCase() || null,
    partner: sp.get('partner')?.toUpperCase() || 'WLD',
    flow: (sp.get('flow') === 'export' ? 'export' : 'import') as TradeFlow,
  }
  const [flow, setFlow] = useState<TradeFlow>(linked.flow)
  const reporters = useMemo(() => facets.reporters
    .filter((r) => r.flows[flow])
    .sort((a, b) => {
      const ia = MARKET_ORDER.indexOf(a.iso3)
      const ib = MARKET_ORDER.indexOf(b.iso3)
      if (ia !== -1 || ib !== -1) return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
      return nameOf(a, lang).localeCompare(nameOf(b, lang))
    }), [facets, flow, lang])
  const [reporter, setReporter] = useState<string | null>(linked.reporter)
  const [partner, setPartner] = useState(linked.partner)
  const [freq, setFreq] = useState<TradeFreq>('A')

  const rep = reporters.find((r) => r.iso3 === reporter) ?? reporters[0]
  // A new market or flow starts again from its total (but not on mount: keep a linked partner).
  const shownKey = useRef(`${rep?.iso3}|${flow}`)
  useEffect(() => {
    const k = `${rep?.iso3}|${flow}`
    if (shownKey.current === k) return
    shownKey.current = k
    setPartner('WLD')
  }, [rep?.iso3, flow])
  const panelRef = useRef<HTMLDivElement>(null)
  const linkedOnMount = useRef(Boolean(linked.reporter))
  useEffect(() => {
    if (linkedOnMount.current) panelRef.current?.scrollIntoView({ block: 'start' })
  }, [])
  const hasMonthly = Boolean(rep?.flows[flow]?.frequencies.includes('M'))
  useEffect(() => { if (!hasMonthly) setFreq('A') }, [hasMonthly])
  const repYears = rep?.flows[flow]?.years ?? []
  const askYear = year !== null && repYears.includes(year) ? year : undefined

  const flows = useQuery({
    queryKey: ['trade', 'flows', rep?.iso3, flow, askYear, metric],
    queryFn: () => api.get<FlowsResponse>('/trade/flows', { reporter: rep!.iso3, flow, year: askYear, metric, top: 10 }),
    enabled: Boolean(rep),
    placeholderData: keepPreviousData,
  })
  const series = useQuery({
    queryKey: ['trade', 'series', rep?.iso3, partner, flow, freq],
    queryFn: () => api.get<SeriesResponse>('/trade/series', { reporter: rep!.iso3, partner, flow, freq }),
    enabled: Boolean(rep),
    placeholderData: keepPreviousData,
  })

  const d = flows.data
  const repName = rep ? nameOf(rep, lang, country) : '—'
  const partnerName = partner === 'WLD' ? '' : nameOf(d?.rows.find((r) => r.iso3 === partner) ?? { iso3: partner }, lang, country)
  const seriesTitle = partner === 'WLD'
    ? t(flow === 'import' ? 'trade.series.subtitleImportTotal' : 'trade.series.subtitleExportTotal', { r: repName })
    : t(flow === 'import' ? 'trade.series.subtitleImport' : 'trade.series.subtitleExport', { r: repName, p: partnerName })

  return (
    <div ref={panelRef} className="scroll-mt-28">
    <Panel
      title={flow === 'import' ? t('trade.flows.title') : t('trade.flows.titleExport')}
      eyebrow={t('trade.flows.eyebrow')}
      actions={(d?.is_demo || series.data?.series.some((s) => s.is_demo)) ? <DemoBadge /> : undefined}
    >
      <div className="flex flex-wrap items-end gap-4 mb-4">
        <Select label={t('trade.flows.market')} value={rep?.iso3 ?? ''} onChange={(e) => setReporter(e.target.value)} className="w-[260px]">
          {reporters.map((r) => <option key={r.iso3} value={r.iso3}>{nameOf(r, lang, country)}</option>)}
        </Select>
        <div>
          <span className="label">{t('trade.flows.flow')}</span>
          <Segmented value={flow} onChange={setFlow} options={[
            { value: 'import', label: t('trade.flows.import') },
            { value: 'export', label: t('trade.flows.export') },
          ]} />
        </div>
        {d?.year && <div className="ml-auto text-right"><div className="eyebrow">{t('trade.year')}</div><div className="num text-[1.15rem]">{d.year}</div></div>}
      </div>
      {year !== null && askYear === undefined && d?.year && d.year !== year && (
        <div className="mb-3"><Note>{t('trade.flows.yearFallback', { c: repName, y: year, z: d.year })}</Note></div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          {flows.isLoading ? <Loading /> : flows.error ? <ErrorBlock error={flows.error} onRetry={() => flows.refetch()} /> : !d || !d.available ? (
            <DataMissing
              what={d?.total ? t('trade.flows.onlyTotal') : d?.year ? t('trade.flows.empty', { c: repName, y: d.year }) : t('trade.flows.emptyNoYear', { c: repName })}
              providers={d?.providers ?? facets.providers}
              fallback={t('trade.empty.fallbackSources')}
              compact
            />
          ) : (
            <FlowsTable d={d} partner={partner} onPartner={setPartner} flow={flow} />
          )}
        </div>
        <div className="min-w-0 xl:border-l xl:border-line-soft xl:pl-6">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
            <div className="min-w-0">
              <div className="eyebrow">{t('trade.series.title')} · {t('trade.series.unit')}</div>
              <div className="font-serif text-[1.05rem] font-semibold text-charcoal truncate">{seriesTitle}</div>
            </div>
            <div className="flex items-center gap-2">
              {partner !== 'WLD' && <button type="button" className="link text-[0.85rem]" onClick={() => setPartner('WLD')}>{t('trade.series.reset')}</button>}
              {hasMonthly && <Segmented size="sm" value={freq} onChange={setFreq} options={[
                { value: 'A', label: t('trade.series.freq.A') }, { value: 'M', label: t('trade.series.freq.M') },
              ]} />}
            </div>
          </div>
          {series.isLoading ? <Loading /> : series.error ? <ErrorBlock error={series.error} onRetry={() => series.refetch()} />
            : !series.data || !series.data.available ? <div className="h-[280px] flex items-center justify-center text-muted border border-dashed border-line rounded-sm">{t('trade.series.empty')}</div>
            : <SeriesChart data={series.data} height={280} />}
        </div>
      </div>
    </Panel>
    </div>
  )
}

function FlowsTable({ d, partner, onPartner, flow }: { d: FlowsResponse; partner: string; onPartner: (p: string) => void; flow: TradeFlow }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const total = d.total
  const altOthers = d.alternatives.filter((a) => a.source?.key !== d.source?.key)
  return (
    <div>
      <table className="w-full text-[0.93rem]">
        <thead>
          <tr className="border-b border-line bg-paper text-left text-[0.72rem] uppercase tracking-wider text-muted">
            <th className="py-2 pl-2 pr-1 font-medium w-7">#</th>
            <th className="py-2 px-2 font-medium">{flow === 'import' ? t('trade.flows.col.origin') : t('trade.flows.col.destination')}</th>
            <th className="py-2 px-2 font-medium text-right">t</th>
            <th className="py-2 px-2 font-medium w-[30%]">{t('trade.flows.col.share')}</th>
            <th className="py-2 px-2 font-medium text-right">{t('trade.leaders.col.uv')}</th>
            <th className="py-2 pl-2 pr-2 font-medium text-right whitespace-nowrap">{t('trade.leaders.col.yoy')}</th>
          </tr>
        </thead>
        <tbody>
          {d.rows.map((r) => (
            <tr key={r.iso3} onClick={() => onPartner(r.iso3)}
              className={clsx('border-b border-line-soft cursor-pointer', partner === r.iso3 ? 'bg-gold-pale/60' : 'hover:bg-ivory/60')}>
              <td className="py-2 pl-2 pr-1 num text-[0.8rem] text-muted">{r.rank}</td>
              <td className="py-2 px-2">
                {r.link ? (
                  <Link to={r.link} onClick={(e) => e.stopPropagation()} className="text-charcoal hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2">
                    {nameOf(r, lang, country)}
                  </Link>
                ) : <span className="text-charcoal-soft">{nameOf(r, lang, country)}</span>}
                {r.months_count !== null && r.months_count < 12 && <span className="ml-1.5 text-[0.75rem] text-muted num">{r.months_count}/12</span>}
              </td>
              <td className="py-2 px-2 num text-right">{fmtT(r.net_weight_kg, lang)}</td>
              <td className="py-2 px-2">
                <div className="flex items-center gap-2">
                  <ShareBar pct={r.share_volume_pct} className="flex-1" />
                  <span className="num text-[0.85rem] w-[3.4rem] text-right">{fmtPct(r.share_volume_pct, lang, 1, false)}</span>
                </div>
              </td>
              <td className="py-2 px-2 num text-right text-charcoal-soft"
                title={r.usd_value !== null ? fmtUsd(r.usd_value, lang) : undefined}>{fmtUv(r.unit_value_usd_per_kg, lang)}</td>
              <td className="py-2 pl-2 pr-2 text-right"><YoY pct={r.yoy_volume_pct}
                title={r.prev_net_weight_kg !== null ? `${(d.year ?? 0) - 1}: ${fmtT(r.prev_net_weight_kg, lang)} t` : t('trade.leaders.noPrev')} /></td>
            </tr>
          ))}
          {d.others && (
            <tr className="border-b border-line-soft text-charcoal-soft">
              <td />
              <td className="py-2 px-2 italic">{t('trade.flows.others', { n: d.others.count })}</td>
              <td className="py-2 px-2 num text-right">{fmtT(d.others.net_weight_kg, lang)}</td>
              <td className="py-2 px-2"><div className="flex items-center gap-2"><ShareBar pct={d.others.share_volume_pct} tone="forest" className="flex-1" /><span className="num text-[0.85rem] w-[3.4rem] text-right">{fmtPct(d.others.share_volume_pct, lang, 1, false)}</span></div></td>
              <td colSpan={2} />
            </tr>
          )}
          {d.unallocated && (
            <tr className="border-b border-line-soft text-muted">
              <td />
              <td className="py-2 px-2 italic">{t('trade.flows.unallocated')}</td>
              <td className="py-2 px-2 num text-right">{fmtT(d.unallocated.net_weight_kg, lang)}</td>
              <td className="py-2 px-2"><span className="num text-[0.85rem]">{fmtPct(d.unallocated.share_volume_pct, lang, 1, false)}</span></td>
              <td colSpan={2} />
            </tr>
          )}
          {total && (
            <tr onClick={() => onPartner('WLD')} className={clsx('cursor-pointer font-medium', partner === 'WLD' ? 'bg-gold-pale/60' : 'hover:bg-ivory/60')}>
              <td />
              <td className="py-2 px-2" title={d.share_basis === 'world_total' ? t('trade.flows.totalWorld') : t('trade.flows.totalPartners')}>
                {t('trade.flows.total')}
                {total.summed_from_partners && <BasisMarks summedPartners partners={total.partners_count} />}
              </td>
              <td className="py-2 px-2 num text-right">{fmtT(total.net_weight_kg, lang)}</td>
              <td className="py-2 px-2 num text-[0.85rem] text-muted" title={fmtUsd(total.usd_value, lang)}>100%</td>
              <td className="py-2 px-2 num text-right">{fmtUv(total.unit_value_usd_per_kg, lang)}</td>
              <td className="py-2 pl-2 pr-2 text-right"><YoY pct={total.yoy_volume_pct} /></td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="mt-3 flex flex-col gap-1 text-[0.8rem] text-muted">
        <div className="flex flex-wrap items-center gap-2">
          <SourceLine p={{ source: d.source ?? null, published_at: d.published_at, source_url: d.source_url, is_demo: d.is_demo, period_label: d.period_label ?? undefined }} />
          {d.freshness && <FreshnessBadge status={d.freshness.status} ageDays={d.freshness.age_days} />}
        </div>
        {d.complete === false && d.months_count && <div className="text-warn">{t('trade.flows.partial', { n: d.months_count })}</div>}
        {d.share_basis && <div>{t(`trade.flows.shareBasis.${d.share_basis}`)} {d.total?.value_basis ? `(${d.total.value_basis})` : ''}</div>}
        {altOthers.length > 0 && (
          <div>{t('trade.flows.altSources', { list: altOthers.map((a) => `${a.source?.publisher || a.source?.name}${a.months_count ? ` (${fmtNumber(a.months_count, lang)}/12)` : ''}`).join(', ') })}</div>
        )}
        <div>{t('trade.flows.clickHint')}</div>
      </div>
    </div>
  )
}
