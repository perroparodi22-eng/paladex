// Right rail of /notizie: topic, country and language counts for the current results (each row
// filters the list) and the news feeds with their freshness and last check.
import clsx from 'clsx'
import { AlertTriangle, ArrowRight, Check, ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { FreshnessBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtAgo, fmtNumber } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import type { SourceInfo } from '@/lib/types'
import { useLangName, utc } from './bits'
import type { CountryFacet, LanguageFacet, NewsFacets, NewsFilterState } from './types'

const COUNTRIES_COLLAPSED = 10
const SOURCES_COLLAPSED = 8

function RailPanel({ title, sub, children, footer }: { title: string; sub?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <section className="panel">
      <div className="border-b border-line-soft px-4 pb-2.5 pt-3">
        <h2 className="font-serif text-[1.05rem] font-semibold text-charcoal">{title}</h2>
        {sub && <p className="mt-0.5 text-[0.8rem] leading-snug text-muted">{sub}</p>}
      </div>
      <div className="py-1.5">{children}</div>
      {footer && <div className="border-t border-line-soft px-4 py-2">{footer}</div>}
    </section>
  )
}

/** One facet row: check box, label and count; clicking it filters the list. */
function FacetRow({ label, count, active, onClick, title, marker }: {
  label: ReactNode; count: number; active: boolean; onClick: () => void; title?: string; marker?: ReactNode
}) {
  const { lang } = useI18n()
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={title}
      className={clsx(
        'flex w-full items-center gap-2.5 px-4 py-[7px] text-left text-[0.93rem] transition-colors',
        active ? 'bg-forest-50 text-forest-900' : count ? 'text-charcoal-soft hover:bg-paper' : 'text-muted hover:bg-paper',
      )}
    >
      <span className={clsx('flex h-[15px] w-[15px] shrink-0 items-center justify-center rounded-[2px] border',
        active ? 'border-forest-800 bg-forest-800 text-ivory' : 'border-line bg-white')} aria-hidden>
        {active && <Check size={11} strokeWidth={3} />}
      </span>
      <span className={clsx('flex min-w-0 flex-1 items-center gap-2', active && 'font-medium')}>
        <span className="truncate">{label}</span>
        {marker}
      </span>
      <span className={clsx('num w-8 shrink-0 text-right text-[0.84rem]', count ? 'text-charcoal-soft' : 'text-line')}>{fmtNumber(count, lang)}</span>
    </button>
  )
}

function ShowMore({ open, n, onClick, labelAll }: { open: boolean; n: number; onClick: () => void; labelAll: string }) {
  const { t } = useI18n()
  return (
    <button type="button" className="px-4 pb-1 pt-1.5 text-[0.86rem] text-forest-700 hover:underline" onClick={onClick}>
      {open ? t('news.rail.showFewer') : labelAll.replace('{n}', String(n))}
    </button>
  )
}

export function TopicsFacet({ facets, state, toggle }: { facets: NewsFacets; state: NewsFilterState; toggle: (k: string) => void }) {
  const { t, lang } = useI18n()
  return (
    <RailPanel title={t('news.rail.topics')}>
      {facets.topics.map((tp) => (
        <FacetRow key={tp.key} label={tp[lang]} count={tp.count} active={state.topics.includes(tp.key)}
          onClick={() => toggle(tp.key)} title={t('news.f.filterBy', { x: tp[lang] })} />
      ))}
    </RailPanel>
  )
}

export function CountriesFacet({ facets, state, toggle }: { facets: NewsFacets; state: NewsFilterState; toggle: (k: string) => void }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const [open, setOpen] = useState(false)
  // selected countries stay listed (with 0) even when nothing matches, so they can be unticked here
  const rows: CountryFacet[] = [
    ...facets.countries,
    ...state.countries.filter((k) => !facets.countries.some((c) => c.key === k))
      .map((k) => ({ key: k, count: 0, name_it: '', name_en: '', origin_of_interest: false })),
  ]
  // keep selected countries visible when the list is collapsed
  const shown = open ? rows : rows.filter((c, i) => i < COUNTRIES_COLLAPSED || state.countries.includes(c.key))
  return (
    <RailPanel title={t('news.rail.countries')} sub={rows.some((c) => c.origin_of_interest) ? t('news.rail.countriesSub') : undefined}>
      {rows.length === 0 && <p className="px-4 py-2 text-[0.88rem] text-muted">{t('news.rail.none')}</p>}
      {shown.map((c) => {
        const name = (lang === 'it' ? c.name_it : c.name_en) || country(c.key)
        return (
          <FacetRow key={c.key} label={name} count={c.count} active={state.countries.includes(c.key)}
            onClick={() => toggle(c.key)} title={t('news.f.filterBy', { x: name })}
            marker={c.origin_of_interest ? <span className="h-[7px] w-[7px] shrink-0 rounded-full bg-gold" title={t('news.rail.originOfInterest')} /> : undefined} />
        )
      })}
      {rows.length > COUNTRIES_COLLAPSED && (
        <ShowMore open={open} n={rows.length} onClick={() => setOpen((v) => !v)} labelAll={t('news.rail.showAll', { n: rows.length })} />
      )}
    </RailPanel>
  )
}

