// Harvest / production reports (official and industry bulletins) and news tagged production or weather.
import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DataMissing } from '@/components/trade/bits'
import { AiBadge, Badge, DemoBadge, ErrorBlock, Loading, Panel, ReliabilityBadge } from '@/components/ui'
import { pickLang, useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate, fmtPeriod } from '@/lib/format'
import type { HarvestNews, HarvestReport, ReportsResponse } from './types'
import { pageUrl } from '@/lib/links'

export function ReportsPanel() {
  const { t } = useI18n()
  const q = useQuery({ queryKey: ['harvest', 'reports'], queryFn: () => api.get<ReportsResponse>('/harvest/reports') })
  return (
    <Panel title={t('harvest.reports.title')} eyebrow={t('harvest.reports.eyebrow')} className="min-w-0">
      {q.isLoading ? <Loading /> : q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} /> : q.data ? (
        <ReportsBody data={q.data} />
      ) : null}
    </Panel>
  )
}

export function ReportsBody({ data }: { data: ReportsResponse }) {
  const { t } = useI18n()
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="min-w-0">
        <h3 className="mb-2 text-[1.02rem] font-semibold">{t('harvest.reports.reports')}</h3>
        {data.reports.length ? (
          <ul className="flex flex-col divide-y divide-line-soft">{data.reports.map((r) => <ReportItem key={r.id} r={r} />)}</ul>
        ) : (
          <DataMissing compact providers={data.report_providers} fallback={t('harvest.reports.fallback')} what={t('harvest.reports.noReports')} />
        )}
      </section>
      <section className="min-w-0">
        <h3 className="mb-2 text-[1.02rem] font-semibold">{t('harvest.reports.news')}</h3>
        {data.news.length ? (
          <ul className="flex flex-col divide-y divide-line-soft">{data.news.map((n) => <NewsItem key={n.id} n={n} />)}</ul>
        ) : (
          <DataMissing compact providers={data.news_providers} fallback={t('harvest.reports.newsFallback')} what={t('harvest.reports.noNews')} />
        )}
        <Link to={data.news_link} className="link mt-2 inline-block text-[0.9rem]">{t('harvest.reports.allNews')} →</Link>
      </section>
    </div>
  )
}

/** Text extracted from a PDF table ("MS 2 S o E S P L R O E L IT F R ...") is not shown as an excerpt. */
export function readable(text: string): boolean {
  const words = text.slice(0, 300).split(/\s+/).filter(Boolean)
  if (words.length < 8) return true
  const single = words.filter((w) => w.length === 1).length
  return single / words.length < 0.25
}

function ReportItem({ r }: { r: HarvestReport }) {
  const { t, lang } = useI18n()
  const summary = lang === 'it' ? r.summary_it ?? r.summary_en : r.summary_en ?? r.summary_it
  return (
    <li className="py-2.5 first:pt-0">
      <a href={pageUrl(r.source_url) ?? undefined} target="_blank" rel="noreferrer" className="link inline-flex items-start gap-1 font-medium [overflow-wrap:anywhere]">
        {r.title} <ExternalLink size={13} className="mt-1 shrink-0" />
      </a>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8rem] text-muted">
        {r.is_demo && <DemoBadge />}
        <span className="text-charcoal-soft">{r.source?.publisher || r.source?.name}</span>
        {r.reliability && <ReliabilityBadge reliability={r.reliability} />}
        {r.period_label && <span>· {t('harvest.reports.period')}: {fmtPeriod(r.period_label, lang)}</span>}
        {r.published_at && <span>· {t('prov.published')} {fmtDate(r.published_at, lang)}</span>}
      </div>
      {summary && (
        <p className="mt-1 text-[0.86rem] text-charcoal-soft">
          {r.summary_is_ai && <span className="mr-1"><AiBadge label={t('harvest.reports.aiSummary')} /></span>}{summary}
        </p>
      )}
      {!summary && r.narrative_excerpt && readable(r.narrative_excerpt) && (
        <p className="mt-1 line-clamp-3 text-[0.84rem] text-muted">{r.narrative_excerpt}</p>
      )}
    </li>
  )
}

function NewsItem({ n }: { n: HarvestNews }) {
  const { t, lang } = useI18n()
  const translated = lang === 'it' ? n.title_it : n.title_en
  const title = translated ?? n.title
  const summary = pickLang(n as unknown as Record<string, unknown>, 'summary', lang)
  return (
    <li className="py-2.5 first:pt-0">
      <a href={pageUrl(n.url) ?? undefined} target="_blank" rel="noreferrer" className="link inline-flex items-start gap-1 font-medium [overflow-wrap:anywhere]">
        {title} <ExternalLink size={13} className="mt-1 shrink-0" />
      </a>
      {translated && translated !== n.title && (
        <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-[0.78rem] text-muted">
          <AiBadge label={t('news.card.aiTitle')} />
          <span>{t('harvest.reports.original')}: <span className="italic text-charcoal-soft">{n.title}</span></span>
        </div>
      )}
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8rem] text-muted">
        {n.is_demo && <DemoBadge />}
        <span className="text-charcoal-soft">{n.publisher || n.source?.name}</span>
        {n.published_at && <span>· {fmtDate(n.published_at, lang)}</span>}
        {n.harvest_topics.map((k) => <Badge key={k} tone="outline">{t(`harvest.reports.topic.${k}`)}</Badge>)}
      </div>
      {summary && n.ai_model && <p className="mt-1 text-[0.85rem] text-charcoal-soft"><AiBadge label={t('news.card.aiSummary')} /> {summary}</p>}
    </li>
  )
}
