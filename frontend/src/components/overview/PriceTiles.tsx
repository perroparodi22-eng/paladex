import clsx from 'clsx'
import { Info } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DemoBadge, FreshnessBadge, StatusBadge } from '@/components/ui'
import { CorrectionBadge } from '@/components/corrections/CorrectionBadge'
import { useI18n } from '@/i18n'
import { fmtAgo, fmtDate, fmtNumber, fmtPeriod } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { colorLabel } from '@/components/prices/utils'
import { BlockEmpty, BlockHead, BlockStamp, Delta, SectionLink } from './parts'
import type { PriceTile, PricesBlock } from './types'

const SPARK_LINE = '#8FB5A2'   // de-emphasised history (forest-300)
const SPARK_NOW = '#A8873A'    // latest published point (gold)

function SparkTip({ active, payload, currency }: { active?: boolean; payload?: { payload: { period_label: string; value: number } }[]; currency: string }) {
  const { lang } = useI18n()
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-sm border border-line bg-white px-2 py-1 text-[0.75rem] shadow-panel">
      <span className="text-muted">{fmtPeriod(p.period_label, lang)}</span>{' '}
      <span className="num text-charcoal">{fmtNumber(p.value, lang, 2)} {currency}/kg</span>
    </div>
  )
}

function Sparkline({ tile }: { tile: PriceTile }) {
  const data = tile.spark
  if (data.length < 2) return <div className="h-9" />
  const last = data[data.length - 1]
  return (
    <div className="-mx-1 h-9" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 5, bottom: 4, left: 5 }}>
          <XAxis dataKey="period_label" hide />
          <YAxis hide domain={['dataMin', 'dataMax']} />
          <Tooltip content={<SparkTip currency={tile.currency} />} cursor={{ stroke: '#DDD6C4' }} isAnimationActive={false} />
          <Line type="monotone" dataKey="value" stroke={SPARK_LINE} strokeWidth={1.6} dot={false} isAnimationActive={false}
            activeDot={{ r: 3, fill: '#143A2B', stroke: '#fff', strokeWidth: 1 }} />
          <ReferenceDot x={last.period_label} y={last.value} r={3} fill={SPARK_NOW} stroke="#fff" strokeWidth={1} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function Tile({ tile, showType, twoLineDetail }: { tile: PriceTile; showType: boolean; twoLineDetail: boolean }) {
  const { t, lang } = useI18n()
  const { country, variety, priceType } = useLabels()
  const origin = tile.origin_iso3 ? country(tile.origin_iso3) : tile.origin_label || country(tile.market_iso3)
  const main = tile.usd_per_kg ?? (tile.currency === 'USD' ? tile.price_per_kg : null)
  const mainCur = main !== null ? 'USD' : tile.currency
  const mainVal = main ?? tile.price_per_kg
  const eur = tile.eur_per_kg ?? (tile.currency === 'EUR' ? tile.price_per_kg : null)
  const publisher = tile.source?.publisher || tile.source?.name || '—'
  const tip = t('overview.prices.tooltip', {
    source: tile.source?.name ?? '—',
    period: fmtPeriod(tile.period_label, lang),
    published: fmtDate(tile.published_at, lang),
    collected: tile.collected_at ? fmtAgo(tile.collected_at, lang) : '—',
    native: `${fmtNumber(tile.price_value, lang, 2)} ${tile.currency}/${tile.unit}${tile.terms ? ` · ${tile.terms}` : ''}`,
  })
  // USDA colour grades arrive as raw English keys ("light amber"): name them like the Prices page.
  const detail = [variety(tile.variety), tile.color_grade ? colorLabel(tile.color_grade, t) : null].filter(Boolean).join(' · ')

  return (
    <Link to={tile.link} title={tip} className="group flex min-w-0 flex-col bg-white px-3.5 pb-3 pt-3 transition-colors hover:bg-paper">
      <div className="min-w-0">
        <div className="flex items-center justify-between gap-1.5">
          <span className="truncate text-[0.98rem] font-semibold leading-tight text-charcoal group-hover:text-forest-800">{origin}</span>
          {tile.is_demo && <span className="shrink-0"><DemoBadge /></span>}
        </div>
        {/* Colour grades ("Ambra extra chiaro") tell the series apart: two lines rather than an
            ellipsis, reserved in every tile of the block so the prices stay aligned. */}
        <div className={clsx('text-[0.8rem] text-muted', twoLineDetail ? 'line-clamp-2 min-h-[2.5em] leading-[1.25]' : 'truncate')} title={detail}>{detail}</div>
        {showType && <div className="truncate text-[0.72rem] uppercase tracking-wide text-gold-dark">{priceType(tile.price_type)}</div>}
      </div>
      <div className="mt-2 flex items-baseline gap-1">
        <span className="num text-[1.6rem] leading-none text-charcoal">{fmtNumber(mainVal, lang, 2)}</span>
        <span className="text-[0.74rem] text-muted">{mainCur}{t('overview.prices.perKg')}</span>
      </div>
      <div className="num mt-0.5 text-[0.8rem] text-muted">
        {eur !== null && mainCur !== 'EUR' ? `${fmtNumber(eur, lang, 2)} EUR${t('overview.prices.perKg')}` : mainCur === 'EUR' ? ' ' : `EUR: ${t('overview.prices.noFx')}`}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[0.8rem]">
        <Delta value={tile.mom_pct} suffix={t('overview.prices.mom')}
          title={tile.mom_period_label ? t('overview.prices.momFull', { p: fmtPeriod(tile.mom_period_label, lang) }) : undefined} />
        <Delta value={tile.yoy_pct} suffix={t('overview.prices.yoy')}
          title={tile.yoy_period_label ? t('overview.prices.yoyFull', { p: fmtPeriod(tile.yoy_period_label, lang) }) : undefined} />
      </div>
      <div className="mt-1"><Sparkline tile={tile} /></div>
      <div className="mt-1.5 border-t border-line-soft pt-1.5 text-[0.75rem] text-muted">
        <div className="truncate"><span className="num text-charcoal-soft">{fmtPeriod(tile.period_label, lang)}</span> · {publisher}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1">
          {tile.correction && <CorrectionBadge c={tile.correction} compact />}
          <FreshnessBadge status={tile.freshness.status} ageDays={tile.freshness.age_days} />
          {!tile.is_demo && !['published', 'live'].includes(tile.data_status) && <StatusBadge status={tile.data_status} />}
        </div>
      </div>
    </Link>
  )
}

