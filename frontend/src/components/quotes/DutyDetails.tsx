// The official duty layers behind a landed cost: the alternatives used (with quota balance and legal
// act), the conditions TARIC publishes for them, and the layers that are NOT turned into numbers
// (US anti-dumping, Chapter 99 headings, EU measures with conditions): explicit warnings with links.
import { AlertTriangle, ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { DutyLayer } from '@/components/regulations/DutyLayer'
import { fmtDuty } from '@/components/regulations/format'
import type { DutyRow } from '@/components/regulations/types'
import { Badge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { useQuoteLabels } from './labels'
import type { Landed, Rate } from './types'

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">
      {children} <ExternalLink size={12} />
    </a>
  )
}

function conditionsOf(m: DutyRow): string[] {
  const conds = (m.extra?.conditions as { requirement?: string | null }[] | undefined) ?? []
  return [...new Set(conds.map((c) => c.requirement).filter((x): x is string => Boolean(x)))]
}

export function DutyDetails({ landed, origin }: { landed: Landed; origin: string }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const labels = useQuoteLabels()
  const d = landed.duty
  const withMeasure = landed.scenarios.filter((s) => s.measure)
  const usReview = d.jurisdiction === 'US' ? d.review : []
  const euReview = d.jurisdiction === 'EU' ? d.review : []
  const ad = d.ad_case
  return (
    <div className="space-y-4">
      <p className="text-[0.9rem] text-muted">
        {t(d.jurisdiction === 'EU' ? 'quotes.duty.introEU' : 'quotes.duty.introUS', { date: fmtDate(d.on, lang) })}
        {d.as_of && <> {t('quotes.duty.checked', { date: fmtDate(d.as_of, lang) })}</>}
        {d.source && <> · {t('prov.source')}: <span className="text-charcoal-soft">{d.source.publisher ?? d.source.name}</span></>}
      </p>

      {withMeasure.length > 0 && (
        <div className="divide-y divide-line-soft rounded-sm border border-line bg-white px-4">
          {withMeasure.map((s) => {
            const m = s.measure!
            const conds = conditionsOf(m)
            return (
              <div key={s.key} className="py-2">
                <div className="mb-0.5 flex flex-wrap items-center gap-2">
                  <span className="eyebrow">{t(`quotes.summary.role.${s.role === 'in_quota' ? 'inQuota' : s.role === 'out_of_quota' ? 'outQuota' : 'applicable'}`)}</span>
                  {!s.available && <Badge tone="down">{t(`quotes.quota.reason.${s.unavailable_reason ?? 'exhausted'}`)}</Badge>}
                </div>
                <DutyLayer row={m} general={m.scope === 'general' ? t('quotes.duty.generalLayer') : undefined} />
                {s.notes.map((n, i) => {
                  if (n.code === 'proof_of_origin') {
                    return <p key={i} className="mt-1 text-[0.86rem] text-charcoal-soft">{t('quotes.duty.proofOfOrigin', { mfn: labels.rate(n.params?.mfn as Rate) })}</p>
                  }
                  if (n.code === 'program_certification') {
                    return (
                      <p key={i} className="mt-1 text-[0.86rem] text-charcoal-soft">
                        {t('quotes.duty.programCertification', {
                          codes: ((n.params?.codes as string[] | undefined) ?? []).join(', '),
                          general: labels.rate(n.params?.general as Rate),
                        })}
                      </p>
                    )
                  }
                  return null
                })}
                {conds.length > 0 && (
                  <div className="mt-1 text-[0.82rem] text-muted">
                    {t('quotes.duty.conditions')} <span className="text-charcoal-soft">{conds.join(' · ')}</span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {ad && (
        <div className="rounded-sm border border-[#EBCDC6] bg-[#FBF1EE] px-4 py-3 text-[0.92rem] text-[#7E2C20]">
          <div className="flex items-center gap-2 font-semibold"><AlertTriangle size={17} className="shrink-0" />{t('quotes.duty.verifyTitle')}</div>
          <p className="mt-1 leading-relaxed">
            {t('quotes.duty.adBody', { origin: country(origin), case: ad.case_number ?? t('quotes.duty.caseUnknown'), product: ad.product })}
          </p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            <Ext href={ad.fr_search_url}>{t('quotes.duty.frSearch')}</Ext>
            {d.links.hts && <Ext href={d.links.hts}>{t('quotes.duty.htsLink')}</Ext>}
          </div>
          {(ad.documents?.length ?? 0) > 0 && (
            <div className="mt-2">
              <div className="text-[0.82rem] font-medium">{t('quotes.duty.adDocs', { n: ad.documents_total ?? ad.documents!.length })}</div>
              <ul className="mt-0.5 space-y-0.5 text-[0.84rem]">
                {ad.documents!.slice(0, 4).map((doc) => (
                  <li key={doc.id}>
                    <span className="num mr-1">{fmtDate(doc.published_at, lang)}</span>
                    <Ext href={doc.url}>{doc.title}</Ext>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {usReview.length > 0 && (
        <div className="rounded-sm border border-[#EED9B0] bg-[#FBF5E8] px-4 py-3 text-[0.92rem] text-[#7A5414]">
          <div className="flex items-center gap-2 font-semibold"><AlertTriangle size={17} className="shrink-0" />{t('quotes.duty.verifyTitle')}</div>
          <p className="mt-1 leading-relaxed">{t('quotes.duty.ch99Body', { n: usReview.length })}</p>
          <ul className="mt-2 divide-y divide-[#EED9B0]">
            {usReview.map((m) => (
              <li key={m.id} className="grid gap-x-3 gap-y-0.5 py-1.5 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto]">
                <span className="num">{m.measure_code}</span>
                <span className="line-clamp-2 text-[0.84rem]" title={m.description ?? undefined}>{m.description}</span>
                <span className="flex items-center gap-2 text-[0.84rem]">
                  <span className="num">{fmtDuty(m, lang, t('quotes.duty.free'))}</span>
                  {m.consult_url && <Ext href={m.consult_url}>HTS</Ext>}
                </span>
              </li>
            ))}
          </ul>
          {(d.review_other_origins ?? 0) > 0 && (
            <p className="mt-1 text-[0.82rem]">{t('quotes.duty.ch99Other', { n: d.review_other_origins ?? 0 })}</p>
          )}
        </div>
      )}

      {euReview.length > 0 && (
        <details className="rounded-sm border border-line bg-white px-4 py-2 text-[0.9rem]">
          <summary className="cursor-pointer text-charcoal-soft">{t('quotes.duty.euReview', { n: euReview.length })}</summary>
          <ul className="mt-2 divide-y divide-line-soft">
            {euReview.map((m) => (
              <li key={m.id} className="py-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-charcoal-soft">{m.description ?? m.measure_code}</span>
                  <span className="num text-muted">{fmtDuty(m, lang, t('quotes.duty.free'))}</span>
                </div>
                {m.review_reason && <div className="text-[0.82rem] text-muted">{m.review_reason}</div>}
                <div className="flex flex-wrap gap-x-3 text-[0.8rem] text-muted">
                  <Badge tone="warn">{t('regulations.duties.review')}</Badge>
                  {m.legal_url && <Ext href={m.legal_url}>{m.legal_reference?.split(';')[0] ?? t('quotes.duty.legal')}</Ext>}
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[0.88rem]">
        {d.links.taric && <Ext href={d.links.taric}>{t('quotes.duty.taricLink')}</Ext>}
        {d.links.hts && !ad && <Ext href={d.links.hts}>{t('quotes.duty.htsLink')}</Ext>}
        <Link to="/normative" className="link">{t('quotes.duty.regulationsPage')}</Link>
      </div>
    </div>
  )
}
