// /aziende — honey exporters and importers by company, country by country, from official sources
// only. A country whose authorities publish nothing at company level says so, with the reason.
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Link, useSearchParams } from 'react-router-dom'
import { countryName } from '@/components/countries/parts'
import { AvailabilityBadge, AvailabilityNote, ListPanel } from '@/components/companies/parts'
import { WebCompaniesPanel } from '@/components/companies/WebCompanies'
import { STATUS_ORDER, type CompaniesCountry, type CompaniesOverview, type OverviewCountry } from '@/components/companies/types'
import { ErrorBlock, Loading, Note, PageHeader, Panel, QueryState } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { isMirrorMissing } from '@/lib/mirror'

export default function Companies() {
  const { t } = useI18n()
  const [params, setParams] = useSearchParams()
  const q = useQuery({ queryKey: ['companies'], queryFn: () => api.get<CompaniesOverview>('/companies') })
  return (
    <div>
      <PageHeader eyebrow={t('companies.eyebrow')} title={t('companies.title')} subtitle={t('companies.subtitle')} />
      <div className="mb-5"><Note>{t('companies.rule')}</Note></div>
      <QueryState q={q}>
        {(d) => {
          const wanted = (params.get('paese') ?? '').toUpperCase()
          const selected = d.countries.find((c) => c.iso3 === wanted) ?? d.countries[0]
          const pick = (iso3: string) => setParams((p) => { p.set('paese', iso3); return p }, { replace: true })
          return <CompaniesLayout d={d} selected={selected} onPick={pick} />
        }}
      </QueryState>
    </div>
  )
}

export function CompaniesLayout({ d, selected, onPick }: { d: CompaniesOverview; selected: OverviewCountry | undefined; onPick: (iso3: string) => void }) {
  const { t, lang } = useI18n()
  const sc = d.status_counts
  return (
    <div className="flex flex-col gap-5">
      <div className="lg:hidden">
        <label className="label" htmlFor="companies-country">{t('companies.pickCountry')}</label>
        <select id="companies-country" className="field" value={selected?.iso3 ?? ''} onChange={(e) => onPick(e.target.value)}>
          {STATUS_ORDER.map((s) => {
            const items = d.countries.filter((c) => c.status === s)
            if (!items.length) return null
            return (
              <optgroup key={s} label={t(`companies.status.${s}`)}>
                {items.map((c) => <option key={c.iso3} value={c.iso3}>{countryName(c, lang)}</option>)}
              </optgroup>
            )
          })}
        </select>
      </div>
      <div className="hidden lg:block">
        <Panel title={t('companies.countriesTitle')}
          eyebrow={t('companies.statusCounts', { a: sc.figures ?? 0, b: sc.register ?? 0, c: (sc.not_published ?? 0) + (sc.unavailable ?? 0), d: sc.unverified ?? 0 })}
          bodyClassName="!py-2">
          <nav aria-label={t('companies.countriesTitle')}>
            {STATUS_ORDER.map((s) => {
              const items = d.countries.filter((c) => c.status === s)
              if (!items.length) return null
              return (
                <div key={s} className="grid grid-cols-[220px_minmax(0,1fr)] gap-3 items-start border-b border-line-soft last:border-b-0 py-2">
                  <div className="pt-1"><AvailabilityBadge status={s} /></div>
                  <ul className="flex flex-wrap gap-1.5">
                    {items.map((c) => (
                      <li key={c.iso3}>
                        <Link to={`/aziende?paese=${c.iso3}`} aria-current={c.iso3 === selected?.iso3 ? 'page' : undefined}
                          className={clsx('inline-flex items-center gap-2 rounded-sm border px-2.5 py-1 text-[0.9rem]',
                            c.iso3 === selected?.iso3 ? 'border-forest-700 bg-forest-50 text-forest-900 font-medium'
                              : 'border-line text-charcoal-soft hover:border-forest-600 hover:text-forest-800')}>
                          <span>{countryName(c, lang)}</span>
                          <CountHint c={c} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              )
            })}
          </nav>
        </Panel>
      </div>
      <div className="min-w-0">{selected ? <CountryView iso3={selected.iso3} /> : null}</div>
    </div>
  )
}

function CountHint({ c }: { c: OverviewCountry }) {
  const { t } = useI18n()
  // Per role: a company can be on both lists, so the two counts are never added up.
  const parts = (['importer', 'exporter', 'registered_exporter'] as const)
    .filter((r) => c.companies[r])
    .map((r) => t(`companies.hint.${r}`, { n: c.companies[r] ?? 0 }))
  if (c.web_companies) parts.push(t('companies.hint.web', { n: c.web_companies }))
  if (!parts.length) return null
  return <span className="num text-[0.78rem] text-muted">{parts.join(' · ')}</span>
}

function CountryView({ iso3 }: { iso3: string }) {
  const q = useQuery({
    queryKey: ['companies', iso3],
    queryFn: () => api.get<CompaniesCountry>(`/companies/${encodeURIComponent(iso3)}`),
    retry: (n, e) => !isMirrorMissing(e) && n < 2,
  })
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
  if (!q.data) return null
  return <CountryBody d={q.data} />
}

export function CountryBody({ d }: { d: CompaniesCountry }) {
  const { t, lang } = useI18n()
  return (
    <div className="flex flex-col gap-5">
      <Panel title={countryName(d.country, lang)} eyebrow={d.country.iso3}
        actions={<Link to={`/paesi/${d.country.iso3}`} className="text-sm link">{t('nav.countries')}</Link>}>
        <AvailabilityNote a={d.availability} />
        {d.lists.length === 0 && ['figures', 'register'].includes(d.availability.status) && (
          <p className="mt-3 text-muted">{t('companies.noRows')}</p>
        )}
      </Panel>
      {d.lists.map((l) => <ListPanel key={`${l.role}-${l.source?.key}-${l.hs_code}`} list={l} />)}
      {d.lists.length > 0 && <p className="text-[0.85rem] text-muted">{t('companies.privacy')}</p>}
      <WebCompaniesPanel web={d.web} />
    </div>
  )
}
