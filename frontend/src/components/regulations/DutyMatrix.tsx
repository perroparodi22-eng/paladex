// "Dazi per origine": one row per origin (priority origins first), the EU and US duty layers side by
// side, each with its official link and the date it was last verified. Chapter 99 headings whose scope
// is ambiguous are listed once, below the table, instead of being attributed to countries.
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowRight, ChevronDown, ChevronUp, ExternalLink, History, Scale } from 'lucide-react'
import { Fragment, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Badge, EmptyState, ErrorBlock, FreshnessBadge, Loading, Note, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { DutyLayer, useLayerLabel } from './DutyLayer'
import { fmtDuty, fmtKg } from './format'
import type { AdCase, DutiesResponse, DutyHistory, DutyRow, JurisdictionStatus, OriginDuties } from './types'
import { pageUrl } from '@/lib/links'

function ExtLink({ href, title, children }: { href: string; title?: string; children: ReactNode }) {
  return (
    <a href={pageUrl(href) ?? undefined} target="_blank" rel="noreferrer" title={title} className="link inline-flex items-center gap-0.5">
      {children} <ExternalLink size={11} />
    </a>
  )
}

// `asOf` is the oldest confirmation of the layers shown, `latest` the newest: when they differ, some
// layer was not re-confirmed by the last read and the footer never presents it under the newer date.
function CellFooter({ asOf, latest, link }: { asOf: string | null; latest?: string | null; link: ReactNode }) {
  const { t, lang } = useI18n()
  const mixed = Boolean(asOf && latest && latest !== asOf)
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line-soft pt-1.5 text-[0.78rem] text-muted">
      <span className={clsx(mixed && 'text-warn')}>
        {!asOf ? t('regulations.duties.notVerified')
          : mixed ? t('regulations.duties.verifiedMixed', { latest: fmtDate(latest, lang), oldest: fmtDate(asOf, lang) })
            : t('regulations.duties.verified', { date: fmtDate(asOf, lang) })}
      </span>
      <span aria-hidden>·</span>
      {link}
    </div>
  )
}

function Unavailable({ children }: { children?: ReactNode }) {
  const { t } = useI18n()
  return <div className="py-1.5 text-[0.9rem] italic text-muted">{children ?? t('regulations.duties.unavailable')}</div>
}

function AdCaseBlock({ ad }: { ad: AdCase }) {
  const { t, lang } = useI18n()
  const latest = ad.documents[0]
  return (
    <div className="mt-1.5 rounded-sm border border-line-soft bg-paper px-2.5 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="text-[0.86rem] font-medium text-charcoal-soft">{t('regulations.ad.title')}</span>
        {ad.case_number
          ? <span className="num text-[0.84rem] text-charcoal">{t('regulations.ad.case', { n: ad.case_number })}</span>
          : <span className="text-[0.78rem] text-muted">{t('regulations.ad.caseUnknown')}</span>}
      </div>
      <div className="text-[0.78rem] text-muted">{ad.product} · {t('regulations.ad.ratesNote')}</div>
      {latest ? (
        <div className="mt-1 text-[0.8rem] leading-snug">
          <a href={pageUrl(latest.url) ?? undefined} target="_blank" rel="noreferrer" title={latest.title} className="link line-clamp-2">
            {t('regulations.ad.latestDoc', { title: latest.title })}
          </a>
          <span className="text-muted">{fmtDate(latest.published_at, lang)}</span>
          {ad.documents_total > 1 && <div className="text-[0.76rem] text-muted">{t('regulations.ad.docs', { n: ad.documents_total })}</div>}
        </div>
      ) : (
        <div className="mt-1 text-[0.8rem] text-muted">{t('regulations.ad.noDocs')}</div>
      )}
      <div className="mt-1 text-[0.78rem]">
        <ExtLink href={ad.fr_search_url}>{t('regulations.ad.search')}</ExtLink>
      </div>
    </div>
  )
}

