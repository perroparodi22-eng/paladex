// Filter state for /notizie, kept in the URL so a view can be bookmarked or linked to
// (the overview links to /notizie?country=ARG, global search to /notizie?q=…).
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { NewsFilterState, NewsSort, PeriodPreset } from './types'

/** "Solo rilevanti per Parodi": medium relevance or higher (backend `relevance_level`: medium >= 35). */
export const MIN_RELEVANT_SCORE = 35

export const PERIODS: PeriodPreset[] = ['today', '7d', '30d', 'all']

const list = (v: string | null) => (v ?? '').split(',').map((x) => x.trim()).filter(Boolean)

function isoLocalDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** First day included by a period preset (inclusive), or undefined for "all". */
export function periodFrom(period: PeriodPreset, now = new Date()): string | undefined {
  if (period === 'all') return undefined
  const d = new Date(now)
  if (period === '7d') d.setDate(d.getDate() - 6)
  if (period === '30d') d.setDate(d.getDate() - 29)
  return isoLocalDate(d)
}

export function useNewsFilters() {
  const [sp, setSp] = useSearchParams()

  const state: NewsFilterState = useMemo(() => {
    const period = sp.get('period')
    return {
      q: sp.get('q') ?? '',
      countries: list(sp.get('country')).map((c) => c.toUpperCase()),
      topics: list(sp.get('topic')),
      sources: list(sp.get('source')),
      langs: list(sp.get('lang')),
      period: (PERIODS as string[]).includes(period ?? '') ? (period as PeriodPreset) : 'all',
      relevantOnly: sp.get('relevance') !== 'all',
      sort: (sp.get('sort') === 'relevance' ? 'relevance' : 'date') as NewsSort,
    }
  }, [sp])

  const update = useCallback((patch: Partial<NewsFilterState>) => {
    setSp((prev) => {
      const next = new URLSearchParams(prev)
      const set = (k: string, v: string | undefined, def = '') => {
        if (v === undefined) return
        if (v === def) next.delete(k)
        else next.set(k, v)
      }
      set('q', patch.q?.trim())
      set('country', patch.countries?.join(','))
      set('topic', patch.topics?.join(','))
      set('source', patch.sources?.join(','))
      set('lang', patch.langs?.join(','))
      set('period', patch.period, 'all')
      if (patch.relevantOnly !== undefined) set('relevance', patch.relevantOnly ? '' : 'all')
      set('sort', patch.sort, 'date')
      return next
    }, { replace: true })
  }, [setSp])

  const toggle = useCallback((field: 'countries' | 'topics' | 'sources' | 'langs', key: string) => {
    const cur = state[field]
    update({ [field]: cur.includes(key) ? cur.filter((x) => x !== key) : [...cur, key] })
  }, [state, update])

  /** Clears what narrows the list; keeps sort and the relevance switch (a reading preference). */
  const reset = useCallback(() => update({ q: '', countries: [], topics: [], sources: [], langs: [], period: 'all' }), [update])

  const hasFilters = Boolean(state.q || state.countries.length || state.topics.length || state.sources.length
    || state.langs.length || state.period !== 'all')

  /** Query parameters for GET /api/news (without page). */
  const apiParams = useMemo(() => ({
    q: state.q || undefined,
    country: state.countries.join(',') || undefined,
    topic: state.topics.join(',') || undefined,
    source: state.sources.join(',') || undefined,
    lang: state.langs.join(',') || undefined,
    from: periodFrom(state.period),
    min_relevance: state.relevantOnly ? MIN_RELEVANT_SCORE : undefined,
    sort: state.sort === 'date' ? undefined : state.sort,
  }), [state])

  return { state, update, toggle, reset, hasFilters, apiParams }
}
