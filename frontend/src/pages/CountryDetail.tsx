// /paesi/:iso3 — country profile: what we know about one honey country, every figure with its
// source, and an explicit list of what we do not know yet.
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Star } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { Badge, DemoBadge, EmptyState, ErrorBlock, Loading, PageHeader, Panel, StatTile, StatusBadge } from '@/components/ui'
import { CountryCompaniesBlock } from '@/components/companies/CountryCompanies'
import { CountryWebCompanies } from '@/components/companies/WebCompanies'
import { AvailabilityChips, countryName, useRegion } from '@/components/countries/parts'
import { ProfileProduction, useNextRelease } from '@/components/countries/ProfileProduction'
import { CountryPricesSimple } from '@/components/countries/CountryPrices'
import { ProfileContext, ProfileMissing, ProfileNews, ProfilePrices, ProfileRegulations } from '@/components/countries/ProfileSections'
import { ProfileTrade } from '@/components/countries/ProfileTrade'
import { useYtdTitle } from '@/components/countries/ProfileYtd'
import type { CountryProfile, TradeFlowSection } from '@/components/countries/types'
import { ProfileWebFindings } from '@/components/findings/ProfileWebFindings'
import { fmtT, fmtUsd, SourcesFooter, useProviderText } from '@/components/trade/bits'
import { prevSpan } from '@/components/trade/ytd'
import { useI18n } from '@/i18n'
import { ApiError, api } from '@/lib/api'
import { fmtNumber } from '@/lib/format'
import { isMirrorMissing } from '@/lib/mirror'
import { useView } from '@/lib/view'
import { CorrectionBadge } from '@/components/corrections/CorrectionBadge'
import { FixValue } from '@/components/corrections/QuickFix'
import type { FigureRef } from '@/components/corrections/types'
import { CountryNotes } from '@/components/corrections/CorrectionsPanel'
import { Details } from '@/components/simple/Details'
import { CountryYtdPanel } from '@/components/simple/SimpleCountry'

export default function CountryDetail() {
  const { iso3 = '' } = useParams()
  const code = iso3.toUpperCase()
  const { t } = useI18n()
  const q = useQuery({
    queryKey: ['countries', code],
    queryFn: () => api.get<CountryProfile>(`/countries/${encodeURIComponent(code)}`),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && !isMirrorMissing(e) && n < 2,
  })

  const back = (
    <Link to="/paesi" className="inline-flex items-center gap-1.5 text-sm text-forest-700 hover:text-forest-900 mb-3">
      <ArrowLeft size={15} /> {t('countries.back')}
    </Link>
  )

  if (q.isLoading) return <div>{back}<Loading /></div>
  if (q.error instanceof ApiError && q.error.status === 404) {
    return <div>{back}<Panel><EmptyState title={t('countries.notFound')} hint={t('countries.notFoundHint', { c: code })} /></Panel></div>
  }
  if (q.error) return <div>{back}<ErrorBlock error={q.error} onRetry={() => q.refetch()} /></div>
  if (!q.data) return null
  // keyed by country: the export/import switch and the open details of one country never carry over to the next
  return <Profile key={q.data.country.iso3} p={q.data} back={back} />
}

function Profile({ p, back }: { p: CountryProfile; back: React.ReactNode }) {
  const { t, lang } = useI18n()
  const { simple } = useView()
  const region = useRegion()
  const c = p.country
  const header = (
    <PageHeader
      eyebrow={`${region(c.region)} · ${c.iso3}`}
      title={countryName(c, lang)}
      subtitle={simple ? undefined : <span className="block mt-2"><AvailabilityChips a={p.availability} /></span>}
      actions={
        <div className="flex items-center gap-2">
          {p.is_demo && <DemoBadge />}
          {c.priority && <Badge tone="gold"><Star size={11} /> {t('countries.priority')}</Badge>}
        </div>
      }
    />
  )
  if (simple) {
    // Simple view (lib/view.tsx): the headline figures, the year so far, production and the
    // unofficial sources; everything else one click away.
    return (
      <div data-view="simple">
        {back}
        {header}
        <KpiRow p={p} />
        <CountryPricesSimple p={p} className="mb-5" />
        <CountryWebCompanies iso3={c.iso3} className="mb-5" />
        <CountryYtdPanel p={p} name={countryName(c, lang)} />
        <ProfileNews p={p} compact className="mb-5 min-w-0" />
        <div className="mb-5"><ProfileProduction data={p.production} /></div>
        <div className="mb-5"><ProfileWebFindings p={p} /></div>
        <CountryNotes iso3={c.iso3} name={countryName(c, lang)} className="mb-5" />
        <Details hint={t('simple.country.detailsHint')}>
          <FullSections p={p} />
        </Details>
      </div>
    )
  }
  return (
    <div>
      {back}
      {header}

      <KpiRow p={p} />
      <ProfileMissing p={p} />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px] items-start mb-5">
        <ProfileProduction data={p.production} />
        <ProfileContext p={p} />
      </div>

      <div className="mb-5"><ProfileTrade p={p} /></div>
      <div className="mb-5"><CountryCompaniesBlock iso3={c.iso3} /></div>
      <CountryWebCompanies iso3={c.iso3} className="mb-5" />
      <div className="mb-5"><ProfilePrices p={p} /></div>
      <div className="mb-5"><ProfileWebFindings p={p} /></div>
      <CountryNotes iso3={c.iso3} name={countryName(c, lang)} className="mb-5" />

      <div className="grid gap-5 xl:grid-cols-2 items-start mb-5">
        <ProfileNews p={p} />
        <ProfileRegulations p={p} />
      </div>

      {p.sources.length > 0 && (
        <Panel title={t('countries.sourcesTitle')}>
          <SourcesFooter sources={p.sources} />
        </Panel>
      )}
    </div>
  )
}

