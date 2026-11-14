// Honey companies found on the web (owner's request, 15 Nov 2026: "the business part per each
// country, the first Google results, no need for them to update"). A fixed list written once from
// web searches (backend/paladex/reference/companies_web.py): the company's name, what it does with
// honey and its own website. Always shown apart from the official lists and labelled
// "Non ufficiale", with the search date; alphabetical, never a ranking.
import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { Badge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { isMirrorMissing } from '@/lib/mirror'
import type { CompaniesCountry, WebCompanies as WebData, WebCompany } from './types'

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function Item({ c }: { c: WebCompany }) {
  const { t, lang } = useI18n()
  const what = lang === 'en' ? c.what_en ?? c.what_it : c.what_it ?? c.what_en
  return (
    <li className="border-b border-line-soft py-3 last:border-0" data-web-company={c.name}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <span className="text-[1.05rem] font-semibold text-charcoal">{c.name}</span>
          <span className="ml-2 text-[0.88rem] text-muted">{[t(`companies.web.role.${c.role}`), c.city].filter(Boolean).join(' · ')}</span>
        </div>
        <a href={c.website} target="_blank" rel="noreferrer" className="link inline-flex shrink-0 items-center gap-1 text-[0.92rem]">
          {host(c.website)} <ExternalLink size={13} aria-hidden />
        </a>
      </div>
      {what && <p className="mt-0.5 text-[0.95rem] leading-snug text-charcoal-soft">{what}</p>}
    </li>
  )
}

/** The panel: nothing at all for a country without web companies. */
export function WebCompaniesPanel({ web, className }: { web: WebData | null | undefined; className?: string }) {
  const { t, lang } = useI18n()
  if (!web || web.companies.length === 0) return null
  return (
    <section className={`panel ${className ?? ''}`} data-web-companies={web.companies.length}>
      <div className="px-4 pb-1 pt-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-2.5">
          <h2 className="font-serif text-[1.35rem] font-semibold leading-tight text-forest-900">{t('companies.web.title')}</h2>
          <Badge tone="outline">{t('companies.web.badge')}</Badge>
        </div>
        <p className="mt-1 text-[0.92rem] leading-snug text-muted">
          {t('companies.web.note', { d: web.searched_on ? fmtDate(web.searched_on, lang, { day: 'numeric', month: 'long', year: 'numeric' }) : '—' })}
        </p>
      </div>
      <ul className="px-4 pb-2 sm:px-6">{web.companies.map((c) => <Item key={`${c.name}-${c.website}`} c={c} />)}</ul>
    </section>
  )
}

/** On a country page: asks for the country's companies and shows the web list when there is one. */
export function CountryWebCompanies({ iso3, className }: { iso3: string; className?: string }) {
  const q = useQuery({
    queryKey: ['companies', iso3],
    queryFn: () => api.get<CompaniesCountry>(`/companies/${encodeURIComponent(iso3)}`),
    retry: (n, e) => !isMirrorMissing(e) && n < 2,
  })
  return <WebCompaniesPanel web={q.data?.web} className={className} />
}
