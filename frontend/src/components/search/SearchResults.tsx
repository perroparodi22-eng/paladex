// Grouped search results. Every result is a focusable link marked with [data-result] so the page
// can move between them with the arrow keys.
import clsx from 'clsx'
import { ArrowRight, ExternalLink, FileDown, Globe2, LineChart } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AiBadge, Badge, DemoBadge, FreshnessBadge, Panel, ReliabilityBadge } from '@/components/ui'
import { pickLang, useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtPeriod } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import type {
  CountryHit, GroupKey, NewsHit, PriceHit, RegulationHit, ReportHit, SearchGroup, SourceHit, VarietyHit,
} from './types'

const RESULT = 'data-result'
const resultProps = { [RESULT]: '' }

export function groupTitleKey(key: GroupKey) {
  return `search.group.${key}`
}

export function ResultGroup({ group, query }: { group: SearchGroup; query: string }) {
  const { t, lang } = useI18n()
  const more = group.total - group.items.length
  const seeAllLabel = group.key === 'news' ? t('search.seeAll.news', { q: query })
    : group.key === 'prices' ? t('search.seeAll.prices')
    : group.key === 'regulations' ? t('search.seeAll.regulations', { q: query })
    : group.key === 'sources' ? t('search.seeAll.sources') : null
  return (
    <Panel
      className="scroll-mt-24"
      title={
        <span id={`grp-${group.key}`} className="flex items-baseline gap-2">
          {t(groupTitleKey(group.key))}
          <span className="num text-[0.9rem] font-normal text-muted">{fmtNumber(group.total, lang)}</span>
        </span>
      }
      actions={group.see_all && seeAllLabel ? (
        <Link to={group.see_all} className="link text-[0.92rem] inline-flex items-center gap-1">{seeAllLabel} <ArrowRight size={14} /></Link>
      ) : undefined}
      bodyClassName={group.key === 'countries' || group.key === 'varieties' ? 'p-5' : 'p-0'}
      footer={more > 0 ? t('search.group.more', { n: fmtNumber(more, lang) }) : undefined}
    >
      {group.key === 'countries' && <CardGrid>{(group.items as CountryHit[]).map((c) => <CountryCard key={c.iso3} c={c} />)}</CardGrid>}
      {group.key === 'varieties' && <CardGrid>{(group.items as VarietyHit[]).map((v) => <VarietyCard key={v.key} v={v} />)}</CardGrid>}
      {group.key === 'prices' && <Rows>{(group.items as PriceHit[]).map((p) => <PriceRow key={`${p.origin_iso3}-${p.variety}`} p={p} />)}</Rows>}
      {group.key === 'news' && <Rows>{(group.items as NewsHit[]).map((n) => <NewsRow key={n.id} n={n} />)}</Rows>}
      {group.key === 'reports' && <Rows>{(group.items as ReportHit[]).map((r) => <ReportRow key={r.id} r={r} />)}</Rows>}
      {group.key === 'regulations' && <Rows>{(group.items as RegulationHit[]).map((r) => <RegulationRow key={r.id} r={r} />)}</Rows>}
      {group.key === 'sources' && <Rows>{(group.items as SourceHit[]).map((s) => <SourceRow key={s.key} s={s} />)}</Rows>}
    </Panel>
  )
}

function CardGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">{children}</div>
}

function Rows({ children }: { children: ReactNode }) {
  return <ul className="divide-y divide-line-soft">{children}</ul>
}

const cardCls = 'group flex items-center justify-between gap-3 rounded-sm border border-line bg-white px-4 py-3.5 hover:border-forest-600 hover:bg-forest-50/40 focus-visible:border-forest-600'

function CountryCard({ c }: { c: CountryHit }) {
  const { t, lang } = useI18n()
  const [main, other] = lang === 'it' ? [c.name_it, c.name_en] : [c.name_en, c.name_it]
  return (
    <Link to={c.target} className={cardCls} {...resultProps}>
      <div className="flex items-center gap-3 min-w-0">
        <Globe2 size={22} className="text-forest-600 shrink-0" />
        <div className="min-w-0">
          <div className="font-serif text-[1.15rem] font-semibold text-charcoal leading-tight">{main}</div>
          <div className="text-[0.85rem] text-muted truncate">{[other !== main ? other : null, c.region].filter(Boolean).join(' · ')}</div>
          <div className="mt-1.5">
            {c.has_prices ? <Badge tone="forest">{t('search.country.hasPrices')}</Badge> : <Badge tone="outline">{t('search.country.noPrices')}</Badge>}
          </div>
        </div>
      </div>
      <span className="flex items-center gap-1 text-[0.85rem] text-forest-700 shrink-0">{t('search.country.open')} <ArrowRight size={15} className="group-hover:translate-x-0.5 transition-transform" /></span>
    </Link>
  )
}

