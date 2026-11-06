import { ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DemoBadge, FreshnessBadge, StatusBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtPeriod, fmtTonnes } from '@/lib/format'
import { BlockEmpty, BlockHead, BlockStamp, Delta, SectionLink } from './parts'
import type { TradeBlock, TradeSide } from './types'
import { isMappedUrl, pageUrl } from '@/lib/links'
import { shortSourceName } from '@/components/countries/metrics'
import { fmtUsd } from '@/components/trade/bits'
import { fmtMonthSpan, prevSpan, type YtdLeaders } from '@/components/trade/ytd'

/** The year so far, one side (importers or exporters): each country with its OWN source and months,
 * against the same months of the year before. Not a ranking across sources: rows carry no rank. */
function YtdSide({ side, title }: { side: YtdLeaders | undefined; title: string }) {
  const { t, lang } = useI18n()
  if (!side || !side.rows.length) {
    return (
      <div className="min-w-0">
        <h3 className="font-sans text-[0.95rem] font-semibold text-charcoal">{title}</h3>
        <p className="mt-2 text-[0.88rem] text-muted">{t('overview.trade.ytd.none')}</p>
      </div>
    )
  }
  return (
    <div className="flex min-w-0 flex-col" data-ytd-side={side.flow}>
      <h3 className="font-sans text-[0.95rem] font-semibold text-charcoal">{title}</h3>
      <ul className="mt-1.5">
        {side.rows.map((r) => {
          const byValue = r.net_weight_kg === null && r.usd_value !== null
          const vs = r.comparable ? t('overview.trade.ytd.vs', { p: prevSpan(r, lang) }) : t('overview.trade.ytd.noCompare')
          return (
            <li key={r.iso3} className="grid grid-cols-[minmax(0,1fr)_auto_4.6rem] items-center gap-x-2 border-b border-line-soft py-[0.4rem] last:border-0">
              <div className="min-w-0">
                <Link to={r.link ?? `/paesi/${r.iso3}`} className="block break-words text-[0.93rem] leading-snug text-charcoal hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2">
                  {r.name ?? r.iso3}
                </Link>
                <div className="flex flex-wrap items-center gap-x-1.5 text-[0.74rem] leading-snug text-muted">
                  <span className="num">{fmtMonthSpan(r.month_from, r.month_to, lang)} {r.year}</span>
                  <span>· {shortSourceName(r.source, lang)}</span>
                  {r.is_demo ? <DemoBadge /> : r.data_status && !['published', 'live'].includes(r.data_status) && <StatusBadge status={r.data_status} />}
                </div>
              </div>
              <span className="num text-right text-[0.9rem] text-charcoal">{byValue ? fmtUsd(r.usd_value, lang) : fmtTonnes(r.net_weight_kg, lang)}</span>
              <span className="text-right text-[0.82rem]">
                {r.comparable ? <Delta value={byValue ? r.change_value_pct : r.change_volume_pct} title={vs} />
                  : <span className="text-[0.74rem] text-muted" title={vs}>{t('overview.trade.ytd.noCompareShort')}</span>}
              </span>
            </li>
          )
        })}
      </ul>
      {side.count > side.rows.length && <p className="mt-1 text-[0.74rem] text-muted">{t('overview.trade.ytd.more', { n: side.count - side.rows.length })}</p>}
    </div>
  )
}

