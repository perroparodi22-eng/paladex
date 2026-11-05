import { ExternalLink, FileText, Newspaper, Ship, TrendingDown, TrendingUp, Type } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AiBadge, Badge, DemoBadge, StatusBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtPeriod } from '@/lib/format'
import { BlockHead, fmtClock } from './parts'
import type { BriefingBlock, BriefingBullet } from './types'
import { pageUrl } from '@/lib/links'

const DAY: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'long', year: 'numeric' }

function KindIcon({ b }: { b: BriefingBullet }) {
  const cls = 'shrink-0 text-gold-dark'
  if (b.kind === 'price') return (b.change_pct ?? 0) >= 0 ? <TrendingUp size={14} className={cls} /> : <TrendingDown size={14} className={cls} />
  if (b.kind === 'report') return <FileText size={14} className={cls} />
  if (b.kind === 'trade') return <Ship size={14} className={cls} />
  if (b.kind === 'news') return <Newspaper size={14} className={cls} />
  return <Type size={14} className={cls} />
}

function Bullet({ b, n }: { b: BriefingBullet; n: number }) {
  const { t, lang } = useI18n()
  const publisher = b.publisher || b.source?.publisher || b.source?.name
  return (
    <li className="grid grid-cols-[2.4rem_1fr] gap-x-3 border-b border-line-soft py-3.5 first:pt-1 last:border-0 last:pb-1">
      <span className="num pt-[0.1rem] text-[1.15rem] font-medium leading-none text-gold">{String(n).padStart(2, '0')}</span>
      <div className="min-w-0">
        <p className="text-[1.02rem] leading-snug text-charcoal">{b.text}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8rem] text-muted">
          <KindIcon b={b} />
          <span className="inline-flex items-center rounded-sm border border-line bg-paper px-1.5 py-[1px] text-[0.76rem] font-medium text-charcoal-soft">
            {publisher || t('overview.briefing.noSource')}
          </span>
          {b.date && <span>{t('prov.published')} {fmtDate(b.date, lang)}</span>}
          {b.period_label && b.kind !== 'news' && <span>· {t('overview.briefing.period', { p: fmtPeriod(b.period_label, lang) })}</span>}
          {b.is_demo && <DemoBadge />}
          {!b.is_demo && b.data_status && !['published', 'live'].includes(b.data_status) && <StatusBadge status={b.data_status} />}
          {b.is_ai && <AiBadge />}
          {b.url && (
            <a href={pageUrl(b.url) ?? undefined} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">
              {t('prov.original')} <ExternalLink size={12} />
            </a>
          )}
          {b.link && (
            <Link to={b.link} className="text-forest-700 hover:text-forest-900">
              {t('overview.openSection')} →
            </Link>
          )}
        </div>
      </div>
    </li>
  )
}

export function BriefingPanel({ b }: { b: BriefingBlock }) {
  const { t, lang } = useI18n()
  const count = (n?: number) => (n === undefined ? '' : n === 0 ? t('overview.briefing.found0') : n === 1 ? t('overview.briefing.found1') : t('overview.briefing.found', { n }))
  const generated = b.is_ai
    ? t('overview.briefing.generatedAi', { date: fmtDate(b.generated_at, lang, DAY), time: fmtClock(b.generated_at, lang), model: b.generator })
    : t('overview.briefing.generatedRules', { date: fmtDate(b.generated_at, lang, DAY), time: fmtClock(b.generated_at, lang) })

  return (
    <section className="panel">
      <BlockHead
        eyebrow={t('overview.briefing.eyebrow')}
        title={t('overview.briefing.title')}
        right={b.is_ai
          ? <AiBadge label={t('overview.briefing.ai', { model: b.generator })} />
          : <Badge tone="forest" title={t('overview.briefing.rulesTitle')}>{t('overview.briefing.rules')}</Badge>}
      />
      <div className="px-5 py-4">
        {b.bullets.length > 0 ? (
          <ol>{b.bullets.map((x, i) => <Bullet key={i} b={x} n={i + 1} />)}</ol>
        ) : (
          <p className="font-serif text-[1.08rem] leading-snug text-charcoal-soft">{b.empty_message}</p>
        )}
      </div>
      <div className="border-t border-line-soft bg-paper/60 px-5 py-2.5 text-[0.8rem] text-muted">
        <div>{generated}</div>
        {b.rules.length > 0 && (
          <div className="mt-1.5">
            <div className="font-medium text-charcoal-soft">{t('overview.briefing.checked')}</div>
            <ul className="mt-0.5 grid grid-cols-1 gap-x-6 gap-y-0.5 md:grid-cols-2">
              {b.rules.map((r) => (
                <li key={r.key} className="flex items-baseline justify-between gap-3 border-b border-dotted border-line py-0.5">
                  <span>{r.text}</span>
                  <span className="shrink-0 text-charcoal-soft">{count(r.count)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
