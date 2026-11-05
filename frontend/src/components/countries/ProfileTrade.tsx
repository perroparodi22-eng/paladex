// Profile · Export / Import: the country's own declared totals over time, its top partners, and —
// kept apart, never added — what its partner countries declare (mirror data).
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { DemoBadge, Panel, Segmented, SourceLine } from '@/components/ui'
import { BasisMarks, DataMissing, fmtT, fmtUv, nameOf, ShareBar, YoY } from '@/components/trade/bits'
import { SeriesChart } from '@/components/trade/SeriesChart'
import type { TradeFlow } from '@/components/trade/types'
import { useI18n } from '@/i18n'
import { fmtPct } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { countryName } from './parts'
import type { CountryProfile, TradeFlowSection } from './types'

export function ProfileTrade({ p }: { p: CountryProfile }) {
  const { t } = useI18n()
  const exp = p.trade.export
  const imp = p.trade.import
  const has = (s: TradeFlowSection) => s.available || s.mirror !== null
  const [flow, setFlow] = useState<TradeFlow>(has(exp) || !has(imp) ? 'export' : 'import')
  const s = flow === 'export' ? exp : imp
  const anyDemo = s.series.some((x) => x.is_demo) || Boolean(s.mirror?.rows.some((r) => r.is_demo)) || Boolean(s.partners?.is_demo)
  return (
    <Panel
      title={t('countries.trade.title')}
      eyebrow={t('countries.trade.eyebrow')}
      actions={
        <>
          {anyDemo && <DemoBadge />}
          <Segmented size="sm" value={flow} onChange={setFlow} options={[
            { value: 'export', label: t('countries.trade.export') },
            { value: 'import', label: t('countries.trade.import') },
          ]} />
        </>
      }
      footer={<Link to="/commercio" className="link">{t('countries.trade.goto')} →</Link>}
    >
      <FlowView p={p} s={s} flow={flow} />
    </Panel>
  )
}