/** Simple view's "Mostra dettagli": the sections the simple page leaves out, in the full order. */
function FullSections({ p }: { p: CountryProfile }) {
  const { t } = useI18n()
  return (
    <>
      <ProfileMissing p={p} />
      <div className="mb-5"><ProfileContext p={p} /></div>
      <div className="mb-5"><ProfileTrade p={p} /></div>
      <div className="mb-5"><CountryCompaniesBlock iso3={p.country.iso3} /></div>
      <div className="mb-5"><ProfilePrices p={p} /></div>
      <div className="grid gap-5 xl:grid-cols-2 items-start mb-5">
        <ProfileNews p={p} />
        <ProfileRegulations p={p} />
      </div>
      {p.sources.length > 0 && (
        <Panel title={t('countries.sourcesTitle')}>
          <SourcesFooter sources={p.sources} />
        </Panel>
      )}
    </>
  )
}

/** "anno 2024" plus a "Stima" / "Provvisorio" badge when the headline figure is not a published one. */
function YearSub({ year, status }: { year: string | number; status: string | null | undefined }) {
  const { t } = useI18n()
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-1">
      {t('countries.kpi.year', { y: year })}
      {status && !['published', 'live', 'demo'].includes(status) && <StatusBadge status={status} />}
    </span>
  )
}

