// "Test now": what a rule would find in the data already collected (creates no alert).
import clsx from 'clsx'
import { Badge, SourceLine } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtPct, fmtTonnes } from '@/lib/format'
import { fmtPeriodLabel } from '@/components/prices/utils'
import { SeverityBadge } from './EventFeed'
import type { PreviewCheck, PreviewResponse } from './types'

const SHOWN = 5

function CheckRow({ c, kind }: { c: PreviewCheck; kind: string }) {
  const { t, lang } = useI18n()
  if (kind === 'new_report') {
    return (
      <li className="py-1.5 border-b border-line-soft last:border-0">
        <span className="font-medium">{(lang === 'it' ? c.source?.name : c.source?.publisher || c.source?.name) ?? '—'}</span>{' — '}
        {c.latest_title
          ? t('alerts.pv.latestReport', { t: c.latest_title, d: fmtDate(c.latest_published_at, lang) })
          : t('alerts.pv.noReport')}
      </li>
    )
  }
  const isTrade = kind === 'trade_change'
  const label = isTrade ? (c.source?.publisher || c.source?.name || '—') : (lang === 'it' ? c.label_it : c.label_en) ?? '—'
  const fmt = (v: number | null | undefined) => (isTrade ? fmtTonnes(v ?? null, lang) : `${fmtNumber(v ?? null, lang, 2)} ${c.currency ?? ''}/kg`)
  const value = isTrade ? c.value_kg : c.value
  const prev = isTrade ? c.previous_value_kg : c.previous_value
  return (
    <li className="py-1.5 border-b border-line-soft last:border-0 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
      <span className="font-medium min-w-0 break-words">{label}</span>
      <span className="num text-sm text-charcoal-soft">
        {fmtPeriodLabel(c.period_label, lang)}: {fmt(value)}
        {prev !== null && prev !== undefined && (
          <> · {fmtPeriodLabel(c.previous_period_label, lang)}: {fmt(prev)}</>
        )}
      </span>
      {c.pct !== null && c.pct !== undefined && (
        <span className={clsx('num text-sm', c.pct > 0 ? 'text-up' : c.pct < 0 ? 'text-down' : 'text-muted')}>{fmtPct(c.pct, lang)}</span>
      )}
      {c.reason && (
        <Badge tone={c.reason === 'fires' ? 'gold' : 'outline'}>{t(`alerts.reason.${c.reason}`)}</Badge>
      )}
    </li>
  )
}

export function PreviewResult({ pv, compact = false }: { pv: PreviewResponse; compact?: boolean }) {
  const { t, lang } = useI18n()
  const items = pv.items.slice(0, SHOWN)
  return (
    <div className="text-[0.95rem]">
      {pv.total === 0 ? (
        <p className="text-charcoal-soft">{t('alerts.pv.none')}</p>
      ) : (
        <>
          <p className="text-charcoal-soft mb-2">{pv.total === 1 ? t('alerts.pv.foundOne') : t('alerts.pv.found', { n: pv.total })}</p>
          <ul className="flex flex-col gap-2">
            {items.map((it) => (
              <li key={it.dedup_key} className="border border-line-soft rounded-sm p-3 bg-paper min-w-0">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <SeverityBadge severity={it.severity} />
                  {it.already_sent && <Badge tone="forest">{t('alerts.pv.alreadySent')}</Badge>}
                </div>
                <div className="font-medium break-words">{lang === 'it' ? it.title_it : it.title_en}</div>
                {!compact && <div className="text-sm text-charcoal-soft mt-0.5 break-words">{lang === 'it' ? it.body_it : it.body_en}</div>}
                <SourceLine className="mt-1" compact p={{ source: it.source, published_at: it.published_at, source_url: it.source_url }} />
              </li>
            ))}
          </ul>
          {pv.total > SHOWN && <p className="text-sm text-muted mt-2">{t('alerts.pv.more', { n: pv.total - SHOWN })}</p>}
        </>
      )}
      {pv.window_days && <p className="text-sm text-muted mt-2">{t('alerts.pv.window', { n: pv.window_days })}</p>}
      {pv.checked.length > 0 && (
        <div className="mt-3">
          <div className="eyebrow mb-1">{t('alerts.pv.checked')}</div>
          <ul className="text-[0.92rem]">
            {pv.checked.slice(0, compact ? 6 : 12).map((c, i) => <CheckRow key={i} c={c} kind={pv.alert_type} />)}
          </ul>
        </div>
      )}
    </div>
  )
}
