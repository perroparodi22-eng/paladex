// Top of the Sources page: one plain sentence on the overall state, five key numbers and "Aggiorna tutto".
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, Info, KeyRound, Loader2, RefreshCw, WifiOff } from 'lucide-react'
import type { ReactNode } from 'react'
import { useI18n } from '@/i18n'
import { fmtAgo, fmtDateTime, fmtNumber } from '@/lib/format'
import { isMirror } from '@/lib/mirror'
import type { CollectState, SourceInfo } from '@/lib/types'
import { asUtc } from './explain'
import type { QualitySummary } from './types'

function needsAttention(s: SourceInfo): boolean {
  return s.enabled && s.kind !== 'manual' && (s.freshness.status === 'stale' || s.freshness.status === 'aging' || s.last_run_status === 'failed')
}

export function SourcesSummary({ summary, sources, collect, onUpdateAll, starting }: {
  summary: QualitySummary; sources: SourceInfo[]; collect: CollectState | undefined; onUpdateAll: () => void; starting: boolean
}) {
  const { t, lang } = useI18n()
  const s = summary.sources
  const running = collect?.running ?? false
  const attention = sources.filter(needsAttention).length
  const nothingYet = sources.every((x) => x.kind === 'manual' || x.freshness.status === 'never')
  const ok = !nothingYet && attention === 0 && summary.issues.critical + summary.issues.warning === 0

  const verdict = nothingYet ? t('sources.sum.verdict.empty')
    : ok ? t('sources.sum.verdict.ok')
    : attention === 1 ? t('sources.sum.verdict.one')
    : attention > 1 ? t('sources.sum.verdict.attention', { n: attention })
    : t('sources.sum.verdict.checks', { n: summary.issues.critical + summary.issues.warning })

  return (
    <section className="panel" aria-labelledby="sources-verdict">
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4 px-6 pt-5 pb-5 border-b border-line-soft">
        <div className="flex items-start gap-3 min-w-0 flex-1 basis-[26rem]">
          <span className={clsx('mt-0.5 shrink-0', ok ? 'text-up' : nothingYet ? 'text-gold' : 'text-warn')}>
            {ok ? <CheckCircle2 size={26} /> : nothingYet ? <Info size={26} /> : <AlertTriangle size={26} />}
          </span>
          <div className="min-w-0">
            <p id="sources-verdict" className="font-serif text-[1.3rem] leading-snug text-charcoal">{verdict}</p>
            <div className="mt-1.5 flex flex-col gap-1 text-[0.92rem] text-muted">
              {s.key_missing > 0 && (
                <span className="inline-flex items-center gap-1.5"><KeyRound size={15} className="text-gold" />{t('sources.sum.keysMissing', { n: s.key_missing })}</span>
              )}
              {s.offline > 0 && (
                <span className="inline-flex items-center gap-1.5"><WifiOff size={15} />{t('sources.sum.offline')}</span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-5 flex-wrap">
          <dl className="text-sm leading-snug">
            <div className="flex gap-2 items-baseline">
              <dt className="text-muted">{t('sources.sum.lastUpdate')}:</dt>
              <dd className="text-charcoal font-medium" title={fmtDateTime(asUtc(summary.last_check_at), lang)}>
                {summary.last_check_at ? fmtAgo(summary.last_check_at, lang) : t('sources.sum.never')}
              </dd>
            </div>
            <div className="flex gap-2 items-baseline mt-0.5">
              <dt className="text-muted">{t('sources.sum.lastNewData')}:</dt>
              <dd className="text-charcoal-soft" title={fmtDateTime(asUtc(summary.last_new_data_at), lang)}>
                {summary.last_new_data_at ? fmtAgo(summary.last_new_data_at, lang) : t('sources.sum.never')}
              </dd>
            </div>
          </dl>
          {!isMirror() && (
            <button className="btn-primary !px-5 !py-2.5" onClick={onUpdateAll} disabled={running || starting}>
              <RefreshCw size={17} className={clsx(running && 'animate-spin')} />
              {running ? t('sources.sum.updating') : t('sources.sum.updateAll')}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-px bg-line-soft">
        <Stat label={t('sources.sum.active')} value={fmtNumber(s.enabled, lang)} hint={t('sources.sum.activeOf', { n: s.total })} href="#fonti-elenco" />
        <Stat label={t('sources.sum.current')} value={fmtNumber(s.current, lang)} hint={t('sources.sum.currentHint')} dot="bg-up" href="#fonti-elenco" />
        <Stat label={t('sources.sum.late')} value={fmtNumber(s.aging + s.stale, lang)} hint={t('sources.sum.lateHint')} dot="bg-warn" href="#fonti-elenco"
          emphasis={s.aging + s.stale > 0} />
        <Stat label={t('sources.sum.errors')} value={fmtNumber(s.errors, lang)} hint={t('sources.sum.errorsHint')} dot="bg-down" href="#fonti-elenco"
          emphasis={s.errors > 0} />
        <Stat label={t('sources.sum.issues')} value={fmtNumber(summary.issues.open, lang)} href="#qualita"
          hint={t('sources.sum.issuesHint', { c: summary.issues.critical, w: summary.issues.warning, i: summary.issues.info })}
          dot={summary.issues.critical ? 'bg-down' : summary.issues.warning ? 'bg-warn' : undefined} emphasis={summary.issues.critical > 0}
          className="col-span-2 xl:col-span-1" />
      </div>

      {running && collect?.started_at && (
        <div className="flex items-center gap-2 px-6 py-2.5 border-t border-line-soft bg-forest-50 text-forest-800 text-[0.92rem]">
          <Loader2 size={16} className="animate-spin" />
          {t('sources.sum.updatingSince', { t: fmtAgo(collect.started_at, lang) })}
        </div>
      )}
    </section>
  )
}

function Stat({ label, value, hint, dot, href, emphasis, className }: {
  label: string; value: ReactNode; hint: string; dot?: string; href: string; emphasis?: boolean; className?: string
}) {
  return (
    <a href={href} className={clsx('group block bg-white px-6 py-4 hover:bg-[#FCFAF4]', className)}>
      <div className="eyebrow flex items-center gap-1.5">
        {dot && <span className={clsx('inline-block h-2 w-2 rounded-full', dot)} />}
        {label}
      </div>
      <div className={clsx('num text-[2rem] leading-tight mt-1', emphasis ? 'text-charcoal' : 'text-charcoal-soft')}>{value}</div>
      <div className="text-[0.85rem] text-muted leading-snug mt-0.5">{hint}</div>
    </a>
  )
}
