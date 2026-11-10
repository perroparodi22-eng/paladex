// Leading exporters / importers for one year: volume, value, unit value, y/y, provenance per row.
import clsx from 'clsx'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { DemoBadge, ErrorBlock, Loading, Panel, Segmented, StatusBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { BasisMarks, DataMissing, fmtT, fmtUsd, fmtUsdM, fmtUv, nameOf, ShareBar, SourcesFooter, YoY } from './bits'
import type { LeaderRow, LeadersResponse, TradeFlow, TradeMetric } from './types'

const INITIAL_ROWS = 10

export function LeadersTable({ flow, data, isLoading, error, refetch, basis, onBasis, metric, year }: {
  flow: TradeFlow
  data: LeadersResponse | undefined
  isLoading: boolean
  error: unknown
  refetch: () => void
  basis: 'declared' | 'mirror'
  onBasis?: (b: 'declared' | 'mirror') => void
  metric: TradeMetric
  year: number | null
}) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const [expanded, setExpanded] = useState(false)
  const rows = data?.rows ?? []
  const shown = expanded ? rows : rows.slice(0, INITIAL_ROWS)
  const max = Math.max(1, ...rows.map((r) => (metric === 'volume' ? r.net_weight_kg : r.usd_value) ?? 0))
  const anyDemo = rows.some((r) => r.is_demo)
  const mirror = basis === 'mirror'
  const title = flow === 'export' ? t('trade.leaders.exporters') : t('trade.leaders.importers')
  const sub = mirror ? t('trade.leaders.mirrorSub') : flow === 'export' ? t('trade.leaders.exportersSub') : t('trade.leaders.importersSub')
  const anySummed = rows.some((r) => r.summed_from_partners)
  const anyMonths = rows.some((r) => r.summed_from_months)

  const footer = data && rows.length > 0 ? (
    <SourcesFooter
      sources={data.sources}
      extra={
        <>
          {mirror && data.reporters && (
            <div>{t('trade.leaders.mirrorReporters', { n: data.reporters.length, list: data.reporters.map((r) => nameOf(r, lang, country)).join(', ') })}</div>
          )}
          {data.mixed_sources && <div>{t('trade.leaders.mixedSources')}</div>}
          {(anySummed || anyMonths) && (
            <div>{[anySummed && t('trade.basis.legendPartners'), anyMonths && t('trade.basis.legendMonths')].filter(Boolean).join(' · ')}</div>
          )}
          {data.incomplete.length > 0 && (
            <div>{t('trade.leaders.incomplete', { list: data.incomplete.map((i) => t('trade.leaders.incompleteItem', { c: nameOf(i, lang, country), n: i.months_count })).join(', ') })}</div>
          )}
        </>
      }
    />
  ) : undefined

  return (
    <Panel title={title} eyebrow={sub} className="min-w-0" bodyClassName="!p-0" actions={anyDemo ? <DemoBadge /> : undefined} footer={footer}>
      {onBasis && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-2.5 border-b border-line-soft bg-paper/60">
          <Segmented size="sm" value={basis} onChange={onBasis} options={[
            { value: 'declared', label: t('trade.leaders.basis.declared') },
            { value: 'mirror', label: t('trade.leaders.basis.mirror') },
          ]} />
          <span className="text-[0.78rem] leading-snug text-muted flex-1 min-w-[200px]">{t('trade.leaders.basisShort')}</span>
        </div>
      )}
      {isLoading ? <Loading /> : error ? <div className="p-4"><ErrorBlock error={error} onRetry={refetch} /></div> : !data || rows.length === 0 ? (
        <div className="px-5">
          <DataMissing
            what={year ? (flow === 'export' ? t('trade.leaders.noExports', { y: year }) : t('trade.leaders.noImports', { y: year })) : undefined}
            providers={data?.providers ?? []}
            fallback={t('trade.empty.fallbackSources')}
          >
            {flow === 'export' && !mirror && onBasis && (
              <button type="button" className="btn-secondary !py-1.5 text-[0.9rem]" onClick={() => onBasis('mirror')}>{t('trade.leaders.tryMirror')}</button>
            )}
          </DataMissing>
        </div>
      ) : (
        <>
          {/* Phones: the table keeps a readable width and scrolls sideways inside its panel. */}
          <div className="relative overflow-x-auto">
          <table className="w-full min-w-[31rem] table-fixed text-[0.92rem]">
            <colgroup>
              <col className="w-[2.6rem]" />
              <col />
              <col className="w-[5.4rem]" />
              <col className="w-[5rem]" />
              <col className="w-[4.2rem]" />
              <col className="w-[5.4rem]" />
            </colgroup>
            <thead>
              <tr className="border-b border-line bg-paper text-left text-[0.7rem] uppercase tracking-wider text-muted">
                <th className="py-2 pl-5 font-medium">{t('trade.leaders.col.rank')}</th>
                <th className="py-2 px-2 font-medium">{t('trade.leaders.col.country')}</th>
                <th className={clsx('py-2 px-2 font-medium text-right', metric === 'volume' && 'text-charcoal')}>{t('trade.leaders.col.tonnes')}</th>
                <th className={clsx('py-2 px-2 font-medium text-right', metric === 'value' && 'text-charcoal')}>{t('trade.leaders.col.usdM')}</th>
                <th className="py-2 px-2 font-medium text-right">{t('trade.leaders.col.uv')}</th>
                <th className="py-2 pl-2 pr-5 font-medium text-right">{t('trade.leaders.col.yoy')}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => <Row key={r.iso3} r={r} max={max} metric={metric} mirror={mirror} />)}
            </tbody>
          </table>
          </div>
          {rows.length > INITIAL_ROWS && (
            <div className="px-5 py-2 border-t border-line-soft">
              <button type="button" className="link text-[0.88rem]" onClick={() => setExpanded((v) => !v)}>
                {expanded ? t('trade.leaders.showLess', { n: INITIAL_ROWS }) : t('trade.leaders.showAll', { n: rows.length })}
              </button>
            </div>
          )}
        </>
      )}
    </Panel>
  )
}

