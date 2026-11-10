// Right-hand column of the overview: alerts, relevant news, new official reports, country activity.
import clsx from 'clsx'
import { AlertOctagon, AlertTriangle, Bell, ExternalLink, Info, Newspaper } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AiBadge, Badge, DemoBadge, FreshnessBadge, TranslatedBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtAgo, fmtDate, fmtPeriod } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { BlockEmpty, BlockHead, BlockStamp, SectionLink } from './parts'
import type { AlertsBlock, CountriesBlock, NewsBlock, NewsItem, ReportsBlock } from './types'
import { pageUrl } from '@/lib/links'

// ---------------------------------------------------------------- alerts

export function AlertsPanel({ block }: { block: AlertsBlock }) {
  const { t, lang } = useI18n()
  const icon = (sev: string) =>
    sev === 'critical' ? <AlertOctagon size={16} className="text-down" />
      : sev === 'warning' ? <AlertTriangle size={16} className="text-warn" />
        : <Info size={16} className="text-forest-600" />
  return (
    <section className="panel">
      <BlockHead
        eyebrow={t('nav.alerts')}
        title={<span className="inline-flex items-center gap-2">{t('overview.alerts.title')}
          {block.unread > 0 && <Badge tone="gold">{t('overview.alerts.unread', { n: block.unread })}</Badge>}</span>}
        right={<SectionLink to={block.link} label={t('overview.alerts.manage')} />}
      />
      {block.items.length === 0 ? (
        <div className="flex items-center gap-2.5 px-5 py-3.5 text-[0.92rem] text-muted">
          <Bell size={16} className="text-gold" /> {t('overview.alerts.none')}
        </div>
      ) : (
        <ul className="divide-y divide-line-soft">
          {block.items.map((a) => {
            const body = (
              <div className="flex items-start gap-2.5 px-5 py-2.5">
                <span className="mt-0.5 shrink-0">{icon(a.severity)}</span>
                <div className="min-w-0">
                  <div className="text-[0.93rem] leading-snug text-charcoal">{a.title}</div>
                  {a.body && <div className="mt-0.5 line-clamp-2 text-[0.8rem] text-muted">{a.body}</div>}
                  <div className="mt-0.5 text-[0.75rem] text-muted">{fmtAgo(a.triggered_at, lang)}</div>
                </div>
              </div>
            )
            const external = a.link && /^https?:/.test(a.link)
            return (
              <li key={a.id} className="hover:bg-paper">
                {a.link ? (external
                  ? <a href={pageUrl(a.link) ?? undefined} target="_blank" rel="noreferrer">{body}</a>
                  : <Link to={a.link}>{body}</Link>) : body}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

// ---------------------------------------------------------------- news

function Thumb({ src }: { src: string | null }) {
  const [broken, setBroken] = useState(false)
  if (!src || broken) {
    return (
      <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-sm border border-line-soft bg-paper text-line">
        <Newspaper size={18} />
      </div>
    )
  }
  return (
    <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)}
      className="h-14 w-14 shrink-0 rounded-sm border border-line-soft object-cover" />
  )
}

function NewsRow({ n }: { n: NewsItem }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  return (
    <li>
      <a href={pageUrl(n.url) ?? undefined} target="_blank" rel="noreferrer" className="flex gap-3 px-5 py-2.5 hover:bg-paper"
        title={n.title_is_ai ? `${t('overview.news.translated')}: ${n.original_title}` : n.original_title}>
        <Thumb src={n.image_url} />
        <div className="min-w-0 flex-1">
          <div className="line-clamp-2 text-[0.93rem] font-medium leading-snug text-charcoal">{n.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[0.76rem] text-muted">
            <span className="font-medium text-charcoal-soft">{n.publisher || n.source?.name}</span>
            <span>· {fmtDate(n.published_at || n.collected_at, lang, { day: '2-digit', month: 'short' })}</span>
            {n.countries.slice(0, 3).map((c) => <span key={c} className="rounded-sm bg-forest-50 px-1 text-[0.7rem] text-forest-800">{country(c)}</span>)}
            {n.summary_is_ai ? <AiBadge /> : n.title_is_ai && <TranslatedBadge model={n.ai_model} />}
            {n.is_demo && <DemoBadge />}
            <ExternalLink size={11} className="opacity-60" />
          </div>
        </div>
      </a>
    </li>
  )
}

export function NewsPanel({ block }: { block: NewsBlock }) {
  const { t } = useI18n()
  return (
    <section className="panel">
      <BlockHead
        eyebrow={t('overview.news.eyebrow')}
        title={t('overview.news.title')}
        sub={block.items.length ? t('overview.news.subtitle', { d: block.window_days, n: block.min_relevance }) : undefined}
        right={<SectionLink to={block.link} label={t('overview.news.all')} />}
      />
      {block.items.length === 0 ? (
        <div className="px-5 py-3.5">
          <BlockEmpty compact what={t('overview.news.emptyWhat')} providers={block.providers} fallbackSources={t('overview.news.fallbackSources')}
            extra={block.collected_last_7_days > 0 ? <span className="text-[0.85rem] text-charcoal-soft">{t('overview.news.someCollected', { n: block.collected_last_7_days })}</span> : undefined} />
        </div>
      ) : (
        <ul className="divide-y divide-line-soft py-1">{block.items.map((n) => <NewsRow key={n.id} n={n} />)}</ul>
      )}
      <div className="border-t border-line-soft px-5 py-2">
        <BlockStamp updatedAt={block.updated_at} />
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- reports

export function ReportsPanel({ block }: { block: ReportsBlock }) {
  const { t, lang } = useI18n()
  return (
    <section className="panel">
      <BlockHead
        eyebrow={t('overview.reports.eyebrow')}
        title={t('overview.reports.title')}
        right={block.new_count > 0 ? <Badge tone="gold">{block.new_count} {t('overview.reports.new')}</Badge> : undefined}
      />
      {block.items.length === 0 ? (
        <div className="px-5 py-3.5">
          <BlockEmpty compact what={t('overview.reports.emptyWhat')} providers={block.providers} fallbackSources={t('overview.reports.fallbackSources')} />
        </div>
      ) : (
        <ul className="divide-y divide-line-soft py-1">
          {block.items.map((r) => (
            <li key={r.id}>
              <a href={pageUrl(r.url) ?? undefined} target="_blank" rel="noreferrer" className="block px-5 py-2.5 hover:bg-paper">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[0.93rem] leading-snug text-charcoal">{r.title}</span>
                  {r.is_new && <Badge tone="gold" className="mt-0.5">{t('overview.reports.new')}</Badge>}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[0.76rem] text-muted">
                  <span className="font-medium text-charcoal-soft">{r.source?.publisher || r.source?.name}</span>
                  {r.published_at && <span>· {t('prov.published')} {fmtDate(r.published_at, lang)}</span>}
                  {r.period_label && <span>· {t('overview.reports.period', { p: fmtPeriod(r.period_label, lang) })}</span>}
                  {r.summary_is_ai && <AiBadge />}
                  {r.is_demo && <DemoBadge />}
                  <ExternalLink size={11} className="opacity-60" />
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line-soft px-5 py-2">
        <BlockStamp updatedAt={block.updated_at} publishedAt={block.latest_published_at} />
        {block.sources.filter((s) => s.freshness.status !== 'unknown' && s.freshness.status !== 'never').slice(0, 1)
          .map((s) => <FreshnessBadge key={s.key} status={s.freshness.status} ageDays={s.freshness.age_days} />)}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- countries

export function CountryActivityPanel({ block }: { block: CountriesBlock }) {
  const { t } = useI18n()
  const max = Math.max(...block.items.map((c) => c.score), 1)
  return (
    <section className="panel">
      <BlockHead
        eyebrow={t('overview.countries.eyebrow')}
        title={t('overview.countries.title')}
        sub={block.items.length ? <>{block.items.some((c) => c.reasons.some((r) => r.is_demo)) && <span className="mr-1.5"><DemoBadge /></span>}{t('overview.countries.subtitle')}</> : undefined}
        right={<SectionLink to={block.link} label={t('overview.countries.all')} />}
      />
      {block.items.length === 0 ? (
        <div className="px-5 py-3.5">
          {/* Derived from the other blocks, so name them rather than every underlying feed. */}
          <BlockEmpty compact what={t('overview.countries.emptyWhat')} providers={[]} fallbackSources={t('overview.countries.fallbackSources')} />
        </div>
      ) : (
        <ol className="divide-y divide-line-soft py-1">
          {block.items.map((c, i) => (
            <li key={c.iso3}>
              <Link to={c.link} className="group grid grid-cols-[1.2rem_minmax(0,1fr)_auto] items-start gap-x-2.5 px-5 py-2.5 hover:bg-paper">
                <span className="num pt-[0.1rem] text-[0.78rem] text-muted">{i + 1}</span>
                <div className="min-w-0">
                  <span className="font-serif text-[1.02rem] font-semibold text-charcoal group-hover:text-forest-800">{c.name}</span>
                  <ul className="mt-0.5 space-y-0.5">
                    {c.reasons.map((r) => (
                      <li key={r.kind} className="flex items-baseline gap-1.5 text-[0.8rem] leading-snug text-muted">
                        <span aria-hidden className={clsx('text-[0.6rem]', r.kind === 'price' && r.change_pct !== undefined
                          ? (r.change_pct > 0 ? 'text-up' : r.change_pct < 0 ? 'text-down' : 'text-muted') : 'text-gold')}>
                          {r.kind === 'price' && r.change_pct !== undefined ? (r.change_pct > 0 ? '▲' : r.change_pct < 0 ? '▼' : '■') : '●'}
                        </span>
                        <span>{r.text}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="flex flex-col items-end gap-1 pt-1" title={t('overview.countries.scoreHelp')}>
                  <span className="num text-[0.78rem] text-charcoal-soft">{c.score}</span>
                  <span className="block h-[3px] w-12 rounded-full bg-forest-50">
                    <span className="block h-[3px] rounded-full bg-gold-light" style={{ width: `${(c.score / max) * 100}%` }} />
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ol>
      )}
      <div className="border-t border-line-soft px-5 py-2">
        <BlockStamp updatedAt={block.items.length ? block.updated_at : null}>
          {block.items.length > 0 && <span title={t('overview.countries.scoreHelp')} className="cursor-help underline decoration-dotted underline-offset-2">{t('overview.countries.scoreLabel')}</span>}
        </BlockStamp>
      </div>
    </section>
  )
}
