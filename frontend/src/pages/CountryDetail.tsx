// /paesi/:iso3 — country profile: what we know about one honey country, every figure with its
// source, and an explicit list of what we do not know yet.
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Star } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { Badge, DemoBadge, EmptyState, ErrorBlock, Loading, PageHeader, Panel, StatTile } from '@/components/ui'
import { AvailabilityChips, countryName, useRegion } from '@/components/countries/parts'
import { ProfileProduction } from '@/components/countries/ProfileProduction'
import { ProfileContext, ProfileMissing, ProfileNews, ProfilePrices, ProfileRegulations } from '@/components/countries/ProfileSections'
import { ProfileTrade } from '@/components/countries/ProfileTrade'
import type { CountryProfile, TradeFlowSection } from '@/components/countries/types'
import { fmtT, SourcesFooter, useProviderText } from '@/components/trade/bits'
import { useI18n } from '@/i18n'
import { ApiError, api } from '@/lib/api'
import { fmtNumber } from '@/lib/format'

export default function CountryDetail() {
  const { iso3 = '' } = useParams()
  const code = iso3.toUpperCase()
  const { t } = useI18n()
  const q = useQuery({
    queryKey: ['countries', code],
    queryFn: () => api.get<CountryProfile>(`/countries/${encodeURIComponent(code)}`),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
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
  return <Profile p={q.data} back={back} />
}

function Profile({ p, back }: { p: CountryProfile; back: React.ReactNode }) {
  const { t, lang } = useI18n()
  const region = useRegion()
  const c = p.country
  return (
    <div>
      {back}
      <PageHeader
        eyebrow={`${region(c.region)} · ${c.iso3}`}
        title={countryName(c, lang)}
        subtitle={<span className="block mt-2"><AvailabilityChips a={p.availability} /></span>}
        actions={
          <div className="flex items-center gap-2">
            {p.is_demo && <DemoBadge />}
            {c.priority && <Badge tone="gold"><Star size={11} /> {t('countries.priority')}</Badge>}
          </div>
        }
      />

      <KpiRow p={p} />
      <ProfileMissing p={p} />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px] items-start mb-5">
        <ProfileProduction data={p.production} />
        <ProfileContext p={p} />
      </div>

      <div className="mb-5"><ProfileTrade p={p} /></div>
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
    </div>
  )
}

function KpiRow({ p }: { p: CountryProfile }) {
  const { t, lang } = useI18n()
  const providerText = useProviderText()
  const prodMetric = p.production.metrics.find((m) => m.metric === 'production')
  const prod = prodMetric?.series[0]?.latest
  const prodSeries = prodMetric?.series[0]

  const tradeTile = (s: TradeFlowSection, label: string, mirrorKey: string) => {
    const l = s.latest
    if (l) {
      return (
        <StatTile
          label={label}
          value={<>{fmtT(l.net_weight_kg, lang)}<span className="text-muted text-[0.6em] ml-1">t</span></>}
          sub={`${t('countries.kpi.year', { y: l.year })}${l.summed_from_partners ? ' · Σ' : ''}`}
          delta={l.yoy_volume_pct}
          deltaLabel={l.prev ? `vs ${l.prev.year}` : undefined}
          demo={l.is_demo}
          footer={<span className="text-[0.78rem] text-muted">{t('prov.source')}: {l.source?.publisher || l.source?.name}</span>}
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
          value={<>{fmtNumber(prod.value, lang, 0)}<span className="text-muted text-[0.6em] ml-1">{prod.unit}</span></>}
          sub={t('countries.kpi.year', { y: prod.period_label })}
          demo={prod.is_demo}
          footer={<span className="text-[0.78rem] text-muted">{t('prov.source')}: {prodSeries.source?.publisher || prodSeries.source?.name}</span>}
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
        sub={p.news.available || p.news.count_30d ? t('countries.kpi.newsSub') : t('ui.noData')}
        demo={p.news.items.some((n) => n.is_demo)}
        footer={<Link to={p.news.link} className="text-[0.78rem] link">{t('countries.news.all')}</Link>}
      />
    </div>
  )
}
