// The "Aziende" block of a country profile: what the country's authorities publish about honey
// exporters and importers, the top entries when there are official figures, and a link to /aziende.
import { useQuery } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ErrorBlock, Loading, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtNumber, fmtPeriod } from '@/lib/format'
import { isMirrorMissing } from '@/lib/mirror'
import { AvailabilityNote, FigureValue, ListSource } from './parts'
import type { CompaniesCountry, FiguresList, RegisterList } from './types'

export const BLOCK_TOP = 5

export function CountryCompaniesBlock({ iso3 }: { iso3: string }) {
  const q = useQuery({
    queryKey: ['companies', iso3],
    queryFn: () => api.get<CompaniesCountry>(`/companies/${encodeURIComponent(iso3)}`),
    retry: (n, e) => !isMirrorMissing(e) && n < 2,
  })
  if (q.isLoading) return <Loading />
  if (q.error) return isMirrorMissing(q.error) ? null : <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
  if (!q.data) return null
  return <CountryCompaniesBody d={q.data} />
}

export function CountryCompaniesBody({ d }: { d: CompaniesCountry }) {
  const { t, lang } = useI18n()
  const figures = d.lists.filter((l): l is FiguresList => l.measure_kind !== 'none')
  const register = d.lists.filter((l): l is RegisterList => l.measure_kind === 'none')
  const imp = register.find((l) => l.role === 'importer')
  const exp = register.find((l) => l.role === 'exporter')
  const span = (l: RegisterList) => ({ a: fmtPeriod(l.first_period, lang), b: fmtPeriod(l.latest_period, lang) })
  return (
    <Panel
      title={t('companies.block.title')}
      eyebrow={t('companies.block.eyebrow')}
      actions={
        <Link to={`/aziende?paese=${d.country.iso3}`} className="inline-flex items-center gap-1 text-sm text-forest-700 hover:text-forest-900">
          {t('companies.block.open')} <ArrowRight size={14} />
        </Link>
      }
    >
      <div className="flex flex-col gap-4">
        <AvailabilityNote a={d.availability} compact />
        {figures.map((l) => (
          <section key={`${l.role}-${l.source?.key}`}>
            <h3 className="font-serif text-[1.02rem] font-semibold mb-1">{t('companies.block.top', { y: l.ref_period ?? '' })}</h3>
            <ol className="flex flex-col divide-y divide-line-soft">
              {l.companies.filter((c) => c.rank_in_ref !== null).slice(0, BLOCK_TOP).map((c) => (
                <li key={c.name} className="flex items-baseline justify-between gap-3 py-1.5">
                  <span><span className="num text-muted mr-2">{c.rank_in_ref}</span>{c.name}</span>
                  <span className="num whitespace-nowrap">
                    {l.ref_period && <FigureValue cell={c.values[l.ref_period]} currency={l.currency} lang={lang} />} {l.currency}
                    {l.ref_period && c.values[l.ref_period]?.share_pct !== undefined && (
                      <span className="text-muted ml-2">{fmtNumber(c.values[l.ref_period].share_pct, lang, 1)}%</span>
                    )}
                  </span>
                </li>
              ))}
            </ol>
            <div className="mt-2"><ListSource list={l} /></div>
          </section>
        ))}
        {register.length > 0 && (
          <section className="flex flex-col gap-2">
            <p>
              {imp && exp ? t('companies.block.register', { n: imp.company_count, m: exp.company_count, ...span(imp) })
                : imp ? t('companies.block.registerImp', { n: imp.company_count, ...span(imp) })
                  : exp ? t('companies.block.registerExp', { n: exp.company_count, ...span(exp) }) : ''}
            </p>
            <p className="text-[0.85rem] text-muted">{t('companies.what.none')}</p>
            <ListSource list={register[0]} />
          </section>
        )}
        {d.lists.length === 0 && ['figures', 'register'].includes(d.availability.status) && (
          <p className="text-muted">{t('companies.noRows')}</p>
        )}
      </div>
    </Panel>
  )
}
