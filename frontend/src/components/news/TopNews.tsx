// /notizie — "Le più importanti": the few stories that matter most right now, above the full list.
//
// Chosen by the backend (GET /api/news?sort=top): the relevance score every article already
// carries, a little more when several outlets ran the story, a little less for each day of age.
// The window is counted by the server (`days`), so the request is the same every day and the
// read-only online copy can answer it.
import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { AiBadge, DemoBadge, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtAgo } from '@/lib/format'
import { pageUrl } from '@/lib/links'
import { useLabels } from '@/lib/meta'
import { fmtNewsDate, utc } from './bits'
import type { NewsListResponse } from './types'
import { MIN_RELEVANT_SCORE } from './useNewsFilters'

export const TOP_NEWS_DAYS = 30
export const TOP_NEWS_COUNT = 5
const MAX_TAGS = 3

export function TopNews() {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const q = useQuery({
    queryKey: ['news', 'top', TOP_NEWS_DAYS, TOP_NEWS_COUNT],
    queryFn: () => api.get<NewsListResponse>('/news', {
      sort: 'top', days: TOP_NEWS_DAYS, page_size: TOP_NEWS_COUNT, min_relevance: MIN_RELEVANT_SCORE,
    }),
  })
  const items = q.data?.items ?? []
  // Nothing relevant in the period (or the request failed): the full list below still says so.
  if (items.length === 0) return null
  const topics = new Map((q.data?.facets.topics ?? []).map((x) => [x.key as string, x[lang]]))
  return (
    <Panel title={t('news.top.title')} eyebrow={t('news.top.eyebrow', { d: TOP_NEWS_DAYS })} bodyClassName="!py-1">
      <ol className="divide-y divide-line-soft" data-news-top>
        {items.map((it, i) => {
          const d = it.display[lang]
          const outlet = it.publisher || it.source?.publisher || it.source?.name || '—'
          const when = it.published_at
            ? fmtNewsDate(it.published_at, lang)
            : t('news.card.collected', { ago: fmtAgo(utc(it.collected_at), lang) })
          const tags = [
            ...it.topics.map((k) => topics.get(k) ?? k),
            ...it.countries.map((c) => country(c)),
          ].slice(0, MAX_TAGS)
          const why = lang === 'it' ? it.relevance_reason_it : it.relevance_reason_en
          return (
            <li key={it.id} className="flex gap-3 py-3" data-news-top-item={it.id}>
              <span className="num w-6 shrink-0 pt-0.5 text-right text-[1.05rem] font-semibold text-gold" aria-hidden>{i + 1}</span>
              <div className="min-w-0">
                <a href={pageUrl(it.url) ?? undefined} target="_blank" rel="noreferrer"
                  lang={d.title_is_ai ? lang : it.language ?? undefined}
                  className="font-serif text-[1.12rem] font-semibold leading-snug text-charcoal decoration-gold/60 underline-offset-[3px] hover:text-forest-800 hover:underline">
                  {d.title} <ExternalLink size={13} className="mb-0.5 inline text-muted" aria-hidden />
                </a>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.86rem] text-muted">
                  {it.is_demo && <DemoBadge />}
                  <span className="font-medium text-charcoal-soft">{outlet}</span>
                  <span aria-hidden>·</span>
                  <time dateTime={utc(it.published_at ?? it.collected_at) ?? undefined}>{when}</time>
                  {d.title_is_ai && <AiBadge />}
                  {it.duplicate_count > 0 && (
                    <span>· {it.duplicate_count === 1 ? t('news.top.outlets1') : t('news.top.outlets', { n: it.duplicate_count })}</span>
                  )}
                </div>
                {tags.length > 0 && (
                  <div className="mt-1 text-[0.86rem] text-forest-800" title={why ?? undefined}>{tags.join(' · ')}</div>
                )}
              </div>
            </li>
          )
        })}
      </ol>
      <p className="border-t border-line-soft py-2 text-[0.8rem] leading-snug text-muted">{t('news.top.how')}</p>
    </Panel>
  )
}
