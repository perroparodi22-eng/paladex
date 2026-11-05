// "Documenti ufficiali": EU legislation, Federal Register notices and RASFF notifications with
// filters by jurisdiction, type and country, a search box, and honest empty states.
import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ExternalLink, FileText, Loader2, Search, SearchX, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Badge, DemoBadge, EmptyState, ErrorBlock, FreshnessBadge, Loading, Panel, ReliabilityBadge, Segmented } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api, ApiError } from '@/lib/api'
import { fmtAgo, fmtDate, fmtNumber } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import type { DocSource, RegulationDoc, RegulationsResponse } from './types'
import { useDocFilters } from './useDocFilters'

const PAGE_SIZE = 20
const SEARCH_DEBOUNCE_MS = 450

function SearchBox({ value, onChange }: { value: string; onChange: (q: string) => void }) {
  const { t } = useI18n()
  const [text, setText] = useState(value)
  const last = useRef(value)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  useEffect(() => {
    if (value !== last.current) {
      last.current = value
      setText(value)
    }
  }, [value])

  useEffect(() => {
    if (text.trim() === last.current.trim()) return
    const id = window.setTimeout(() => {
      last.current = text.trim()
      onChangeRef.current(text.trim())
    }, SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [text])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    last.current = text.trim()
    onChange(text.trim())
  }

  return (
    <form onSubmit={submit} role="search" className="relative min-w-0 flex-1 basis-[22rem]">
      <Search size={18} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
      <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t('regulations.docs.searchPlaceholder')}
        aria-label={t('regulations.docs.search')} className="field !py-2.5 !pl-11 !pr-24" type="search" enterKeyHint="search" />
      <div className="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-1">
        {text && (
          <button type="button" className="rounded-sm p-1.5 text-muted hover:bg-paper hover:text-charcoal" title={t('regulations.docs.clearSearch')}
            aria-label={t('regulations.docs.clearSearch')} onClick={() => { setText(''); last.current = ''; onChange('') }}>
            <X size={16} />
          </button>
        )}
        <button type="submit" className="btn-primary !px-3 !py-1.5 text-[0.9rem]">{t('regulations.docs.search')}</button>
      </div>
    </form>
  )
}

function useTypeLabel() {
  const { t } = useI18n()
  return (k: string) => {
    const key = `regulations.type.${k}`
    const v = t(key)
    return v === key ? k.replace(/_/g, ' ') : v
  }
}

function useJurisdictionLabel() {
  const { t } = useI18n()
  return (k: string) => {
    const key = `regulations.j.${k}`
    const v = t(key)
    return v === key ? k : v
  }
}