function VarietyCard({ v }: { v: VarietyHit }) {
  const { t, lang } = useI18n()
  const [main, other] = lang === 'it' ? [v.it, v.en] : [v.en, v.it]
  return (
    <Link to={v.target} className={cardCls} {...resultProps}>
      <div className="min-w-0">
        <div className="font-serif text-[1.15rem] font-semibold text-charcoal leading-tight">{main}</div>
        <div className="text-[0.85rem] text-muted truncate">{other}</div>
        <div className="mt-1.5">
          {v.has_prices ? <Badge tone="forest">{t('search.country.hasPrices')}</Badge> : <Badge tone="outline">{t('search.country.noPrices')}</Badge>}
        </div>
      </div>
      <span className="flex items-center gap-1 text-[0.85rem] text-forest-700 shrink-0">{t('search.variety.open')} <ArrowRight size={15} /></span>
    </Link>
  )
}

const rowLinkCls = 'block px-5 py-4 hover:bg-ivory/50 focus-visible:bg-ivory/60 outline-offset-[-2px]'

function PriceRow({ p }: { p: PriceHit }) {
  const { t, lang } = useI18n()
  const { priceType } = useLabels()
  const origin = (lang === 'it' ? p.origin_name_it : p.origin_name_en) ?? '—'
  const variety = lang === 'it' ? p.variety_it : p.variety_en
  return (
    <li>
      <Link to={p.target} className={clsx(rowLinkCls, 'flex items-center justify-between gap-4')} {...resultProps}>
        <div className="flex items-start gap-3 min-w-0">
          <LineChart size={20} className="text-gold mt-0.5 shrink-0" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-[1.05rem] text-charcoal">{origin} · {variety}</span>
              {p.is_demo && <DemoBadge />}
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {p.price_types.map((pt) => <Badge key={pt} tone="neutral">{priceType(pt)}</Badge>)}
            </div>
            <div className="mt-1.5 text-[0.88rem] text-muted num">
              {t('search.prices.latest')}: <span className="text-charcoal-soft">{fmtPeriod(p.latest_period_label, lang)}</span>
              {' · '}{t('search.prices.observations', { n: fmtNumber(p.observations, lang) })}
              {' · '}{p.sources === 1 ? t('search.prices.sourcesOne') : t('search.prices.sources', { n: p.sources })}
            </div>
          </div>
        </div>
        <span className="flex items-center gap-1 text-[0.88rem] text-forest-700 shrink-0">{t('search.prices.open')} <ArrowRight size={15} /></span>
      </Link>
    </li>
  )
}

function NewsRow({ n }: { n: NewsHit }) {
  const { t, lang } = useI18n()
  const translated = lang === 'it' ? n.title_it : n.title_en
  const summary = lang === 'it' ? n.summary_it ?? n.summary_en : n.summary_en ?? n.summary_it
  return (
    <li className="px-5 py-4">
      <a href={n.url} target="_blank" rel="noreferrer" className="group inline-flex items-start gap-1.5 text-[1.05rem] font-semibold text-charcoal hover:text-forest-700 leading-snug" {...resultProps}>
        <span className="group-hover:underline decoration-gold/60 underline-offset-2">{n.title}</span>
        <ExternalLink size={14} className="mt-1 shrink-0 text-muted" />
      </a>
      {translated && translated !== n.title && (
        <div className="mt-0.5 flex items-start gap-2 text-[0.95rem] text-charcoal-soft"><AiBadge /> <span>{translated}</span></div>
      )}
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.85rem] text-muted">
        {n.is_demo && <DemoBadge />}
        {n.publisher && <span className="text-charcoal-soft">{n.publisher}</span>}
        {n.published_at && <span>· {fmtDate(n.published_at, lang)}</span>}
        {n.source && <span>· {t('prov.source')}: {n.source.name}</span>}
      </div>
      {n.snippet ? (
        <p className="mt-1.5 text-[0.95rem] text-charcoal-soft leading-relaxed">{n.snippet}</p>
      ) : summary ? (
        <p className="mt-1.5 text-[0.95rem] text-charcoal-soft leading-relaxed"><AiBadge label={t('search.news.summaryAi')} /> {summary}</p>
      ) : null}
    </li>
  )
}

