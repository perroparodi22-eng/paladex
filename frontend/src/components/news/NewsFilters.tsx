// Filter bar for /notizie: search, priority-country chips, topic, source, period presets,
// "Solo rilevanti per Parodi" and sort. All state lives in the URL (useNewsFilters).
import { Search, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Segmented } from '@/components/ui'
import { useI18n } from '@/i18n'
import { sourceName, useLabels } from '@/lib/meta'
import { Field, FilterChip, Switch } from './bits'
import type { NewsFacets, NewsFilterState, PeriodPreset } from './types'
import { PERIODS } from './useNewsFilters'

/** Origins Parodi Group buys from, then its own markets (Italy, United States). */
export const PRIORITY_COUNTRIES = ['ARG', 'CHN', 'UKR', 'SRB', 'BRA', 'VNM', 'IND', 'ITA', 'USA']

const SEARCH_DEBOUNCE_MS = 450

function SearchBox({ value, onChange }: { value: string; onChange: (q: string) => void }) {
  const { t } = useI18n()
  const [text, setText] = useState(value)
  const last = useRef(value)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  // follow the URL (back button, links from global search)
  useEffect(() => {
    if (value !== last.current) {
      last.current = value
      setText(value)
    }
  }, [value])

  // search while typing, after a short pause
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
    <form onSubmit={submit} role="search" className="relative w-full min-w-0 xl:w-auto xl:flex-1">
      <Search size={19} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t('news.f.searchPlaceholder')}
        aria-label={t('news.f.search')}
        className="field !py-2.5 !pl-11 !pr-24 text-[1.02rem]"
        type="search"
        enterKeyHint="search"
      />
      <div className="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-1">
        {text && (
          <button type="button" className="rounded-sm p-1.5 text-muted hover:bg-paper hover:text-charcoal" title={t('news.f.clearSearch')}
            aria-label={t('news.f.clearSearch')} onClick={() => { setText(''); last.current = ''; onChange('') }}>
            <X size={16} />
          </button>
        )}
        <button type="submit" className="btn-primary !px-3 !py-1.5 text-[0.9rem]">{t('news.f.search')}</button>
      </div>
    </form>
  )
}

export function NewsFilters({ state, facets, update, toggle }: {
  state: NewsFilterState
  facets: NewsFacets | undefined
  update: (p: Partial<NewsFilterState>) => void
  toggle: (field: 'countries' | 'topics' | 'sources' | 'langs', key: string) => void
}) {
  const { t, lang } = useI18n()
  const { country } = useLabels()

  const countryCount = new Map((facets?.countries ?? []).map((c) => [c.key, c.count]))
  const chipCountries = [...PRIORITY_COUNTRIES, ...state.countries.filter((c) => !PRIORITY_COUNTRIES.includes(c))]
  const otherCountries = (facets?.countries ?? []).filter((c) => !chipCountries.includes(c.key))
  const countryName = (iso3: string) => {
    const f = facets?.countries.find((c) => c.key === iso3)
    return f ? (lang === 'it' ? f.name_it : f.name_en) || country(iso3) : country(iso3)
  }

  const topics = facets?.topics ?? []
  const sources = facets?.sources ?? []
  const selectedSourceMissing = state.sources.filter((k) => !sources.some((s) => s.key === k))

  const topicValue = state.topics.length === 1 ? state.topics[0] : state.topics.length > 1 ? '__many' : ''
  const sourceValue = state.sources.length === 1 ? state.sources[0] : state.sources.length > 1 ? '__many' : ''

  return (
    <section className="panel" aria-label={t('ui.search')}>
      <div className="flex flex-wrap items-end gap-x-5 gap-y-3 border-b border-line-soft px-5 py-4">
        <SearchBox value={state.q} onChange={(q) => update({ q })} />
        <Field label={t('news.f.sort')} className="shrink-0">
          <Segmented<'date' | 'relevance'>
            value={state.sort}
            onChange={(v) => update({ sort: v })}
            options={[{ value: 'date', label: t('news.f.sort.date') }, { value: 'relevance', label: t('news.f.sort.relevance') }]}
          />
        </Field>
      </div>

      <div className="border-b border-line-soft px-5 py-3.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-2 text-[0.76rem] font-medium uppercase tracking-[0.1em] text-muted">{t('news.f.countries')}</span>
          <FilterChip active={state.countries.length === 0} onClick={() => update({ countries: [] })}>{t('news.f.allCountries')}</FilterChip>
          {chipCountries.map((c) => {
            const n = countryCount.get(c) ?? 0
            return (
              <FilterChip key={c} active={state.countries.includes(c)} count={n} dim={n === 0}
                title={t('news.f.filterBy', { x: countryName(c) })} onClick={() => toggle('countries', c)}>
                {countryName(c)}
              </FilterChip>
            )
          })}
          {otherCountries.length > 0 && (
            <select
              className="field !w-auto !py-1 !pl-2.5 pr-8 text-[0.92rem] text-charcoal-soft"
              value=""
              aria-label={t('news.f.otherCountries')}
              onChange={(e) => e.target.value && toggle('countries', e.target.value)}
            >
              <option value="">{t('news.f.otherCountriesN', { n: otherCountries.length })}</option>
              {otherCountries.map((c) => (
                <option key={c.key} value={c.key}>{(lang === 'it' ? c.name_it : c.name_en) || country(c.key)} ({c.count})</option>
              ))}
            </select>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 items-end gap-x-5 gap-y-3.5 px-5 py-4 md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
        <Field label={t('news.f.topic')}>
          <select className="field pr-8" value={topicValue} aria-label={t('news.f.topic')}
            onChange={(e) => update({ topics: e.target.value ? [e.target.value] : [] })}>
            <option value="">{t('news.f.allTopics')}</option>
            {topicValue === '__many' && <option value="__many" disabled>{t('news.f.nTopics', { n: state.topics.length })}</option>}
            {topics.map((tp) => (
              <option key={tp.key} value={tp.key}>{tp[lang]} ({tp.count})</option>
            ))}
          </select>
        </Field>
        <Field label={t('news.f.source')}>
          <select className="field pr-8" value={sourceValue} aria-label={t('news.f.source')}
            onChange={(e) => update({ sources: e.target.value ? [e.target.value] : [] })}>
            <option value="">{t('news.f.allSources')}</option>
            {sourceValue === '__many' && <option value="__many" disabled>{t('news.f.nSources', { n: state.sources.length })}</option>}
            {sources.map((s) => <option key={s.key} value={s.key}>{sourceName(s, lang)} ({s.count})</option>)}
            {selectedSourceMissing.map((k) => <option key={k} value={k}>{k} (0)</option>)}
          </select>
        </Field>
        <Field label={t('news.f.period')} className="[&_button]:whitespace-nowrap">
          <Segmented<PeriodPreset>
            value={state.period}
            onChange={(v) => update({ period: v })}
            options={PERIODS.map((p) => ({ value: p, label: t(`news.f.period.${p}`) }))}
          />
        </Field>
        <div className="flex h-[38px] items-center">
          <Switch checked={state.relevantOnly} onChange={(v) => update({ relevantOnly: v })}
            label={t('news.f.relevantOnly')} hint={t('news.f.relevantOnlyHint')} />
        </div>
      </div>
    </section>
  )
}
