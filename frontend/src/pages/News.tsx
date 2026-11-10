// /notizie — global honey-market news: search + filters, an editorial list of articles (AI output
// always labelled, publisher excerpt otherwise, link to the original), facet counts and feed status.
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowRight, Loader2, X } from 'lucide-react'
import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { NewsCard, type CardActions } from '@/components/news/NewsCard'
import { FilteredEmpty, NoNewsYet } from '@/components/news/NewsEmpty'
import { NewsFilters } from '@/components/news/NewsFilters'
import { CountriesFacet, LanguagesFacet, SourcesRail, TopicsFacet } from '@/components/news/NewsRail'
import { TopNews } from '@/components/news/TopNews'
import { useLangName, utc } from '@/components/news/bits'
import type { NewsDetail, NewsItem, NewsListResponse } from '@/components/news/types'
import { useNewsFilters } from '@/components/news/useNewsFilters'
import { ErrorBlock, Loading, PageHeader } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api, ApiError } from '@/lib/api'
import { fmtAgo, fmtNumber } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import type { SourceInfo } from '@/lib/types'
import { useView } from '@/lib/view'
import { Details } from '@/components/simple/Details'
import { SimpleNewsItem } from '@/components/simple/SimpleNews'

const PAGE_SIZE = 20

function ActivePill({ children, onRemove, label }: { children: ReactNode; onRemove: () => void; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-sm border border-forest-100 bg-forest-50 py-0.5 pl-2 pr-1 text-[0.86rem] text-forest-800">
      {children}
      <button type="button" onClick={onRemove} className="rounded-sm p-0.5 hover:bg-forest-100" title={label} aria-label={label}>
        <X size={13} />
      </button>
    </span>
  )
}