export function PriceTiles({ block }: { block: PricesBlock }) {
  const { t } = useI18n()
  const { priceType } = useLabels()
  const tiles = block.items
  const anyDemo = tiles.some((x) => x.is_demo)
  const sub = tiles.length && !block.mixed_price_types ? `${priceType(block.price_types[0])} · USD/kg · EUR/kg` : undefined

  return (
    <section className="panel">
      <BlockHead
        eyebrow={t('overview.prices.eyebrow')}
        title={t('overview.prices.title')}
        sub={sub}
        right={<>{anyDemo && <DemoBadge />}<SectionLink to={block.link} label={t('overview.prices.allPrices')} /></>}
      />
      {tiles.length === 0 ? (
        <div className="px-5 py-4">
          <BlockEmpty what={t('overview.prices.emptyWhat')} providers={block.providers} fallbackSources={t('overview.prices.fallbackSources')} />
        </div>
      ) : (
        <div className={clsx('grid gap-px border-b border-line-soft bg-line-soft', tiles.length > 2 ? 'grid-cols-2 sm:grid-cols-4' : 'grid-cols-2')}>
          {tiles.map((tile) => <Tile key={tile.id} tile={tile} showType={block.mixed_price_types} twoLineDetail={tiles.some((x) => x.color_grade)} />)}
          {/* keep the grid rectangular when fewer than a full row */}
          {Array.from({ length: (4 - (tiles.length % 4)) % 4 }).map((_, i) => <div key={`f${i}`} className="hidden bg-white sm:block" />)}
        </div>
      )}
      <div className="space-y-1 px-5 py-2.5">
        {block.mixed_price_types && <p className="text-[0.8rem] text-warn">{t('overview.prices.mixedNote')}</p>}
        <BlockStamp updatedAt={block.updated_at} publishedAt={block.latest_published_at}>
          {block.sources.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              {t('prov.source')}: <span className="font-medium text-charcoal-soft">{s.publisher || s.name}</span>
              <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />
              <span aria-hidden>·</span>
            </span>
          ))}
        </BlockStamp>
        {tiles.length > 0 && (
          <p className="flex items-start gap-1.5 text-[0.76rem] text-muted"><Info size={13} className="mt-[0.15rem] shrink-0" />{t('overview.prices.basisNote')}</p>
        )}
      </div>
    </section>
  )
}