export function LanguagesFacet({ facets, state, toggle }: { facets: NewsFacets; state: NewsFilterState; toggle: (k: string) => void }) {
  const { t } = useI18n()
  const langName = useLangName()
  if (facets.languages.length < 2 && !state.langs.length) return null
  const rows: LanguageFacet[] = [
    ...facets.languages,
    ...state.langs.filter((k) => !facets.languages.some((l) => l.key === k)).map((k) => ({ key: k, count: 0 })),
  ]
  return (
    <RailPanel title={t('news.rail.languages')}>
      {rows.map((l) => (
        <FacetRow key={l.key} label={langName(l.key, true)} count={l.count} active={state.langs.includes(l.key)}
          onClick={() => toggle(l.key)} title={t('news.f.filterBy', { x: langName(l.key, true) })} />
      ))}
    </RailPanel>
  )
}

/** The news feeds: results per feed (from the facets) and each feed's freshness and last check. */
export function SourcesRail({ sources, facets, state, toggle }: {
  sources: SourceInfo[]; facets: NewsFacets | undefined; state: NewsFilterState; toggle: (k: string) => void
}) {
  const { t, lang } = useI18n()
  const [open, setOpen] = useState(false)
  const counts = new Map((facets?.sources ?? []).map((s) => [s.key, s.count]))
  const rows = [...sources].sort((a, b) =>
    (counts.get(b.key) ?? 0) - (counts.get(a.key) ?? 0)
    || Number(b.enabled) - Number(a.enabled)
    || a.name.localeCompare(b.name))
  const shown = open ? rows : rows.filter((s, i) => i < SOURCES_COLLAPSED || state.sources.includes(s.key))

  return (
    <RailPanel
      title={t('news.rail.sources')}
      sub={t('news.rail.sourcesSub')}
      footer={(
        <Link to="/fonti" className="inline-flex items-center gap-1.5 text-[0.88rem] text-forest-700 hover:underline">
          {t('news.rail.manage')} <ArrowRight size={14} />
        </Link>
      )}
    >
      <ul>
        {shown.map((s) => {
          const n = counts.get(s.key) ?? 0
          const active = state.sources.includes(s.key)
          const problem = s.last_run_status === 'failed' || s.last_run_status === 'offline'
          return (
            <li key={s.key} className={clsx('group flex items-start gap-2 px-4 py-2', active ? 'bg-forest-50' : 'hover:bg-paper')}>
              <button type="button" className="min-w-0 flex-1 text-left" onClick={() => toggle(s.key)} aria-pressed={active} title={t('news.rail.onlyThis')}>
                <span className={clsx('line-clamp-2 text-[0.88rem] leading-snug', active ? 'font-medium text-forest-900' : s.enabled ? 'text-charcoal-soft' : 'text-muted')}>
                  {s.name}
                </span>
                <span className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[0.76rem] text-muted">
                  {s.enabled ? <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} /> : <span className="uppercase tracking-wide">{t('news.rail.disabled')}</span>}
                  {problem && (
                    <span className="inline-flex items-center gap-1 text-down" title={t('news.rail.sourceStatus', { s: t(`status.${s.last_run_status}`) })}>
                      <AlertTriangle size={12} /> {t(`status.${s.last_run_status}`)}
                    </span>
                  )}
                  <span>{s.last_run_at ? t('news.rail.lastCheck', { ago: fmtAgo(utc(s.last_run_at), lang) }) : t('news.rail.neverChecked')}</span>
                </span>
              </button>
              <span className={clsx('num pt-[1px] text-[0.84rem]', n ? 'text-charcoal-soft' : 'text-line')}>{fmtNumber(n, lang)}</span>
              <Link to={`/fonti#${encodeURIComponent(s.key)}`} className="pt-[2px] text-muted opacity-0 hover:text-forest-700 focus:opacity-100 group-hover:opacity-100"
                title={t('news.rail.openSource')} aria-label={t('news.rail.openSource')}>
                <ChevronRight size={15} />
              </Link>
            </li>
          )
        })}
      </ul>
      {rows.length > SOURCES_COLLAPSED && (
        <ShowMore open={open} n={rows.length} onClick={() => setOpen((v) => !v)} labelAll={t('news.rail.showAllSources', { n: rows.length })} />
      )}
    </RailPanel>
  )
}
