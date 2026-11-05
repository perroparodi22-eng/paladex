// Comparison of 2-6 quotes ranked by landed cost (EUR/kg), with the difference to the cheapest per
// kg, in %, and per container. "Prudente" counts a quote with a tariff quota at the out-of-quota
// duty (the quota may run out), "migliore" at its lowest available alternative.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Trophy } from 'lucide-react'
import { DemoBadge, ErrorBlock, Loading, Note, Segmented } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtNumber, fmtPct } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { Drawer } from './Drawer'
import { useQuoteLabels } from './labels'
import { QuotePrice } from './QuoteTable'
import type { CompareBasis, CompareResponse, FxMode } from './types'
import { fmtAmount, fmtPerKg, fmtTons } from './utils'

export function CompareView({ ids, basis, fx, onBasis, onFx, onClose, onOpen }: {
  ids: number[]
  basis: CompareBasis
  fx: FxMode
  onBasis: (b: CompareBasis) => void
  onFx: (v: FxMode) => void
  onClose: () => void
  onOpen: (id: number) => void
}) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  const labels = useQuoteLabels()
  const enough = ids.length >= 2
  const q = useQuery({
    queryKey: ['quotes', 'compare', ids, basis, fx],
    queryFn: () => api.get<CompareResponse>('/quotes/compare', { ids: ids.join(','), basis, fx }),
    enabled: enough,
    placeholderData: keepPreviousData,
  })
  const d = q.data
  return (
    <Drawer open onClose={onClose} labelId="quote-compare-title" size="xl" eyebrow={t('quotes.compare.eyebrow')}
      title={t('quotes.compare.title', { n: ids.length })} meta={t('quotes.compare.subtitle')}>
      <div className="mb-4 flex flex-wrap items-end gap-x-6 gap-y-3">
        <div>
          <span className="label">{t('quotes.compare.basis')}</span>
          <Segmented<CompareBasis> value={basis} onChange={onBasis}
            options={[{ value: 'conservative', label: t('quotes.compare.conservative') }, { value: 'best', label: t('quotes.compare.best') }]} />
        </div>
        <div>
          <span className="label">{t('quotes.fx.label')}</span>
          <Segmented<FxMode> value={fx} onChange={onFx}
            options={[{ value: 'received', label: t('quotes.fx.received') }, { value: 'today', label: t('quotes.fx.today') }]} />
        </div>
      </div>
      <p className="mb-4 max-w-4xl text-[0.9rem] text-muted">{t(basis === 'conservative' ? 'quotes.compare.conservativeHint' : 'quotes.compare.bestHint')}</p>

      {!enough ? <Note>{t('quotes.compare.needTwo')}</Note> : q.isLoading ? <Loading /> : q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} /> : d && (
        <>
          <div className="mb-4 space-y-2">
            {d.mixed_destinations && <Note tone="warn">{t('quotes.compare.mixedDest')}</Note>}
            {d.incomplete.length > 0 && (
              <Note tone="warn">
                {t(d.incomplete.length === 1 ? 'quotes.compare.incomplete1' : 'quotes.compare.incompleteN', {
                  n: d.incomplete.length,
                  names: d.items.filter((x) => d.incomplete.includes(x.quote.id)).map((x) => x.quote.supplier_name).join(', '),
                })}
              </Note>
            )}
            {d.mixed_demo && <Note tone="warn">{t('quotes.compare.mixedDemo')}</Note>}
          </div>
          <ol className="space-y-2 sm:hidden">
            {d.items.map((x) => {
              const best = x.quote.id === d.best_id
              const jurisdiction = x.quote.destination === 'USA' ? 'US' : 'EU'
              return (
                <li key={x.quote.id} className={clsx('cursor-pointer rounded-sm border border-line bg-white px-3 py-2.5', best && 'border-forest-300 bg-forest-50/80')}
                  onClick={() => onOpen(x.quote.id)}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="num text-muted">{x.rank ?? '—'}.</span>
                        {best && <Trophy size={14} className="text-gold" aria-label={t('quotes.compare.cheapest')} />}
                        <button type="button" className="min-w-0 break-words text-left font-medium text-charcoal"
                          onClick={(e) => { e.stopPropagation(); onOpen(x.quote.id) }}>{x.quote.supplier_name}</button>
                      </div>
                      <div className="text-[0.84rem] text-muted">
                        {x.quote.is_demo && <DemoBadge />} {country(x.quote.origin_iso3)} · {variety(x.quote.variety)} · {x.quote.incoterm ?? t('quotes.notGiven')}
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="num whitespace-nowrap text-[1.05rem] text-charcoal">{fmtPerKg(x.value_eur_per_kg, 'EUR', lang)}</div>
                      <div className="num whitespace-nowrap text-[0.8rem] text-muted">{fmtPerKg(x.value_usd_per_kg, 'USD', lang)}</div>
                    </div>
                  </div>
                  <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3 text-[0.84rem]">
                    <span className="text-muted">
                      {x.scenario ? <>{labels.scenario({ kind: x.scenario.kind, role: x.scenario.kind === 'trq_in' ? 'in_quota' : x.landed.headline.alternatives ? 'out_of_quota' : 'applicable', rate: x.scenario.rate, quota: x.scenario.quota }, jurisdiction)} <span className="num">{labels.rate(x.scenario.rate)}</span></> : '—'}
                    </span>
                    <span className="num whitespace-nowrap">
                      {best || x.diff_eur_per_kg === null ? <span className="font-sans text-muted">{best ? t('quotes.compare.reference') : '—'}</span>
                        : <>+{fmtPerKg(x.diff_eur_per_kg, 'EUR', lang)} ({fmtPct(x.diff_pct, lang, 1)})</>}
                    </span>
                  </div>
                  {!best && x.diff_eur_per_container !== null && (
                    <div className="num text-right text-[0.8rem] text-muted">+{fmtAmount(x.diff_eur_per_container, 'EUR', lang, 0)} / {t('quotes.compare.perContainerShort', { t: fmtTons(d.container_kg, lang) })}</div>
                  )}
                  {d.incomplete.includes(x.quote.id) && <div className="text-[0.8rem] text-warn">{t('quotes.list.incomplete')}</div>}
                  {x.landed.headline.warnings.some((w) => w === 'us_antidumping' || w === 'us_additional_duty_review') && (
                    <div className="text-[0.8rem] text-down">{t('quotes.compare.warnings')}</div>
                  )}
                  {x.landed.headline.warnings.includes('quota_unavailable') && <div className="text-[0.8rem] text-down">{t('quotes.list.quotaOut')}</div>}
                </li>
              )
            })}
          </ol>
          <div className="relative hidden overflow-x-auto rounded-sm border border-line bg-white sm:block">
            <table className="table-clean min-w-[960px]">
              <thead>
                <tr>
                  <th className="w-12 text-right">#</th>
                  <th>{t('quotes.list.supplier')}</th>
                  <th>{t('quotes.list.origin')}</th>
                  <th className="text-right">{t('quotes.list.price')}</th>
                  <th>{t('quotes.compare.dutyUsed')}</th>
                  <th className="text-right">{t('quotes.compare.landedEur')}</th>
                  <th className="text-right">{t('quotes.compare.diffKg')}</th>
                  <th className="text-right">{t('quotes.compare.diffContainer', { t: fmtTons(d.container_kg, lang) })}</th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((x) => {
                  const best = x.quote.id === d.best_id
                  const incomplete = d.incomplete.includes(x.quote.id)
                  const jurisdiction = x.quote.destination === 'USA' ? 'US' : 'EU'
                  return (
                    <tr key={x.quote.id} className={clsx('cursor-pointer', best && 'bg-forest-50/80')} onClick={() => onOpen(x.quote.id)}>
                      <td className="num text-right">
                        {x.rank ?? '—'}
                        {best && <Trophy size={14} className="ml-1 inline text-gold" aria-label={t('quotes.compare.cheapest')} />}
                      </td>
                      <td className="min-w-[12rem]">
                        <button type="button" className="text-left font-medium text-charcoal hover:text-forest-700"
                          onClick={(e) => { e.stopPropagation(); onOpen(x.quote.id) }}>{x.quote.supplier_name}</button>
                        <div className="mt-0.5 flex flex-wrap gap-1.5 text-[0.8rem] text-muted">
                          {x.quote.is_demo && <DemoBadge />}
                          <span>{x.quote.incoterm ?? t('quotes.notGiven')}{x.quote.incoterm_place ? ` ${x.quote.incoterm_place}` : ''}</span>
                          <span>· {t(`quotes.dest.short.${x.quote.destination}`)}</span>
                        </div>
                        {incomplete && <div className="text-[0.8rem] text-warn">{t('quotes.list.incomplete')}</div>}
                      </td>
                      <td>
                        <div>{country(x.quote.origin_iso3)}</div>
                        <div className="text-[0.84rem] text-muted">{variety(x.quote.variety)}</div>
                      </td>
                      <td className="text-right"><QuotePrice q={x.quote} /></td>
                      <td className="text-[0.88rem]">
                        {x.scenario ? (
                          <>
                            <div>{labels.scenario({ kind: x.scenario.kind, role: x.scenario.kind === 'trq_in' ? 'in_quota' : x.landed.headline.alternatives ? 'out_of_quota' : 'applicable', rate: x.scenario.rate, quota: x.scenario.quota }, jurisdiction)}</div>
                            <div className="num text-muted">{labels.rate(x.scenario.rate)}</div>
                          </>
                        ) : <span className="text-muted">—</span>}
                        {x.landed.headline.warnings.some((w) => w === 'us_antidumping' || w === 'us_additional_duty_review') && (
                          <div className="text-[0.8rem] text-down">{t('quotes.compare.warnings')}</div>
                        )}
                        {x.landed.headline.warnings.includes('quota_unavailable') && (
                          <div className="text-[0.8rem] text-down">{t('quotes.list.quotaOut')}</div>
                        )}
                      </td>
                      <td className="text-right">
                        <div className="num whitespace-nowrap text-[1.02rem] text-charcoal">{fmtPerKg(x.value_eur_per_kg, 'EUR', lang)}</div>
                        <div className="num whitespace-nowrap text-[0.82rem] text-muted">{fmtPerKg(x.value_usd_per_kg, 'USD', lang)}</div>
                      </td>
                      <td className="text-right">
                        {x.diff_eur_per_kg === null || best ? <span className="text-[0.88rem] text-muted">{best ? t('quotes.compare.reference') : '—'}</span> : (
                          <>
                            <div className="num whitespace-nowrap">+{fmtPerKg(x.diff_eur_per_kg, 'EUR', lang)}</div>
                            <div className="num whitespace-nowrap text-[0.82rem] text-muted">{fmtPct(x.diff_pct, lang, 1)}</div>
                          </>
                        )}
                      </td>
                      <td className="num whitespace-nowrap text-right">{x.diff_eur_per_container === null || best ? '—' : `+${fmtAmount(x.diff_eur_per_container, 'EUR', lang, 0)}`}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[0.84rem] text-muted">
            {t('quotes.compare.footer', { drum: fmtNumber(d.drum_kg, lang), container: fmtTons(d.container_kg, lang) })}
          </p>
        </>
      )}
    </Drawer>
  )
}