export default function News() {
  const { t, lang } = useI18n()
  const { simple } = useView()
  const { country } = useLabels()
  const langName = useLangName()
  const qc = useQueryClient()
  const f = useNewsFilters()
  const { state } = f

  const list = useInfiniteQuery({
    queryKey: ['news', 'list', f.apiParams],
    queryFn: ({ pageParam }) => api.get<NewsListResponse>('/news', { ...f.apiParams, page: pageParam, page_size: PAGE_SIZE }),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page < last.pages ? last.page + 1 : undefined),
    placeholderData: keepPreviousData,
  })
  // When a filtered request fails (on the phone copy: a combination of filters that was not
  // captured), the last good answer keeps the search box, the filters and the pills on screen
  // with the error inline, so the filter that caused it can be removed.
  const lastGood = useRef<NewsListResponse>()
  if (list.data?.pages[0]) lastGood.current = list.data.pages[0]
  const first = list.data?.pages[0] ?? (list.error ? lastGood.current : undefined)

  // With "Solo rilevanti per Parodi" on, count what the switch hides (same filters, any relevance).
  const allParams = useMemo(() => ({ ...f.apiParams, min_relevance: undefined, sort: undefined }), [f.apiParams])
  const hiddenQ = useQuery({
    queryKey: ['news', 'count-any-relevance', allParams],
    queryFn: () => api.get<NewsListResponse>('/news', { ...allParams, page_size: 1 }),
    enabled: state.relevantOnly && first !== undefined,
    placeholderData: keepPreviousData,
  })
  const hidden = state.relevantOnly && first && hiddenQ.data && !hiddenQ.isPlaceholderData && !list.isPlaceholderData
    ? Math.max(0, hiddenQ.data.total - first.total) : 0

  const sourcesQ = useQuery({ queryKey: ['sources'], queryFn: () => api.get<{ sources: SourceInfo[] }>('/sources'), refetchInterval: 60000 })
  const newsSources = useMemo(() => (sourcesQ.data?.sources ?? []).filter((s) => s.category === 'news'), [sourcesQ.data])

  // On-demand AI translation: put the translated article straight into every cached list page.
  const [translateErrors, setTranslateErrors] = useState<Record<number, unknown>>({})
  const [translatingIds, setTranslatingIds] = useState<Set<number>>(new Set())
  const translate = useMutation({
    mutationFn: (item: NewsItem) => api.post<NewsDetail>(`/news/${item.id}/translate?lang=${lang}`),
    onMutate: (item) => {
      setTranslatingIds((prev) => new Set(prev).add(item.id))
      setTranslateErrors(({ [item.id]: _drop, ...rest }) => rest)
    },
    onSettled: (_d, _e, item) => setTranslatingIds((prev) => {
      const next = new Set(prev)
      next.delete(item.id)
      return next
    }),
    onSuccess: (detail) => {
      qc.setQueriesData<InfiniteData<NewsListResponse>>({ queryKey: ['news', 'list'] }, (old) => old && ({
        ...old,
        pages: old.pages.map((p) => ({ ...p, items: p.items.map((it) => (it.id === detail.id ? { ...it, ...detail } : it)) })),
      }))
      qc.invalidateQueries({ queryKey: ['overview'] })
    },
    onError: (err, item) => setTranslateErrors((prev) => ({ ...prev, [item.id]: err })),
  })

  const items = useMemo(() => {
    const seen = new Set<number>()
    const out: NewsItem[] = []
    for (const p of list.data?.pages ?? []) for (const it of p.items) if (!seen.has(it.id)) { seen.add(it.id); out.push(it) }
    return out
  }, [list.data])

  const topicLabel = useCallback((key: string) => {
    const tp = first?.facets.topics.find((x) => x.key === key)
    return tp ? tp[lang] : key
  }, [first, lang])

  const baseActions: Omit<CardActions, 'translating' | 'translateError'> = {
    llmEnabled: first?.llm_enabled ?? false,
    topicLabel,
    activeCountries: state.countries,
    activeTopics: state.topics,
    onCountry: (c) => f.toggle('countries', c),
    onTopic: (k) => f.toggle('topics', k),
    onTranslate: (it) => translate.mutate(it),
  }

  const updated = first?.updated
  const sourceName = (key: string) => first?.facets.sources.find((s) => s.key === key)?.name
    ?? newsSources.find((s) => s.key === key)?.name ?? key
  const noNewsAtAll = first !== undefined && first.total === 0 && !updated?.last_collected_at
  const badFilters = list.error instanceof ApiError && list.error.status === 400

  const header = (
    <PageHeader
      eyebrow={t('news.eyebrow')}
      title={t('news.title')}
      subtitle={(
        <>
          {t('news.subtitle')}
          {updated && (
            <span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.88rem]">
              <span className={clsx('inline-block h-1.5 w-1.5 rounded-full', updated.last_checked_at ? 'bg-up' : 'bg-muted')} aria-hidden />
              <span>{updated.last_checked_at ? t('news.header.checked', { ago: fmtAgo(utc(updated.last_checked_at), lang) }) : t('news.header.neverChecked')}</span>
              <span aria-hidden>·</span>
              <span>{t('news.header.sources', { n: updated.sources_enabled, total: updated.sources_total })}</span>
              <span aria-hidden>·</span>
              <Link to="/fonti" className="inline-flex items-center gap-1 text-forest-700 hover:underline">
                {t('news.header.manage')} <ArrowRight size={14} />
              </Link>
            </span>
          )}
        </>
      )}
    />
  )

  if (list.isLoading) return <div>{header}<Loading /></div>

  if (list.error && !first) {
    return (
      <div className="space-y-5">
        {header}
        {badFilters ? (
          <div className="panel flex flex-wrap items-center justify-between gap-4 px-5 py-4">
            <div>
              <div className="font-medium text-down">{t('news.err.badFilters')}</div>
              <div className="text-[0.92rem] text-muted" title={list.error.message}>{t('news.err.badFiltersHint')}</div>
            </div>
            <button type="button" className="btn-secondary" onClick={f.reset}>{t('news.f.reset')}</button>
          </div>
        ) : (
          <>
            <ErrorBlock error={list.error} onRetry={() => list.refetch()} />
            {f.hasFilters && <button type="button" className="btn-secondary" onClick={f.reset}>{t('news.f.reset')}</button>}
          </>
        )}
      </div>
    )
  }
  if (!first || !updated) return null

  if (noNewsAtAll) {
    return (
      <div className="space-y-6">
        {header}
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
          <NoNewsYet updated={updated} newsSources={newsSources} />
          {newsSources.length > 0 && <SourcesRail sources={newsSources} facets={first.facets} state={state} toggle={(k) => f.toggle('sources', k)} />}
        </div>
      </div>
    )
  }

  const shown = items.length
  const periodActive = state.period !== 'all'
  const pills: ReactNode[] = []
  if (state.q) pills.push(<ActivePill key="q" label={t('news.f.clearSearch')} onRemove={() => f.update({ q: '' })}>{t('news.f.searchFor', { q: state.q })}</ActivePill>)
  for (const c of state.countries) pills.push(<ActivePill key={`c-${c}`} label={t('news.f.remove', { x: country(c) })} onRemove={() => f.toggle('countries', c)}>{country(c)}</ActivePill>)
  for (const k of state.topics) pills.push(<ActivePill key={`t-${k}`} label={t('news.f.remove', { x: topicLabel(k) })} onRemove={() => f.toggle('topics', k)}>{topicLabel(k)}</ActivePill>)
  for (const k of state.sources) pills.push(<ActivePill key={`s-${k}`} label={t('news.f.remove', { x: sourceName(k) })} onRemove={() => f.toggle('sources', k)}><span className="max-w-[18rem] truncate">{sourceName(k)}</span></ActivePill>)
  for (const k of state.langs) pills.push(<ActivePill key={`l-${k}`} label={t('news.f.remove', { x: langName(k) })} onRemove={() => f.toggle('langs', k)}>{t('news.f.lang', { x: langName(k) })}</ActivePill>)
  if (periodActive) pills.push(<ActivePill key="p" label={t('news.f.remove', { x: t(`news.f.period.${state.period}`) })} onRemove={() => f.update({ period: 'all' })}>{t(`news.f.period.${state.period}`)}</ActivePill>)

  const refreshing = list.isFetching && !list.isFetchingNextPage
  const failed = Boolean(list.error) && !list.data

  const filters = <NewsFilters state={state} facets={first.facets} update={f.update} toggle={f.toggle} />
  const facetsAside = (
    <aside className="grid items-start gap-5 md:grid-cols-2 xl:grid-cols-1">
      <TopicsFacet facets={first.facets} state={state} toggle={(k) => f.toggle('topics', k)} />
      <CountriesFacet facets={first.facets} state={state} toggle={(k) => f.toggle('countries', k)} />
      <LanguagesFacet facets={first.facets} state={state} toggle={(k) => f.toggle('langs', k)} />
      {newsSources.length > 0 && <SourcesRail sources={newsSources} facets={first.facets} state={state} toggle={(k) => f.toggle('sources', k)} />}
    </aside>
  )

  return (
    <div className="space-y-5" data-view={simple ? 'simple' : undefined}>
      {header}
      {simple ? (
        // Simple view (lib/view.tsx): the list first; search, filters and counts one click away.
        <Details bare className="!mt-0" label={t('simple.news.filters')} hideLabel={t('simple.news.filtersHide')}>
          <div className="space-y-5">
            {filters}
            <div className="grid items-start gap-5 md:grid-cols-2 [&_aside]:contents">{facetsAside}</div>
          </div>
        </Details>
      ) : filters}

      {/* The few stories that matter most, before the full list (hidden while the list is being narrowed). */}
      {!f.hasFilters && <TopNews />}

      <div className={clsx('grid items-start gap-6', !simple && 'xl:grid-cols-[minmax(0,1fr)_340px]')}>
        <div className="min-w-0 space-y-3">
          {/* results line */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {/* after a failed request `first` is the last good answer: its count belongs to other filters */}
            {!failed && (
              <h2 className="font-serif text-[1.25rem] font-semibold text-charcoal">
                {first.total === 1 ? t('news.results.count1') : t('news.results.count', { n: fmtNumber(first.total, lang) })}
                {state.relevantOnly && <span className="ml-1.5 font-sans text-[0.95rem] font-normal text-muted">{t(first.total === 1 ? 'news.results.relevantOnly1' : 'news.results.relevantOnly')}</span>}
              </h2>
            )}
            {pills.length > 0 && <div className="flex flex-wrap items-center gap-1.5">{pills}</div>}
            {f.hasFilters && (
              <button type="button" className="text-[0.88rem] text-forest-700 underline decoration-gold/50 underline-offset-2 hover:decoration-gold" onClick={f.reset}>
                {t('news.f.reset')}
              </button>
            )}
            <span className={clsx('ml-auto inline-flex items-center gap-1.5 text-[0.85rem] text-muted', !refreshing && 'invisible')} aria-live="polite">
              <Loader2 size={14} className="animate-spin" /> {t('news.results.updating')}
            </span>
          </div>

          {list.error && <ErrorBlock error={list.error} onRetry={() => list.refetch()} />}

          <section className={clsx('panel transition-opacity', refreshing && 'opacity-70', failed && 'hidden')}>
            {items.length === 0 ? (
              <FilteredEmpty relevantOnly={state.relevantOnly} hidden={hidden} hasFilters={f.hasFilters}
                onShowHidden={() => f.update({ relevantOnly: false })} onReset={f.reset} />
            ) : (
              <div className="divide-y divide-line-soft">
                {items.map((it) => simple ? <SimpleNewsItem key={it.id} item={it} /> : (
                  <NewsCard key={it.id} item={it} actions={{
                    ...baseActions,
                    translating: translatingIds.has(it.id),
                    translateError: translateErrors[it.id],
                  }} />
                ))}
              </div>
            )}

            {items.length > 0 && (
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-6 py-3.5">
                <span className="num text-[0.86rem] text-muted">{t('news.results.moreOf', { shown: fmtNumber(shown, lang), total: fmtNumber(first.total, lang) })}</span>
                {list.hasNextPage ? (
                  <button type="button" className="btn-secondary" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
                    {list.isFetchingNextPage ? <><Loader2 size={16} className="animate-spin" /> {t('news.results.loadingMore')}</> : t('news.results.more')}
                  </button>
                ) : (
                  <span className="text-[0.86rem] text-muted">{t('news.results.end')}</span>
                )}
              </div>
            )}
          </section>

          {items.length > 0 && hidden > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[0.92rem] text-muted">
              <span>{hidden === 1 ? t('news.results.hidden1') : t('news.results.hidden', { n: fmtNumber(hidden, lang) })}</span>
              <button type="button" className="text-forest-700 underline decoration-gold/50 underline-offset-2 hover:decoration-gold"
                onClick={() => f.update({ relevantOnly: false })}>
                {t('news.results.showHidden')}
              </button>
            </div>
          )}
        </div>

        {!simple && facetsAside}
      </div>
    </div>
  )
}