function FlowView({ p, s, flow }: { p: CountryProfile; s: TradeFlowSection; flow: TradeFlow }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const name = countryName(p.country, lang)
  const partners = s.partners
  const providers = (flow === 'import' ? p.trade.providers_import : undefined) ?? p.trade.providers
  return (
    <div className="flex flex-col gap-6">
      {!s.available ? (
        <DataMissing compact what={t('countries.trade.noDeclared')} providers={providers} fallback={t('countries.trade.fallback')} />
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="min-w-0">
            <div className="eyebrow mb-1">{t('countries.trade.seriesTitle')}</div>
            <SeriesChart height={240} data={{
              reporter: p.country.iso3, partner: 'WLD', flow, freq: 'A',
              reporter_names: { name_it: p.country.name_it, name_en: p.country.name_en }, partner_names: { name_it: null, name_en: null },
              available: true, series: s.series, excluded_partial: s.excluded_partial, discrepancies: s.discrepancies, providers,
            }} />
          </div>
          <div className="min-w-0 xl:border-l xl:border-line-soft xl:pl-6">
            {partners ? (
              <>
                <div className="flex items-baseline justify-between gap-2 mb-1">
                  <span className="eyebrow">{t(flow === 'export' ? 'countries.trade.partnersTitle' : 'countries.trade.partnersTitleImp', { y: partners.year ?? '' })}</span>
                  {partners.total && (
                    <span className="num text-[0.9rem] text-charcoal">
                      {fmtT(partners.total.net_weight_kg, lang)} t
                      <BasisMarks summedPartners={partners.total.summed_from_partners} partners={partners.total.partners_count} />
                      <YoY pct={partners.total.yoy_volume_pct} className="ml-2 text-[0.82rem]" />
                    </span>
                  )}
                </div>
                <div className="relative overflow-x-auto">
                <table className="w-full min-w-[20rem] text-[0.92rem]">
                  <thead>
                    <tr className="border-b border-line bg-paper text-left text-[0.7rem] uppercase tracking-wider text-muted">
                      <th className="py-1.5 px-2 font-medium">{flow === 'export' ? t('trade.flows.col.destination') : t('trade.flows.col.origin')}</th>
                      <th className="py-1.5 px-2 font-medium text-right">t</th>
                      <th className="py-1.5 px-2 font-medium w-[34%]">{t('trade.flows.col.share')}</th>
                      <th className="py-1.5 px-2 font-medium text-right">{t('trade.leaders.col.uv')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {partners.rows.map((r) => (
                      <tr key={r.iso3} className="border-b border-line-soft">
                        <td className="py-1.5 px-2">
                          {r.link ? <Link className="hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2" to={r.link}>{nameOf(r, lang, country)}</Link> : nameOf(r, lang, country)}
                        </td>
                        <td className="py-1.5 px-2 num text-right">{fmtT(r.net_weight_kg, lang)}</td>
                        <td className="py-1.5 px-2">
                          <div className="flex items-center gap-2"><ShareBar pct={r.share_volume_pct} className="flex-1" /><span className="num text-[0.82rem] w-[3.2rem] text-right">{fmtPct(r.share_volume_pct, lang, 1, false)}</span></div>
                        </td>
                        <td className="py-1.5 px-2 num text-right text-charcoal-soft">{fmtUv(r.unit_value_usd_per_kg, lang)}</td>
                      </tr>
                    ))}
                    {partners.others && (
                      <tr className="border-b border-line-soft text-charcoal-soft">
                        <td className="py-1.5 px-2 italic">{partners.others.count === 1 ? t('trade.flows.othersOne') : t('trade.flows.others', { n: partners.others.count })}</td>
                        <td className="py-1.5 px-2 num text-right">{fmtT(partners.others.net_weight_kg, lang)}</td>
                        <td className="py-1.5 px-2"><span className="num text-[0.82rem]">{fmtPct(partners.others.share_volume_pct, lang, 1, false)}</span></td>
                        <td />
                      </tr>
                    )}
                  </tbody>
                </table>
                </div>
                <div className="mt-2">
                  <SourceLine p={{ source: partners.source ?? null, published_at: partners.published_at, source_url: partners.source_url, is_demo: partners.is_demo, period_label: partners.period_label ?? undefined }} />
                  {partners.share_basis && <div className="text-[0.78rem] text-muted mt-0.5">{t(`trade.flows.shareBasis.${partners.share_basis}`)}</div>}
                </div>
              </>
            ) : (
              <DataMissing compact what={t('trade.flows.onlyTotal')} providers={providers} fallback={t('countries.trade.fallback')} />
            )}
          </div>
        </div>
      )}

      {s.mirror && (
        <div className="rounded-sm border border-dashed border-gold-light/70 bg-gold-pale/20 px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-serif text-[1.02rem] font-semibold text-charcoal">{t('countries.trade.mirrorTitle')}</span>
            <span className="text-[0.8rem] text-muted max-w-2xl">{t(flow === 'export' ? 'countries.trade.mirrorHintExp' : 'countries.trade.mirrorHintImp', { c: name })}</span>
          </div>
          <div className="relative overflow-x-auto mt-2">
          <table className="w-full min-w-[20rem] text-[0.92rem]">
            <thead>
              <tr className="border-b border-line text-left text-[0.7rem] uppercase tracking-wider text-muted">
                <th className="py-1.5 px-2 font-medium">{t('countries.trade.col.declaredBy')}</th>
                <th className="py-1.5 px-2 font-medium">{t('countries.trade.col.year')}</th>
                <th className="py-1.5 px-2 font-medium text-right">t</th>
                <th className="py-1.5 px-2 font-medium text-right">{t('trade.leaders.col.uv')}</th>
                <th className="py-1.5 px-2 font-medium">{t('prov.source')}</th>
              </tr>
            </thead>
            <tbody>
              {s.mirror.rows.map((r) => (
                <tr key={r.iso3} className="border-b border-line-soft last:border-0">
                  <td className="py-1.5 px-2"><Link to={r.link} className="hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2">{nameOf(r, lang, country)}</Link></td>
                  <td className="py-1.5 px-2 num">{r.year}{!r.complete && r.months_count ? <span className="text-muted text-[0.78rem]"> ({r.months_count}/12)</span> : null}
                    <BasisMarks summedMonths={r.summed_from_months && r.complete} /></td>
                  <td className="py-1.5 px-2 num text-right">{fmtT(r.net_weight_kg, lang)}</td>
                  <td className="py-1.5 px-2 num text-right text-charcoal-soft">{fmtUv(r.unit_value_usd_per_kg, lang)}</td>
                  <td className="py-1.5 px-2 text-[0.82rem] text-muted">
                    {r.is_demo && <span className="mr-1"><DemoBadge /></span>}{r.source?.publisher || r.source?.name}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  )
}