function Side({ side, title, fallbackEmpty }: { side: TradeSide | null; title: string; fallbackEmpty: string }) {
  const { t, lang } = useI18n()
  if (!side) {
    return (
      <div className="min-w-0">
        <h3 className="font-sans text-[0.95rem] font-semibold text-charcoal">{title}</h3>
        <p className="mt-2 text-[0.88rem] text-muted">{fallbackEmpty}</p>
      </div>
    )
  }
  const max = Math.max(...side.items.map((i) => i.net_weight_kg ?? 0), 1)
  const basis = t(`overview.trade.basis.${side.basis}`, { n: side.reporters_count ?? '' })
  const prev = side.prev_period_label ? fmtPeriod(side.prev_period_label, lang) : null
  return (
    <div className="flex min-w-0 flex-col">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-sans text-[0.95rem] font-semibold text-charcoal">{title}</h3>
        <span className="num whitespace-nowrap text-[0.78rem] text-muted">{fmtPeriod(side.period_label, lang)}{prev ? ` · ${t('overview.trade.yoy', { p: prev })}` : ''}</span>
      </div>
      <ol className="mt-2">
        {side.items.map((row, i) => (
          <li key={row.iso3} className="grid grid-cols-[1.1rem_minmax(0,1fr)_auto_4.6rem] items-center gap-x-2 border-b border-line-soft py-[0.45rem] last:border-0">
            <span className="num text-[0.78rem] text-muted">{i + 1}</span>
            <div className="min-w-0">
              <Link to={row.link} className="block break-words text-[0.93rem] leading-snug text-charcoal hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2">
                {row.name}
              </Link>
              <div className="mt-1 h-[3px] rounded-full bg-forest-50">
                <div className="h-[3px] rounded-full bg-gold-light" style={{ width: `${Math.max(2, ((row.net_weight_kg ?? 0) / max) * 100)}%` }} />
              </div>
            </div>
            <span className="num text-right text-[0.9rem] text-charcoal" title={row.unit_value_usd_per_kg ? t('overview.trade.unitValue', { v: fmtNumber(row.unit_value_usd_per_kg, lang, 2) }) : undefined}>
              {fmtTonnes(row.net_weight_kg, lang)}
            </span>
            <span className="text-right text-[0.82rem]">
              <Delta value={row.yoy_pct} title={prev ? t('overview.trade.yoy', { p: prev }) : undefined} />
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-2 text-[0.78rem] leading-snug text-muted">
        {basis}
        {side.partial_latest && <> {t('overview.trade.partial')}</>}
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.78rem] text-muted">
        {side.is_demo ? <DemoBadge /> : side.data_status && !['published', 'live'].includes(side.data_status) && <StatusBadge status={side.data_status} />}
        <span>{t('prov.source')}: <span className="font-medium text-charcoal-soft">{side.source?.publisher || side.source?.name}</span></span>
        {side.published_at && <span>· {t('prov.published')} {fmtDate(side.published_at, lang)}</span>}
        <FreshnessBadge status={side.freshness.status} ageDays={side.freshness.age_days} />
        {side.source_url && (
          <a href={pageUrl(side.source_url) ?? undefined} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5"
            title={isMappedUrl(side.source_url) ? t('prov.exactAddress', { url: side.source_url }) : undefined}>
            {t(isMappedUrl(side.source_url) ? 'prov.officialPage' : 'prov.original')} <ExternalLink size={12} />
          </a>
        )}
      </div>
    </div>
  )
}

export function TradeHighlights({ block }: { block: TradeBlock }) {
  const { t, lang } = useI18n()
  const exp = block.exporters
  const ytd = block.ytd ?? null
  const ytdYear = ytd?.importers?.year ?? ytd?.exporters?.year
  const anyDemo = !!(block.importers?.is_demo || exp?.is_demo || ytd?.importers?.is_demo || ytd?.exporters?.is_demo)
  const annual = block.importers?.period_label ?? exp?.period_label
  return (
    <section className="panel">
      <BlockHead
        eyebrow={t('overview.trade.eyebrow')}
        title={t('overview.trade.title')}
        sub={block.available ? 'HS 0409 · t' : undefined}
        right={<>{anyDemo && <DemoBadge />}<SectionLink to={block.link} label={t('overview.trade.goto')} /></>}
      />
      <div className="px-5 py-4">
        {block.available && ytd && ytdYear !== undefined && (
          // the freshest period first: monthly customs data of the running year
          <div className="mb-5 border-b border-line-soft pb-4" data-ytd="overview">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <h3 className="font-serif text-[1.05rem] font-semibold text-forest-900">{t('overview.trade.ytd.title', { y: ytdYear })}</h3>
              <span className="text-[0.78rem] text-muted">{t('overview.trade.ytd.sub', { py: ytdYear - 1 })}</span>
            </div>
            <div className="mt-2 grid grid-cols-1 gap-x-8 gap-y-5 md:grid-cols-2">
              <YtdSide side={ytd.importers} title={t('overview.trade.importers')} />
              <YtdSide side={ytd.exporters} title={t('overview.trade.exporters')} />
            </div>
            <p className="mt-2 text-[0.76rem] leading-snug text-muted">{t('overview.trade.ytd.note')}</p>
          </div>
        )}
        {block.available && ytd && (block.importers || exp) && (
          <h3 className="mb-2 font-serif text-[1.05rem] font-semibold text-forest-900">
            {t('overview.trade.annualTitle', { p: annual ? fmtPeriod(annual, lang) : '' })}
          </h3>
        )}
        {!block.available ? (
          <BlockEmpty what={t('overview.trade.emptyWhat')} providers={block.providers} fallbackSources={t('overview.trade.fallbackSources')} />
        ) : (block.importers || exp) && (
          <div className="grid grid-cols-1 gap-x-8 gap-y-6 md:grid-cols-2">
            <Side side={block.importers} title={t('overview.trade.importers')} fallbackEmpty={t('overview.noData')} />
            <Side side={exp} title={exp?.basis === 'mirror_imports' ? t('overview.trade.origins') : t('overview.trade.exporters')}
              fallbackEmpty={t('overview.trade.noExporters')} />
          </div>
        )}
      </div>
      <div className="border-t border-line-soft px-5 py-2.5">
        <BlockStamp updatedAt={block.updated_at} publishedAt={block.latest_published_at} />
      </div>
    </section>
  )
}