function EuCell({ o, status, general }: { o: OriginDuties; status: JurisdictionStatus; general: DutyRow[] }) {
  const { t } = useI18n()
  const applies = general.filter((g) => o.eu.general_ids.includes(g.id))
  // Every general (erga omnes) layer that applies: MFN, safeguard / additional duties, non-preferential
  // quotas, erga-omnes anti-dumping ... The general MFN only gives way to the origin's own MFN.
  const base = applies.filter((g) => !g.needs_review && !(g.measure_type === 'mfn' && o.eu.has_own_mfn))
  const review = applies.filter((g) => g.needs_review).length
  if (!status.last_success_at && o.eu.rows.length === 0 && base.length === 0) return <Unavailable />
  return (
    <div>
      <div className="divide-y divide-line-soft">
        {base.map((g) => <DutyLayer key={g.id} row={g} general={t('regulations.duties.generalAppliesEU')} />)}
        {o.eu.rows.map((r) => <DutyLayer key={r.id} row={r} />)}
      </div>
      {o.eu.rows.length === 0 && base.length > 0 && (
        <div className="text-[0.8rem] text-muted">{t('regulations.duties.noOwnMeasures')}</div>
      )}
      {review > 0 && <div className="text-[0.78rem] text-muted">{t(review === 1 ? 'regulations.duties.generalReviewEU1' : 'regulations.duties.generalReviewEU', { n: review })}</div>}
      <CellFooter asOf={o.eu.as_of} latest={o.eu.as_of_latest} link={
        <ExtLink href={o.eu.links.taric} title={t('regulations.duties.taricLinkTitle')}>{t('regulations.duties.taricLink')}</ExtLink>
      } />
    </div>
  )
}

function UsCell({ o, status, general }: { o: OriginDuties; status: JurisdictionStatus; general: DutyRow[] }) {
  const { t } = useI18n()
  if (o.us.domestic) return <Unavailable>{t('regulations.duties.domestic')}</Unavailable>
  const applies = general.filter((g) => o.us.general_ids.includes(g.id))
  const base = applies.filter((g) => !g.needs_review)
  const review = applies.length - base.length
  const hasRows = o.us.rows.length > 0 || base.length > 0
  return (
    <div>
      {!status.last_success_at && !hasRows ? <Unavailable /> : (
        <div className="divide-y divide-line-soft">
          {base.map((g) => <DutyLayer key={g.id} row={g} general={t('regulations.duties.generalAppliesUS')} />)}
          {o.us.rows.map((r) => <DutyLayer key={r.id} row={r} />)}
        </div>
      )}
      {review > 0 && <div className="text-[0.78rem] text-muted">{t(review === 1 ? 'regulations.duties.generalReviewUS1' : 'regulations.duties.generalReviewUS', { n: review })}</div>}
      {o.us.ad_case && <AdCaseBlock ad={o.us.ad_case} />}
      <CellFooter asOf={o.us.as_of} latest={o.us.as_of_latest} link={
        <ExtLink href={o.us.links.hts} title={t('regulations.duties.htsLinkTitle')}>{t('regulations.duties.htsLink')}</ExtLink>
      } />
    </div>
  )
}

