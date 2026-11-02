import { ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DemoBadge, FreshnessBadge, StatusBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtPeriod, fmtTonnes } from '@/lib/format'
import { BlockEmpty, BlockHead, BlockStamp, Delta, SectionLink } from './parts'
import type { TradeBlock, TradeSide } from './types'

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
              <Link to={row.link} className="block truncate text-[0.93rem] text-charcoal hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2">
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
          <a href={side.source_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">
            {t('prov.original')} <ExternalLink size={12} />
          </a>
        )}
      </div>
    </div>
  )
}

export function TradeHighlights({ block }: { block: TradeBlock }) {
  const { t } = useI18n()
  const exp = block.exporters
  const anyDemo = !!(block.importers?.is_demo || exp?.is_demo)
  return (
    <section className="panel">
      <BlockHead
        eyebrow={t('overview.trade.eyebrow')}
        title={t('overview.trade.title')}
        sub={block.available ? 'HS 0409 · t' : undefined}
        right={<>{anyDemo && <DemoBadge />}<SectionLink to={block.link} label={t('overview.trade.goto')} /></>}
      />
      <div className="px-5 py-4">
        {!block.available ? (
          <BlockEmpty what={t('overview.trade.emptyWhat')} providers={block.providers} fallbackSources={t('overview.trade.fallbackSources')} />
        ) : (
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
