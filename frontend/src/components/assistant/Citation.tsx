// Citation chip [n]: opens the fact's source (original document, else the page of this app);
// on hover (desktop) a small card shows source, publication date, period and status.
import clsx from 'clsx'
import { Link } from 'react-router-dom'
import { useI18n } from '@/i18n'
import { fmtDate, fmtPeriod } from '@/lib/format'
import type { AssistantFact } from './types'
import { pageUrl } from '@/lib/links'

export function citationTitle(f: AssistantFact, t: (k: string, v?: Record<string, string | number>) => string, lang: 'it' | 'en'): string {
  const parts = [f.private ? t('assistant.cite.private') : f.source_name || t('assistant.cite.noSource')]
  if (f.published_at) parts.push(t('assistant.cite.published', { date: fmtDate(f.published_at, lang) }))
  if (f.period_label && f.kind !== 'news') parts.push(t('assistant.cite.period', { p: fmtPeriod(f.period_label, lang) }))
  parts.push(f.status_label)
  return parts.join(' · ')
}

const STATUS_DOT: Record<string, string> = {
  verified_official: 'bg-forest-600', verified_industry: 'bg-gold', provisional: 'bg-warn', estimate: 'bg-warn',
  historical: 'bg-muted', press: 'bg-line', user: 'bg-gold-dark', corrected: 'bg-[#24507A]',
}

export function Citation({ fact }: { fact: AssistantFact }) {
  const { t, lang } = useI18n()
  const title = citationTitle(fact, t, lang)
  const chip = 'inline-flex items-center rounded-sm border border-line bg-paper px-1 font-mono text-[0.72rem] leading-[1.35] text-forest-800 hover:border-forest-600 hover:bg-forest-50'
  const label = <span className={chip}>{fact.id}</span>
  const external = fact.url && !fact.private
  return (
    <span className="group relative inline-block align-baseline">
      {external ? (
        <a href={pageUrl(fact.url!) ?? undefined} target="_blank" rel="noreferrer" title={title} aria-label={`[${fact.id}] ${title}`}>{label}</a>
      ) : fact.link ? (
        <Link to={fact.link} title={title} aria-label={`[${fact.id}] ${title}`}>{label}</Link>
      ) : (
        <span title={title}>{label}</span>
      )}
      {/* Hover card: desktop only (a touch screen opens the source directly). */}
      <span role="tooltip" className="pointer-events-none absolute left-0 top-full z-30 mt-1 hidden w-72 rounded-sm border border-line bg-white p-2.5 text-left text-[0.8rem] leading-snug text-charcoal-soft shadow-lg md:group-hover:block">
        <span className="flex items-center gap-1.5 font-medium text-charcoal">
          <span className={clsx('inline-block h-1.5 w-1.5 shrink-0 rounded-full', STATUS_DOT[fact.status] ?? 'bg-muted')} />
          {fact.private ? t('assistant.cite.private') : fact.source_name || t('assistant.cite.noSource')}
        </span>
        <span className="mt-1 block text-muted">{fact.title}</span>
        <span className="mt-1 block text-muted">
          {[fact.published_at && t('assistant.cite.published', { date: fmtDate(fact.published_at, lang) }),
            fact.period_label && fact.kind !== 'news' && t('assistant.cite.period', { p: fmtPeriod(fact.period_label, lang) })]
            .filter(Boolean).join(' · ')}
        </span>
        <span className="mt-1 block text-[0.74rem] uppercase tracking-wide text-forest-700">{fact.status_label}</span>
      </span>
    </span>
  )
}

/** The chips of one sentence: "[2] [5]". */
export function Citations({ refs, facts }: { refs: number[]; facts: Map<number, AssistantFact> }) {
  const known = refs.map((r) => facts.get(r)).filter((f): f is AssistantFact => Boolean(f))
  if (!known.length) return null
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-baseline">
      {known.map((f) => <Citation key={f.id} fact={f} />)}
    </span>
  )
}