function ReportRow({ r }: { r: ReportHit }) {
  const { t, lang } = useI18n()
  const summary = pickLang(r as unknown as Record<string, unknown>, 'summary', lang)
  return (
    <li className="px-5 py-4">
      <a href={r.url} target="_blank" rel="noreferrer" className="group inline-flex items-start gap-1.5 text-[1.05rem] font-semibold text-charcoal hover:text-forest-700 leading-snug" {...resultProps}>
        <span className="group-hover:underline decoration-gold/60 underline-offset-2">{r.title}</span>
        <ExternalLink size={14} className="mt-1 shrink-0 text-muted" />
      </a>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.85rem] text-muted">
        {r.is_demo && <DemoBadge />}
        {r.source && <span className="text-charcoal-soft">{r.source.publisher || r.source.name}</span>}
        {r.source && <ReliabilityBadge reliability={r.source.reliability} />}
        {r.published_at && <span>· {t('prov.published')} {fmtDate(r.published_at, lang)}</span>}
        {r.period_label && <span>· {t('search.report.period')}: {fmtPeriod(r.period_label, lang)}</span>}
      </div>
      {summary && (
        <p className="mt-1.5 text-[0.95rem] text-charcoal-soft leading-relaxed">
          {r.summary_is_ai && <><AiBadge /> </>}{summary}
        </p>
      )}
      {r.excerpt && <p className="mt-1.5 text-[0.92rem] text-muted leading-relaxed italic">“{r.excerpt}”</p>}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.88rem]">
        <a href={r.url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1">{t('search.report.original')} <ExternalLink size={13} /></a>
        {r.file_url && (
          <a href={r.file_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1">{t('search.report.archived')} <FileDown size={13} /></a>
        )}
      </div>
    </li>
  )
}

function RegulationRow({ r }: { r: RegulationHit }) {
  const { t, lang } = useI18n()
  const summary = pickLang(r as unknown as Record<string, unknown>, 'summary', lang)
  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-center gap-2 text-[0.85rem] text-muted">
        {r.is_demo && <DemoBadge />}
        <Badge tone="forest">{r.jurisdiction}</Badge>
        <span className="num text-charcoal-soft">{r.reference}</span>
        {r.published_at && <span>· {fmtDate(r.published_at, lang)}</span>}
        {r.effective_date && <span>· {t('search.reg.effective')} {fmtDate(r.effective_date, lang)}</span>}
      </div>
      <a href={r.url} target="_blank" rel="noreferrer" className="group mt-1 inline-flex items-start gap-1.5 text-[1.05rem] font-semibold text-charcoal hover:text-forest-700 leading-snug" {...resultProps}>
        <span className="group-hover:underline decoration-gold/60 underline-offset-2">{r.title}</span>
        <ExternalLink size={14} className="mt-1 shrink-0 text-muted" />
      </a>
      {summary && (
        <p className="mt-1.5 text-[0.95rem] text-charcoal-soft leading-relaxed">{r.summary_is_ai && <><AiBadge /> </>}{summary}</p>
      )}
    </li>
  )
}

function SourceRow({ s }: { s: SourceHit }) {
  const { t, lang } = useI18n()
  return (
    <li>
      <Link to={s.target} className={clsx(rowLinkCls, 'flex items-center justify-between gap-4')} {...resultProps}>
        <div className="min-w-0">
          <div className="font-semibold text-[1.02rem] text-charcoal">{s.name}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[0.85rem] text-muted">
            {s.publisher && <span>{s.publisher}</span>}
            <ReliabilityBadge reliability={s.reliability} />
            <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />
            {s.latest_published_at && <span>· {t('prov.published')} {fmtDate(s.latest_published_at, lang)}</span>}
          </div>
        </div>
        <span className="flex items-center gap-1 text-[0.88rem] text-forest-700 shrink-0">{t('search.source.open')} <ArrowRight size={15} /></span>
      </Link>
    </li>
  )
}
