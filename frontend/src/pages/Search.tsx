// /cerca?q= — global search with grouped results, keyboard navigation and helpful empty states.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Search as SearchIcon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ResultGroup, groupTitleKey } from '@/components/search/SearchResults'
import type { SearchResponse } from '@/components/search/types'
import { ErrorBlock, Loading, PageHeader, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtNumber } from '@/lib/format'

const RESULT_SELECTOR = '[data-result]'

export default function Search() {
  const { t, lang } = useI18n()
  const [params, setParams] = useSearchParams()
  const q = (params.get('q') ?? '').trim()
  const [text, setText] = useState(q)
  const inputRef = useRef<HTMLInputElement>(null)
  const resultsRef = useRef<HTMLDivElement>(null)

  useEffect(() => setText(q), [q])

  const res = useQuery({
    queryKey: ['search', q],
    queryFn: () => api.get<SearchResponse>('/search', { q, limit: 8 }),
    placeholderData: keepPreviousData,
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const v = text.trim()
    setParams(v ? { q: v } : {})
  }

  const results = useCallback(() => Array.from(resultsRef.current?.querySelectorAll<HTMLElement>(RESULT_SELECTOR) ?? []), [])

  // "/" focuses the search box from anywhere on the page (unless typing in another field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      const typing = el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
      if (e.key === '/' && !typing) {
        e.preventDefault()
        inputRef.current?.focus()
        inputRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const onInputKey = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      const first = results()[0]
      if (first) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  const onResultsKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Escape') return
    const list = results()
    const idx = list.indexOf(document.activeElement as HTMLElement)
    if (e.key === 'Escape') {
      inputRef.current?.focus()
      return
    }
    if (idx < 0) return
    e.preventDefault()
    if (e.key === 'ArrowDown') list[Math.min(idx + 1, list.length - 1)]?.focus()
    else if (idx === 0) inputRef.current?.focus()
    else list[idx - 1]?.focus()
  }

  const data = res.data
  const groups = (data?.groups ?? []).filter((g) => g.items.length > 0)
  const shownForQuery = data && data.query === q

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={t('search.eyebrow')} title={q ? t('search.titleFor', { q }) : t('search.title')} subtitle={t('search.subtitle')} />

      <form onSubmit={submit} role="search" className="flex flex-wrap items-stretch gap-3">
        <label className="relative flex-1 min-w-[18rem] max-w-3xl">
          <span className="sr-only">{t('ui.search')}</span>
          <SearchIcon size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted" />
          <input
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onInputKey}
            placeholder={t('search.placeholder')}
            autoFocus
            className="field !pl-12 !py-3 !text-[1.1rem]"
            aria-describedby="search-keys"
          />
        </label>
        <button type="submit" className="btn-primary !px-6">{t('search.button')}</button>
      </form>
      <p id="search-keys" className="-mt-3 text-[0.85rem] text-muted">{t('search.keyboard')}</p>

      {res.isLoading ? <Loading /> : res.error ? <ErrorBlock error={res.error} onRetry={() => res.refetch()} /> : data && (
        <div ref={resultsRef} onKeyDown={onResultsKey} className={res.isFetching && !shownForQuery ? 'opacity-60 transition-opacity' : undefined}>
          {groups.length > 0 ? (
            <div className="space-y-5">
              <nav aria-label={t('search.jump')} className="flex flex-wrap items-center gap-x-1 gap-y-2 text-[0.92rem]">
                <span className="text-charcoal-soft font-medium mr-2">
                  {data.total === 1 ? t('search.summaryOne') : t('search.summary', { n: fmtNumber(data.total, lang) })}
                </span>
                <span className="text-muted mr-1">· {t('search.jump')}:</span>
                {groups.map((g) => (
                  <a key={g.key} href={`#grp-${g.key}`} className="rounded-sm border border-line bg-white px-2.5 py-1 hover:border-forest-600 hover:text-forest-800">
                    {t(groupTitleKey(g.key))} <span className="num text-muted">{fmtNumber(g.total, lang)}</span>
                  </a>
                ))}
              </nav>
              {groups.map((g) => <ResultGroup key={g.key} group={g} query={data.query} />)}
            </div>
          ) : (
            <Suggestions data={data} />
          )}
        </div>
      )}
    </div>
  )
}

function Suggestions({ data }: { data: SearchResponse }) {
  const { t, lang } = useI18n()
  const s = data.suggestions
  const chip = 'inline-flex items-center rounded-sm border border-line bg-white px-3 py-1.5 text-[0.95rem] text-charcoal-soft hover:border-forest-600 hover:text-forest-800'
  const examples = [1, 2, 3, 4].map((i) => t(`search.example.${i}`))
  return (
    <Panel>
      <div className="max-w-3xl mx-auto py-4 text-center">
        <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-gold-pale text-gold-dark"><SearchIcon size={20} /></div>
        <h2 className="font-serif text-[1.45rem] text-charcoal">{data.query ? t('search.none.title', { q: data.query }) : t('search.empty.title')}</h2>
        <p className="mt-1.5 text-muted">{data.query ? t('search.none.hint') : t('search.empty.hint')}</p>
      </div>
      <div className="mt-4 grid gap-6 md:grid-cols-3 border-t border-line-soft pt-6">
        {s && s.countries.length > 0 && (
          <div>
            <h3 className="eyebrow font-sans mb-2">{t('search.suggest.countries')}</h3>
            <div className="flex flex-wrap gap-2">
              {s.countries.map((c) => {
                const name = lang === 'it' ? c.name_it : c.name_en
                return <Link key={c.iso3} to={`/cerca?q=${encodeURIComponent(name)}`} className={chip} data-result="">{name}</Link>
              })}
            </div>
          </div>
        )}
        {s && s.varieties.length > 0 && (
          <div>
            <h3 className="eyebrow font-sans mb-2">{t('search.suggest.varieties')}</h3>
            <div className="flex flex-wrap gap-2">
              {s.varieties.map((v) => {
                const name = lang === 'it' ? v.it : v.en
                return <Link key={v.key} to={`/cerca?q=${encodeURIComponent(name.split(/[/(]/)[0].trim())}`} className={chip} data-result="">{name}</Link>
              })}
            </div>
          </div>
        )}
        <div>
          <h3 className="eyebrow font-sans mb-2">{t('search.suggest.examples')}</h3>
          <div className="flex flex-wrap gap-2">
            {examples.map((e) => <Link key={e} to={`/cerca?q=${encodeURIComponent(e)}`} className={chip} data-result="">{e}</Link>)}
          </div>
        </div>
      </div>
    </Panel>
  )
}
