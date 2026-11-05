import clsx from 'clsx'
import { Loader2, WifiOff } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DemoBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtAgo } from '@/lib/format'
import { SectionLink } from './parts'
import type { QualityBlock, StatusBlock } from './types'

function Count({ n, label, dot, title }: { n: number; label: string; dot: string; title?: string }) {
  return (
    <span className={clsx('inline-flex items-center gap-1.5 whitespace-nowrap', n === 0 && 'opacity-55')} title={title}>
      <span className={clsx('inline-block h-2 w-2 rounded-full', dot)} />
      <span className="text-charcoal-soft">{label}</span>
    </span>
  )
}

/** One-line health of the data: how many sources are current / late / failing, and when we last looked. */
export function StatusStrip({ status, quality, showDemo }: { status: StatusBlock; quality: QualityBlock; showDemo: boolean }) {
  const { t, lang } = useI18n()
  const c = status.counts
  const late = c.aging + c.stale
  const lateNames = status.sources
    .filter((s) => s.last_run_status === 'failed' || s.freshness.status === 'aging' || s.freshness.status === 'stale')
    .map((s) => s.publisher || s.name)
  const critical = quality.by_severity.critical ?? 0

  return (
    <section className="panel mb-6" aria-label={t('overview.status.title')}>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3 text-[0.92rem]">
        <span className="eyebrow">{t('overview.status.title')}</span>
        <span className="flex flex-wrap items-center gap-x-4 gap-y-1" title={lateNames.length ? t('overview.status.lateList', { list: lateNames.join(', ') }) : undefined}>
          <Count n={c.current} label={t('overview.status.current', { n: c.current })} dot="bg-up" />
          <Count n={late} label={t('overview.status.late', { n: late })} dot="bg-warn" />
          <Count n={c.failed} label={t('overview.status.failed', { n: c.failed })} dot="bg-down" />
          <Count n={c.never} label={t('overview.status.never', { n: c.never })} dot="bg-line" />
          {c.unknown > 0 && <Count n={c.unknown} label={t('overview.status.unknown', { n: c.unknown })} dot="bg-muted" />}
        </span>
        <span className="hidden h-5 w-px bg-line xl:inline-block" aria-hidden />
        <span className="whitespace-nowrap text-muted">
          {t('overview.status.lastCheck')}:{' '}
          <span className="text-charcoal-soft">{status.last_check_at ? fmtAgo(status.last_check_at, lang) : t('overview.status.never_short')}</span>
        </span>
        <span className="whitespace-nowrap text-muted">
          {t('overview.status.newestData')}:{' '}
          <span className="text-charcoal-soft">{status.newest_data_at ? fmtAgo(status.newest_data_at, lang) : t('overview.status.never_short')}</span>
        </span>
        <Link to={quality.link} className="whitespace-nowrap text-muted hover:text-forest-800">
          {t('overview.status.quality')}:{' '}
          <span className={clsx(critical ? 'text-down' : quality.open ? 'text-warn' : 'text-charcoal-soft')}>
            {quality.open === 0 ? t('overview.status.qualityOk')
              : quality.open === 1 ? t('overview.status.qualityOpen1') : t('overview.status.qualityOpen', { n: quality.open })}
            {critical > 0 && ` (${t('overview.status.critical', { n: critical })})`}
          </span>
        </Link>
        <span className="ml-auto flex items-center gap-3">
          {showDemo && <span title={t('overview.status.demo')}><DemoBadge /></span>}
          <SectionLink to={status.link} label={t('overview.status.toSources')} />
        </span>
      </div>
      {(status.offline || status.collection_running) && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-line-soft px-5 py-2 text-[0.85rem]">
          {status.collection_running && (
            <span className="inline-flex items-center gap-1.5 text-forest-700"><Loader2 size={14} className="animate-spin" /> {t('overview.status.running')}</span>
          )}
          {status.offline && (
            <span className="inline-flex items-center gap-1.5 text-warn"><WifiOff size={14} /> {t('overview.status.offline')}</span>
          )}
        </div>
      )}
    </section>
  )
}
