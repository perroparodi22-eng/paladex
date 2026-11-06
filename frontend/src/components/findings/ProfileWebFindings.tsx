// Country page, "Altre fonti (non ufficiali)": the newest figures found on the web for the country,
// each checked by Paladex on the page it cites, kept apart from every official figure on the page.
// Rendered from the `web_findings` block of /api/countries/{iso3}, so the read-only online copy shows
// it from the recorded answer; an older answer without the block shows nothing.
import { ExternalLink, Quote, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AiBadge, Badge, DemoBadge, Note, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtPeriod } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type { FindingStatus, WebFinding, WebFindingsBlock } from './types'

const STATUS_TONE: Record<FindingStatus, 'forest' | 'warn' | 'neutral'> = {
  official_final: 'forest', official_provisional: 'warn', official_estimate: 'warn',
  forecast: 'warn', estimate: 'warn', reported: 'neutral',
}

/** "2026" / "2026-09" as the app writes periods; anything else ("2025/26", "2026-01..2026-06") as published. */
function periodText(label: string, lang: Lang): string {
  return /^\d{4}(-\d{2}|-Q[1-4])?$/.test(label) ? fmtPeriod(label, lang) : label.replace('..', '–')
}

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export function ProfileWebFindings({ p }: { p: { country: { iso3: string }; web_findings?: WebFindingsBlock | null } }) {
  const { t } = useI18n()
  const b = p.web_findings
  if (!b) return null
  const demo = b.metrics.some((m) => m.findings.some((f) => f.is_demo))
  return (
    <Panel
      title={t('findings.title')}
      eyebrow={t('findings.eyebrow')}
      actions={<>{demo && <DemoBadge />}<Badge tone="warn" title={t('findings.nonOfficialTitle')}>{t('findings.badge')}</Badge></>}
      footer={
        <span className="flex flex-wrap items-center justify-between gap-2">
          <span>{b.available ? (b.count === 1 ? t('findings.countOne') : t('findings.count', { n: b.count })) : ''}</span>
          <Link to="/fonti#web_findings" className="link">{t('findings.howLink')} →</Link>
        </span>
      }
    >
      <div className="flex flex-col gap-5">
        <Note>{t('findings.explain')}</Note>
        {b.available ? b.metrics.map((m) => (
          <section key={m.metric} aria-label={t(`findings.metric.${m.metric}`)}>
            <h3 className="font-serif text-[1.05rem] font-semibold mb-1">{t(`findings.metric.${m.metric}`)}</h3>
            <ul className="flex flex-col divide-y divide-line-soft">
              {m.findings.map((f) => <FindingItem key={f.id} f={f} />)}
            </ul>
          </section>
        )) : <Empty b={b} />}
      </div>
    </Panel>
  )
}