function Row({ r, max, metric, mirror }: { r: LeaderRow; max: number; metric: TradeMetric; mirror: boolean }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const mag = (metric === 'volume' ? r.net_weight_kg : r.usd_value) ?? 0
  const prevTitle = mirror
    ? (r.yoy_like_for_like_reporters ? t('trade.leaders.yoyLfl', { n: r.yoy_like_for_like_reporters }) : t('trade.leaders.noPrev'))
    : r.prev ? t('trade.leaders.prevTitle', {
      y: r.prev.year,
      v: metric === 'value' && r.prev.usd_value !== null ? fmtUsd(r.prev.usd_value, lang) : `${fmtT(r.prev.net_weight_kg, lang)} t`,
    }) : t('trade.leaders.noPrev')
  const srcTitle = [
    `${t('prov.source')}: ${r.source ? r.source.publisher || r.source.name : r.sources_list?.map((s) => s.publisher || s.name).join(', ')}`,
    `${t('prov.period')}: ${r.period_label}`,
    r.published_at ? `${t('prov.published')} ${fmtDate(r.published_at, lang)}` : null,
    mirror && r.reporters ? `${t('trade.leaders.declaredBy')}: ${r.reporters.map((x) => country(x)).join(', ')}` : null,
  ].filter(Boolean).join('\n')
  const yoy = metric === 'value' && !mirror ? r.yoy_value_pct : r.yoy_volume_pct
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-ivory/50">
      <td className="py-2 pl-5 num text-[0.8rem] text-muted align-top pt-[0.6rem]">{r.rank}</td>
      <td className="py-2 px-2">
        {/* flex-wrap: in a narrow column the badges move under the name instead of cutting it
            to "Stati…" (phones, and the longer English "ESTIMATE") */}
        <div className="flex flex-wrap items-center gap-y-1 min-w-0" title={srcTitle}>
          <Link to={r.link} className="truncate text-charcoal hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2">
            {nameOf(r, lang, country)}
          </Link>
          <BasisMarks summedPartners={r.summed_from_partners} partners={r.partners_count} summedMonths={r.summed_from_months} />
          {r.data_status && !['published', 'live', 'demo'].includes(r.data_status) && <span className="ml-1.5"><StatusBadge status={r.data_status} /></span>}
        </div>
        <ShareBar pct={(mag / max) * 100} className="mt-1 max-w-[200px]" />
      </td>
      <td className="py-2 px-2 num text-right text-charcoal align-top pt-[0.5rem]">{fmtT(r.net_weight_kg, lang)}</td>
      <td className="py-2 px-2 num text-right text-charcoal-soft align-top pt-[0.5rem]"
        title={r.value !== null && r.currency ? `${fmtNumber(r.value, lang, 0)} ${r.currency}${r.value_basis ? ` (${r.value_basis})` : ''}` : undefined}>
        {fmtUsdM(r.usd_value, lang)}
        {r.fx_missing && <BasisMarks fxMissing />}
      </td>
      <td className="py-2 px-2 num text-right text-charcoal-soft align-top pt-[0.5rem]">{fmtUv(r.unit_value_usd_per_kg, lang)}</td>
      <td className="py-2 pl-2 pr-5 text-right align-top pt-[0.5rem]"><YoY pct={yoy} title={prevTitle} /></td>
    </tr>
  )
}