function HistoryPanel({ iso3, name }: { iso3: string; name: string }) {
  const { t, lang } = useI18n()
  const label = useLayerLabel()
  const q = useQuery({ queryKey: ['regulations', 'history', iso3], queryFn: () => api.get<DutyHistory>(`/regulations/duties/${iso3}`) })
  if (q.isLoading) return <Loading label={t('regulations.history.loading')} />
  if (q.error) return <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
  const series = q.data?.series ?? []
  return (
    <div className="space-y-3">
      <h3 className="font-serif text-[1.05rem] font-semibold text-charcoal">{t('regulations.history.title', { name })}</h3>
      {series.length === 0 ? <div className="text-[0.9rem] text-muted">{t('regulations.history.empty')}</div> : (
        <div className="grid gap-3 lg:grid-cols-2">
          {series.map((s) => {
            const latest = s.revisions[0]
            return (
              <div key={s.series_key} className="rounded-sm border border-line-soft bg-white px-3 py-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[0.88rem] font-medium text-charcoal-soft">
                    <Badge tone="outline" className="mr-1.5">{t(`regulations.j.${s.jurisdiction}`)}</Badge>
                    {label(latest)}
                    {s.scope === 'general' && <span className="font-normal text-muted"> · {t('regulations.history.general')}</span>}
                  </span>
                  <span className="flex flex-wrap gap-1">
                    {latest.needs_review && <Badge tone="warn" title={latest.review_reason ?? undefined}>{t('regulations.duties.review')}</Badge>}
                    <Badge tone={s.current ? 'up' : 'outline'}>{t(s.current ? 'regulations.history.current' : 'regulations.history.withdrawn')}</Badge>
                  </span>
                </div>
                <ol className="mt-1.5 space-y-1">
                  {s.revisions.map((r) => (
                    <li key={r.id} className={clsx('flex flex-wrap items-baseline gap-x-2 text-[0.8rem]', r.is_current ? 'text-charcoal-soft' : 'text-muted')}>
                      <span className="num">{t('regulations.history.revision', { n: r.revision })}</span>
                      <span className="num font-medium">{fmtDuty(r, lang, t('regulations.duty.free'))}</span>
                      {r.quota?.balance_kg != null && <span className="num">· {t('regulations.history.balance', { balance: fmtKg(r.quota.balance_kg, lang) })}</span>}
                      <span className="w-full text-muted">{t('regulations.history.seen', { from: fmtDate(r.collected_at, lang), to: fmtDate(r.as_of, lang) })}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function StatusStrip({ d }: { d: DutiesResponse }) {
  const { t, lang } = useI18n()
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-2 text-[0.88rem]">
      {(['EU', 'US'] as const).map((j) => {
        const s = d.jurisdictions[j]
        return (
          <div key={j} className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-medium text-charcoal">{t(`regulations.status.${j === 'EU' ? 'eu' : 'us'}`)}</span>
            {s.freshness && <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />}
            <span className="text-muted">
              {s.as_of ? t('regulations.status.as_of', { date: fmtDate(s.as_of, lang) }) : t('regulations.status.never')}
              {s.last_run_status === 'failed' && <> · <span className="text-down">{t('regulations.status.failed')}</span></>}
              {s.last_run_status === 'partial' && <> · <span className="text-warn">{t('regulations.status.partial')}</span></>}
            </span>
            {s.review_count > 0 && (
              <Badge tone="warn">{s.review_count === 1 ? t('regulations.status.review1') : t('regulations.status.reviewN', { n: s.review_count })}</Badge>
            )}
          </div>
        )
      })}
    </div>
  )
}

function GeneralReview({ d }: { d: DutiesResponse }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const label = useLayerLabel()
  const rows = [...d.jurisdictions.EU.general, ...d.jurisdictions.US.general].filter((r) => r.needs_review)
  if (rows.length === 0) return null
  return (
    <div className="border-t border-line px-5 py-4">
      <h3 className="font-serif text-[1.05rem] font-semibold text-charcoal">{t('regulations.general.title')}</h3>
      <p className="mt-1 max-w-4xl text-[0.9rem] text-muted">{t('regulations.general.body')}</p>
      <ul className="mt-3 divide-y divide-line-soft">
        {rows.map((r) => {
          const named = (r.extra?.countries_named as string[] | undefined) ?? []
          return (
            <li key={r.id} className="grid gap-x-4 gap-y-1 py-2 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto]">
              <div className="text-[0.88rem] text-charcoal-soft">
                <Badge tone="outline" className="mr-1.5">{t(`regulations.j.${r.jurisdiction}`)}</Badge>{label(r)}
              </div>
              <div className="text-[0.84rem] text-muted">
                <div className="line-clamp-2" title={r.description ?? undefined}>{r.description}</div>
                {named.length > 0 && <div>{t('regulations.general.countries', { list: named.map((c) => country(c)).join(', ') })}</div>}
                <div className="flex flex-wrap items-center gap-x-2">
                  <Badge tone="warn" title={r.review_reason ?? undefined}>{t('regulations.duties.review')}</Badge>
                  {r.consult_url && <ExtLink href={r.consult_url}>{t('regulations.duties.consultLink')}</ExtLink>}
                  <span>{t('regulations.duties.verified', { date: fmtDate(r.as_of, lang) })}</span>
                </div>
              </div>
              <div className="num text-right text-[1rem] text-muted" title={r.duty_text ?? undefined}>{fmtDuty(r, lang, t('regulations.duty.free'))}</div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function NoDutiesYet({ d }: { d: DutiesResponse }) {
  const { t } = useI18n()
  const { country } = useLabels()
  const byOrigin = new Map(d.origins.map((o) => [o.iso3, o]))
  return (
    <div>
      <EmptyState icon={<Scale size={24} />} title={t('regulations.empty.title')} hint={t('regulations.empty.body')}
        action={<Link to="/fonti" className="btn-secondary">{t('regulations.empty.sources')} <ArrowRight size={16} /></Link>} />
      <div className="border-t border-line-soft px-5 py-4">
        <h3 className="font-serif text-[1.05rem] font-semibold text-charcoal">{t('regulations.empty.adTitle')}</h3>
        <p className="mt-1 text-[0.88rem] text-muted">{t('regulations.ad.ratesNoteLong')}</p>
        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {d.ad_cases.map((c) => {
            const ad = byOrigin.get(c.origin_iso3)?.us.ad_case
            return (
              <div key={c.origin_iso3}>
                <div className="text-[0.9rem] font-medium text-charcoal">{country(c.origin_iso3)}</div>
                {ad && <AdCaseBlock ad={ad} />}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export function DutyMatrix({ d }: { d: DutiesResponse }) {
  const { t, lang } = useI18n()
  const [open, setOpen] = useState<string | null>(null)
  const eu = d.jurisdictions.EU
  const us = d.jurisdictions.US
  const name = (o: OriginDuties) => (lang === 'it' ? o.name_it : o.name_en) ?? o.iso3
  return (
    <Panel title={t('regulations.duties.title')} eyebrow={t('regulations.duties.eyebrow')} bodyClassName="!p-0"
      footer={(
        <div className="space-y-1">
          <div><span className="font-medium text-charcoal-soft">{t('regulations.status.eu')}:</span> {t('regulations.status.sourceEU')}</div>
          <div><span className="font-medium text-charcoal-soft">{t('regulations.status.us')}:</span> {t('regulations.status.sourceUS')} {t('regulations.ad.ratesNoteLong')}</div>
        </div>
      )}>
      {!d.has_data ? <NoDutiesYet d={d} /> : (
        <>
          <div className="space-y-3 border-b border-line-soft px-5 py-4">
            <StatusStrip d={d} />
            <Note>{t('regulations.duties.intro')}</Note>
          </div>
          {/* Phones: one block per origin (name, then EU, then USA) instead of a three-column table. */}
          <div className="relative overflow-x-auto">
            <table className="table-clean min-w-[40rem] table-fixed max-sm:block max-sm:min-w-0">
              <colgroup className="max-sm:hidden">
                <col className="w-[8.5rem] xl:w-[11.5rem]" />
                <col />
                <col />
              </colgroup>
              <thead className="max-sm:hidden">
                <tr>
                  <th>{t('regulations.duties.col.origin')}</th>
                  <th>{t('regulations.duties.col.eu')}<div className="font-normal normal-case tracking-normal">{t('regulations.duties.col.euSub')}</div></th>
                  <th>{t('regulations.duties.col.us')}<div className="font-normal normal-case tracking-normal">{t('regulations.duties.col.usSub')}</div></th>
                </tr>
              </thead>
              <tbody className="max-sm:block">
                {d.origins.map((o) => {
                  const isOpen = open === o.iso3
                  return (
                    <Fragment key={o.iso3}>
                      <tr className={clsx('max-sm:block max-sm:border-b-2 max-sm:border-line', isOpen && 'bg-ivory/40')}>
                        <td className="max-sm:block max-sm:!border-b-0 max-sm:!pb-1">
                          <div className="flex items-start gap-1.5">
                            {o.priority && <span className="mt-2 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-gold" title={t('regulations.duties.priority')} />}
                            <div className="min-w-0">
                              <Link to={`/paesi/${o.iso3}`} className="font-serif text-[1.05rem] font-semibold text-charcoal hover:text-forest-700"
                                title={t('regulations.duties.countryPage')}>
                                {name(o)}
                              </Link>
                              <div className="num text-[0.76rem] text-muted">{o.iso3}</div>
                              <button type="button" className="mt-1.5 inline-flex items-center gap-1 text-[0.82rem] text-forest-700 hover:underline"
                                aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : o.iso3)}>
                                <History size={13} /> {t(isOpen ? 'regulations.duties.historyHide' : 'regulations.duties.history')}
                                {isOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                              </button>
                            </div>
                          </div>
                        </td>
                        <td className="max-sm:block max-sm:!border-b-0">
                          <div className="sm:hidden eyebrow mb-1">{t('regulations.duties.col.eu')}</div>
                          <EuCell o={o} status={eu} general={eu.general} />
                        </td>
                        <td className="max-sm:block">
                          <div className="sm:hidden eyebrow mb-1">{t('regulations.duties.col.us')}</div>
                          <UsCell o={o} status={us} general={us.general} />
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-paper hover:!bg-paper max-sm:block">
                          <td colSpan={3} className="!py-4 max-sm:block"><HistoryPanel iso3={o.iso3} name={name(o)} /></td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
          <GeneralReview d={d} />
        </>
      )}
    </Panel>
  )
}