function FindingItem({ f }: { f: WebFinding }) {
  const { t, lang } = useI18n()
  const failed = f.last_check && f.last_check.ok === false
  const attributed = !f.is_official && f.status.startsWith('official_')
  const also = f.also_reported_by
    .map((a) => (typeof a === 'string' ? a : a.url ?? ''))
    .filter((u) => /^https?:\/\//.test(u))
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <span className="num text-[1.25rem] text-charcoal" lang={f.language ?? undefined}>{f.value_as_published}</span>
          {f.value !== null && (
            <span className="ml-2 text-[0.85rem] text-muted num">{t('findings.asNumber', { v: fmtNumber(f.value, lang, f.value % 1 ? 2 : 0), u: f.unit })}</span>
          )}
          {f.value === null && f.value_low != null && f.value_high != null && (
            <span className="ml-2 text-[0.85rem] text-muted num">
              {t('findings.range', { a: fmtNumber(f.value_low, lang), b: fmtNumber(f.value_high, lang), u: f.unit })}
            </span>
          )}
        </div>
        <span className="text-[0.9rem] text-charcoal-soft whitespace-nowrap">{t('findings.period')}: <span className="num">{periodText(f.period_label, lang)}</span></span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {f.is_demo && <DemoBadge />}
        <Badge tone={STATUS_TONE[f.status] ?? 'neutral'}>{t(`findings.status.${f.status}`)}</Badge>
        {f.is_official
          ? <Badge tone="forest" title={t('findings.officialPubTitle')}>{t('findings.officialPub')}</Badge>
          : <Badge tone="outline" title={t('findings.nonOfficialTitle')}>{t('findings.nonOfficial')}</Badge>}
        {f.found_by === 'ai_web_search' && <span title={t('findings.foundByAiTitle')}><AiBadge label={t('findings.foundByAi')} /></span>}
      </div>
      {attributed && <div className="mt-1 text-[0.82rem] text-muted">{t('findings.attributed')}</div>}
      <div className="mt-1.5 text-[0.85rem] text-charcoal-soft">
        <span className="font-medium">{f.publisher}</span>
        <span className="text-muted"> · {t(`findings.kind.${f.kind}`)}</span>
        {f.published_at && <span className="text-muted"> · {t('findings.published', { d: fmtDate(f.published_at, lang) })}</span>}
        {f.language && f.language.slice(0, 2) !== lang && <span className="text-muted uppercase"> · {f.language.slice(0, 2)}</span>}
      </div>
      <details className="mt-1.5 group">
        <summary className="cursor-pointer text-[0.85rem] text-forest-700 hover:text-forest-900 inline-flex items-center gap-1">
          <Quote size={13} /> {t('findings.quote')}
        </summary>
        <blockquote className="mt-1.5 border-l-2 border-gold-light pl-3 text-[0.9rem] italic text-charcoal-soft" lang={f.language ?? undefined}>
          “{f.quote}”
        </blockquote>
        {f.notes && <p className="mt-1 text-[0.8rem] text-muted">{t('findings.notes')}: {f.notes}</p>}
      </details>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8rem] text-muted">
        <a href={f.source_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1"
          title={t('findings.openTitle', { url: f.source_url })}>
          {t('findings.open')} ({host(f.source_url)}) <ExternalLink size={12} />
        </a>
        {f.verified_at && (
          <span className="inline-flex items-center gap-1">
            <ShieldCheck size={13} className="text-forest-700" />
            {t(f.last_check?.doc_type === 'pdf' ? 'findings.verifiedPdf' : 'findings.verified', { d: fmtDate(f.verified_at, lang) })}
          </span>
        )}
      </div>
      {failed && f.last_check && (
        <div className="mt-1 text-[0.8rem] text-[#7A5414]">
          {t('findings.checkFailed', {
            d: fmtDate(f.last_check.at, lang),
            why: t(`findings.why.${f.last_check.reason && ['unreachable', 'blocked', 'quote_not_found', 'number_not_found', 'unsupported', 'unreadable', 'invalid'].includes(f.last_check.reason) ? f.last_check.reason : 'other'}`),
            v: fmtDate(f.verified_at, lang),
          })}
        </div>
      )}
      {also.length > 0 && (
        <div className="mt-1 text-[0.8rem] text-muted">
          {t('findings.alsoReported')}{' '}
          {also.map((u, i) => (
            <span key={u}>{i > 0 && ', '}<a href={u} target="_blank" rel="noreferrer" className="link">{host(u)}</a></span>
          ))}
        </div>
      )}
    </li>
  )
}

function Empty({ b }: { b: WebFindingsBlock }) {
  const { t, lang } = useI18n()
  return (
    <div>
      <div className="font-serif text-lg text-charcoal-soft">{t('findings.emptyTitle')}</div>
      {b.not_found.length === 0 ? (
        <p className="mt-1 text-sm text-muted">{t('findings.emptyNone')}</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-3">
          {b.not_found.map((n, i) => (
            <li key={i} className="text-[0.9rem] text-charcoal-soft">
              <div className="eyebrow !text-[0.68rem]">{t(`findings.by.${n.by}`, { d: n.on ? fmtDate(n.on, lang) : '—' })}</div>
              {n.searched && <p className="mt-0.5"><span className="font-medium">{t('findings.emptySearched')}:</span> {n.searched}</p>}
              {n.result && <p className="mt-0.5"><span className="font-medium">{t('findings.emptyResult')}:</span> {n.result}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