function DocItem({ doc }: { doc: RegulationDoc }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const typeLabel = useTypeLabel()
  const jLabel = useJurisdictionLabel()
  const [open, setOpen] = useState(false)
  return (
    <article className="grid gap-x-5 gap-y-1 px-5 py-4 md:grid-cols-[7.5rem_minmax(0,1fr)]">
      <div className="text-[0.86rem] text-muted">
        <div className="num text-charcoal-soft">{fmtDate(doc.published_at, lang)}</div>
        <div className="mt-1 flex flex-wrap gap-1">
          <Badge tone="forest">{jLabel(doc.jurisdiction)}</Badge>
        </div>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={doc.doc_type === 'antidumping' || doc.doc_type === 'tariff' ? 'gold' : doc.doc_type === 'food_safety_notification' ? 'down' : 'neutral'}>
            {typeLabel(doc.doc_type)}
          </Badge>
          {doc.ad_cases.map((c) => (
            <Badge key={c.origin_iso3} tone="outline" title={c.product}>
              {c.case_number ? t('regulations.docs.adCase', { n: c.case_number }) : t('regulations.docs.adCaseNoNumber', { product: country(c.origin_iso3) })}
            </Badge>
          ))}
          {doc.is_demo && <DemoBadge />}
        </div>
        <h3 className="mt-1 text-[1.02rem] font-medium leading-snug text-charcoal">
          <a href={doc.url} target="_blank" rel="noreferrer" className="hover:text-forest-700 hover:underline decoration-gold/60 underline-offset-2"
            title={t('regulations.docs.open')}>
            {doc.title}
            <ExternalLink size={13} className="ml-1 inline-block align-baseline text-muted" />
          </a>
        </h3>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8rem] text-muted">
          <span className="num text-charcoal-soft">{doc.reference}</span>
          {doc.source && <span>· {doc.source.publisher || doc.source.name}</span>}
          {doc.reliability && <ReliabilityBadge reliability={doc.reliability} />}
          {doc.effective_date && <span>· {t('regulations.docs.effective', { date: fmtDate(doc.effective_date, lang) })}</span>}
          {doc.collected_at && <span>· {t('regulations.docs.collected', { ago: fmtAgo(doc.collected_at, lang) })}</span>}
        </div>
        {doc.countries.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {doc.countries.map((c) => (
              <Link key={c} to={`/paesi/${c}`} className="rounded-sm border border-line-soft bg-paper px-1.5 py-0.5 text-[0.76rem] text-charcoal-soft hover:border-forest-300">
                {country(c)}
              </Link>
            ))}
          </div>
        )}
        {doc.summary_en && (
          <div className="mt-1.5">
            <button type="button" className="text-[0.82rem] text-forest-700 hover:underline" aria-expanded={open} onClick={() => setOpen(!open)}>
              {t(open ? 'regulations.docs.summaryHide' : 'regulations.docs.summaryShow')}
            </button>
            {open && (
              <div className="mt-1 border-l-2 border-gold-light/70 pl-3">
                <div className="eyebrow mb-0.5">{t('regulations.docs.summary')}</div>
                <p className="text-[0.9rem] leading-relaxed text-charcoal-soft" lang="en">{doc.summary_en}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </article>
  )
}

function SourcesStatus({ sources }: { sources: DocSource[] }) {
  const { t, lang } = useI18n()
  if (sources.length === 0) return null
  return (
    <ul className="mx-auto mt-2 max-w-2xl divide-y divide-line-soft rounded-sm border border-line-soft text-left text-[0.88rem]">
      {sources.map((s) => (
        <li key={s.key} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
          <span className="text-charcoal-soft">{s.name}</span>
          <span className="flex items-center gap-2 text-muted">
            <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />
            {s.last_run_at ? t('regulations.docs.sourceChecked', { ago: fmtAgo(s.last_run_at, lang) }) : t('regulations.docs.sourceNever')}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function DocumentsPanel() {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const typeLabel = useTypeLabel()
  const jLabel = useJurisdictionLabel()
  const f = useDocFilters()
  const { state } = f

  const list = useInfiniteQuery({
    queryKey: ['regulations', 'docs', f.apiParams],
    queryFn: ({ pageParam }) => api.get<RegulationsResponse>('/regulations', { ...f.apiParams, page: pageParam, page_size: PAGE_SIZE }),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page < last.pages ? last.page + 1 : undefined),
    placeholderData: keepPreviousData,
  })
  const first = list.data?.pages[0]
  const items = useMemo(() => {
    const seen = new Set<number>()
    const out: RegulationDoc[] = []
    for (const p of list.data?.pages ?? []) for (const it of p.items) if (!seen.has(it.id)) { seen.add(it.id); out.push(it) }
    return out
  }, [list.data])

  const facets = first?.facets
  const jurisdictions = facets?.jurisdictions ?? []
  const jOptions = [{ value: '', label: t('regulations.docs.allJurisdictions') },
    ...jurisdictions.map((j) => ({ value: j.key, label: `${jLabel(j.key)} (${fmtNumber(j.count, lang)})` }))]
  if (state.jurisdiction && !jurisdictions.some((j) => j.key === state.jurisdiction)) {
    jOptions.push({ value: state.jurisdiction, label: jLabel(state.jurisdiction) })
  }
  const nothingAtAll = first !== undefined && !f.hasFilters && first.total === 0
  const badFilters = list.error instanceof ApiError && list.error.status === 400
  const refreshing = list.isFetching && !list.isFetchingNextPage

  return (
    <Panel title={t('regulations.docs.title')} eyebrow={t('regulations.docs.eyebrow')} bodyClassName="!p-0">
      {!nothingAtAll && (
        <div className="space-y-3 border-b border-line-soft px-5 py-4">
          <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
            <SearchBox value={state.q} onChange={(q) => f.update({ q })} />
            <div className="shrink-0 max-w-full">
              <span className="label">{t('regulations.docs.jurisdiction')}</span>
              <Segmented<string> size="sm" value={state.jurisdiction} onChange={(v) => f.update({ jurisdiction: v })} options={jOptions} />
            </div>
          </div>
          <div className="grid gap-x-5 gap-y-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
            <label className="block">
              <span className="label">{t('regulations.docs.type')}</span>
              <select className="field pr-8" value={state.docType} onChange={(e) => f.update({ docType: e.target.value })}>
                <option value="">{t('regulations.docs.allTypes')}</option>
                {(facets?.doc_types ?? []).map((d) => <option key={d.key} value={d.key}>{typeLabel(d.key)} ({d.count})</option>)}
                {state.docType && !facets?.doc_types.some((d) => d.key === state.docType) && <option value={state.docType}>{typeLabel(state.docType)}</option>}
              </select>
            </label>
            <label className="block">
              <span className="label">{t('regulations.docs.country')}</span>
              <select className="field pr-8" value={state.country} onChange={(e) => f.update({ country: e.target.value })}>
                <option value="">{t('regulations.docs.allCountries')}</option>
                {(facets?.countries ?? []).map((c) => <option key={c.key} value={c.key}>{country(c.key)} ({c.count})</option>)}
                {state.country && !facets?.countries.some((c) => c.key === state.country) && <option value={state.country}>{country(state.country)}</option>}
              </select>
            </label>
            <button type="button" className="btn-secondary" onClick={f.reset} disabled={!f.hasFilters}>{t('regulations.docs.reset')}</button>
          </div>
        </div>
      )}

      {list.isLoading ? <Loading /> : list.error && !first ? (
        <div className="p-5">
          {badFilters ? (
            <EmptyState icon={<SearchX size={22} />} title={t('regulations.docs.filteredTitle')} hint={list.error.message}
              action={<button type="button" className="btn-secondary" onClick={f.reset}>{t('regulations.docs.reset')}</button>} />
          ) : <ErrorBlock error={list.error} onRetry={() => list.refetch()} />}
        </div>
      ) : !first ? null : nothingAtAll ? (
        <div className="px-5 pb-6">
          <EmptyState icon={<FileText size={22} />} title={t('regulations.docs.emptyTitle')} hint={t('regulations.docs.emptyBody')} />
          <SourcesStatus sources={first.sources} />
        </div>
      ) : (
        <div className={clsx('transition-opacity', refreshing && 'opacity-70')}>
          <div className="flex items-center justify-between gap-3 px-5 pt-3 text-[0.9rem]">
            <span className="font-medium text-charcoal">
              {first.total === 1 ? t('regulations.docs.count1') : t('regulations.docs.count', { n: fmtNumber(first.total, lang) })}
            </span>
            <span className={clsx('inline-flex items-center gap-1.5 text-[0.85rem] text-muted', !refreshing && 'invisible')} aria-live="polite">
              <Loader2 size={14} className="animate-spin" />
            </span>
          </div>
          {items.length === 0 ? (
            <EmptyState icon={<SearchX size={22} />} title={t('regulations.docs.filteredTitle')} hint={t('regulations.docs.filteredBody')}
              action={<button type="button" className="btn-secondary" onClick={f.reset}>{t('regulations.docs.reset')}</button>} />
          ) : (
            <>
              <div className="divide-y divide-line-soft">{items.map((d) => <DocItem key={d.id} doc={d} />)}</div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
                <span className="num text-[0.86rem] text-muted">
                  {t('regulations.docs.moreOf', { shown: fmtNumber(items.length, lang), total: fmtNumber(first.total, lang) })}
                </span>
                {list.hasNextPage ? (
                  <button type="button" className="btn-secondary" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
                    {list.isFetchingNextPage ? <><Loader2 size={16} className="animate-spin" /> {t('regulations.docs.loadingMore')}</> : t('regulations.docs.more')}
                  </button>
                ) : <span className="text-[0.86rem] text-muted">{t('regulations.docs.end')}</span>}
              </div>
            </>
          )}
        </div>
      )}
    </Panel>
  )
}