export function KpiRow({ p }: { p: CountryProfile }) {
  const { t, lang } = useI18n()
  const providerText = useProviderText()
  const prodMetric = p.production.metrics.find((m) => m.metric === 'production')
  // One series per source (never merged): the headline shows the most recent year any source has
  // published (USA: NASS 2025 rather than FAOSTAT 2024); on a tie the backend's first source wins.
  const prodSeries = prodMetric?.series.reduce<(typeof prodMetric.series)[number] | undefined>(
    (best, s) => (!best || (s.latest.period_label ?? '') > (best.latest.period_label ?? '') ? s : best), undefined)
  const prod = prodSeries?.latest
  const nextRelease = useNextRelease()
  const prodNote = prodSeries ? nextRelease(prodSeries) : null

  const ytdTitle = useYtdTitle()
  const tradeTile = (s: TradeFlowSection, label: string, mirrorKey: string) => {
    const l = s.latest
    const y = s.ytd?.own
    if (y) {
      // The freshest period leads: the year so far against the same months of the year before (one
      // source); the last full year stays in the footer. Without weights (Uruguay), the value.
      const byValue = y.net_weight_kg === null && y.usd_value !== null
      return (
        <StatTile
          label={label}
          value={byValue ? fmtUsd(y.usd_value, lang) : <>{fmtT(y.net_weight_kg, lang)}<span className="text-muted text-[0.6em] ml-1">t</span></>}
          sub={
            <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-1">
              {ytdTitle(y)}
              {y.data_status && !['published', 'live', 'demo'].includes(y.data_status) && <StatusBadge status={y.data_status} />}
            </span>
          }
          delta={byValue ? y.change_value_pct : y.change_volume_pct}
          deltaLabel={y.comparable ? t('countries.ytd.vs', { p: prevSpan(y, lang) }) : undefined}
          demo={y.is_demo}
          footer={
            <div className="text-[0.78rem] text-muted">
              <div>{t('prov.source')}: {y.source?.publisher || y.source?.name}</div>
              {(y.correction || l?.correction) && <CorrectionBadge c={y.correction ?? l?.correction} compact className="my-1" />}
              {l && (
                <div>
                  {/* a country that publishes no weights (Uruguay): the value, never "— t" */}
                  {t('countries.kpi.fullYear', { y: l.year })}: <span className="num">{l.net_weight_kg === null && l.usd_value !== null ? fmtUsd(l.usd_value, lang) : `${fmtT(l.net_weight_kg, lang)} t`}</span>
                  {l.source?.key !== y.source?.key && <> ({l.source?.publisher || l.source?.name})</>}
                </div>
              )}
            </div>
          }
        />
      )
    }
    if (l) {
      const figure: FigureRef | null = l.row_id && !l.is_demo && l.net_weight_kg !== null ? {
        table: 'trade_flows', row_id: l.row_id, value: l.net_weight_kg, unit: 'kg', currency: null, field: 'net_weight_kg',
        label: `${label} · ${countryName(p.country, lang)} · ${l.year}`, country_iso3: p.country.iso3, period_label: String(l.year),
      } : null
      return (
        <StatTile
          label={label}
          value={l.net_weight_kg === null && l.usd_value !== null ? fmtUsd(l.usd_value, lang)
            : <FixValue figure={figure} correction={l.correction}><span>{fmtT(l.net_weight_kg, lang)}<span className="text-muted text-[0.6em] ml-1">t</span></span></FixValue>}
          sub={<YearSub year={`${l.year}${l.summed_from_partners ? ' · Σ' : ''}`} status={l.data_status} />}
          delta={l.net_weight_kg === null ? null : l.yoy_volume_pct}
          deltaLabel={l.prev ? `vs ${l.prev.year}` : undefined}
          demo={l.is_demo}
          footer={<>
            <span className="text-[0.78rem] text-muted">{t('prov.source')}: {l.source?.publisher || l.source?.name}</span>
            {l.correction && <CorrectionBadge c={l.correction} compact className="mt-1" />}
          </>}
        />
      )
    }
    return (
      <StatTile
        label={label}
        value={<span className="text-muted">—</span>}
        sub={s.mirror ? t(s.mirror.count === 1 ? `${mirrorKey}1` : mirrorKey, { n: s.mirror.count }) : t('ui.noData')}
        footer={<span className="text-[0.78rem] text-muted">{s.mirror ? t('countries.missing.partial') : t('countries.trade.noDeclared')}</span>}
      />
    )
  }

  return (
    <div className="grid gap-4 grid-cols-2 xl:grid-cols-4 mb-5">
      {prod && prodSeries ? (
        <StatTile
          label={t('countries.kpi.production')}
          value={<FixValue correction={prod.correction} figure={prod.row_id && !prod.is_demo ? {
            table: 'production_stats', row_id: prod.row_id, value: prod.value, unit: prod.unit, currency: null,
            label: `${t('countries.kpi.production')} · ${countryName(p.country, lang)} · ${prod.period_label}`,
            country_iso3: p.country.iso3, period_label: prod.period_label,
          } : null}><span>{fmtNumber(prod.value, lang, 0)}<span className="text-muted text-[0.6em] ml-1">{prod.unit}</span></span></FixValue>}
          sub={<>
            <YearSub year={prod.period_label ?? '—'} status={prod.data_status} />
            {prodNote && <div className="text-[0.78rem] leading-snug">{prodNote}</div>}
          </>}
          demo={prod.is_demo}
          footer={<>
            <span className="text-[0.78rem] text-muted">{t('prov.source')}: {prodSeries.source?.publisher || prodSeries.source?.name}</span>
            {prod.correction && <CorrectionBadge c={prod.correction} compact className="mt-1" />}
          </>}
        />
      ) : (
        <StatTile label={t('countries.kpi.production')} value={<span className="text-muted">—</span>} sub={t('ui.noData')}
          footer={<span className="text-[0.78rem] text-muted">{t('countries.missing.from', { s: providerText(p.production.providers, t('countries.prod.fallback'), 2) })}</span>} />
      )}
      {tradeTile(p.trade.export, t('countries.kpi.exports'), 'countries.kpi.mirror')}
      {tradeTile(p.trade.import, t('countries.kpi.imports'), 'countries.kpi.mirrorImp')}
      <StatTile
        label={t('countries.kpi.news')}
        value={p.news.available || p.news.count_30d ? fmtNumber(p.news.count_30d, lang) : <span className="text-muted">—</span>}
        sub={p.news.available || p.news.count_30d ? t(p.news.count_30d === 1 ? 'countries.kpi.newsSubOne' : 'countries.kpi.newsSub') : t('ui.noData')}
        demo={p.news.items.some((n) => n.is_demo)}
        footer={<Link to={p.news.link} className="text-[0.78rem] link">{t('countries.news.all')}</Link>}
      />
    </div>
  )
}
