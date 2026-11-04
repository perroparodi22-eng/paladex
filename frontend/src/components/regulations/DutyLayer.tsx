// One published duty layer (MFN, preference, quota, additional duty ...) with its official links,
// validity and the "da verificare" flag; tariff quotas carry a fill bar.
import clsx from 'clsx'
import { ExternalLink } from 'lucide-react'
import { Badge, DemoBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate } from '@/lib/format'
import { fmtDuty, fmtKg, fmtPct, isChapter99, legalLabel } from './format'
import type { DutyRow, Quota } from './types'

const QUOTA_TONE: Record<string, 'up' | 'warn' | 'down' | 'outline'> = {
  open: 'up', critical: 'warn', exhausted: 'down', blocked: 'down',
}

// `staleAsOf`: the layer was not re-confirmed by the latest read; the balance is dated so it never
// reads as current under the newer date of its cell.
export function QuotaBar({ quota, staleAsOf }: { quota: Quota; staleAsOf?: string | null }) {
  const { t, lang } = useI18n()
  const fill = quota.fill_pct
  const width = fill === null ? 0 : Math.min(100, Math.max(0, fill))
  const status = quota.status ?? ''
  const statusKey = `regulations.quota.status.${status}`
  const statusLabel = t(statusKey) === statusKey ? status : t(statusKey)
  return (
    <div className="mt-1 space-y-1">
      {fill !== null ? (
        <>
          <div className="flex items-center gap-2">
            <div className="relative h-2 flex-1 overflow-hidden rounded-sm border border-line bg-paper"
              role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(width)}
              aria-label={t('regulations.quota.used', { pct: fmtPct(fill, lang) })}>
              <div className={clsx('absolute inset-y-0 left-0', width >= 90 ? 'bg-down' : width >= 70 ? 'bg-gold' : 'bg-forest-600')}
                style={{ width: `${width}%` }} />
            </div>
            <span className="num shrink-0 text-[0.82rem] text-charcoal-soft">{t('regulations.quota.used', { pct: fmtPct(fill, lang) })}</span>
          </div>
          <div className="num text-[0.8rem] text-muted">
            {t('regulations.quota.balance', { balance: fmtKg(quota.balance_kg, lang), volume: fmtKg(quota.volume_kg, lang) })}
            {staleAsOf && <span className="text-warn"> · {t('regulations.quota.balanceAsOf', { date: fmtDate(staleAsOf, lang) })}</span>}
          </div>
        </>
      ) : (
        <div className="text-[0.8rem] text-muted">{t('regulations.quota.noFigures')}</div>
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.78rem] text-muted">
        {status && <Badge tone={QUOTA_TONE[status] ?? 'outline'}>{statusLabel}</Badge>}
        <span>{t('regulations.quota.order', { n: quota.order_number })}</span>
        {quota.shared_by_group && <span>· {t('regulations.quota.shared')}</span>}
      </div>
      {(quota.period_start || quota.last_allocation_date) && (
        <div className="text-[0.78rem] text-muted">
          {quota.period_start && quota.period_end
            && t('regulations.quota.period', { from: fmtDate(quota.period_start, lang), to: fmtDate(quota.period_end, lang) })}
          {quota.period_start && quota.last_allocation_date && ' · '}
          {quota.last_allocation_date && t('regulations.quota.lastAllocation', { date: fmtDate(quota.last_allocation_date, lang) })}
        </div>
      )}
    </div>
  )
}

export function useLayerLabel() {
  const { t } = useI18n()
  return (r: DutyRow): string => {
    if (r.measure_type === 'mfn') return t(r.jurisdiction === 'EU' ? 'regulations.layer.mfnEU' : 'regulations.layer.mfnUS')
    if (isChapter99(r)) return t('regulations.layer.ch99', { code: r.measure_code ?? '' })
    const base = t(`regulations.layer.${r.measure_type}`)
    const extra = r.extra ?? {}
    if (r.measure_type === 'preference' && r.jurisdiction === 'US') {
      const codes = (extra.program_codes as string[] | undefined)?.join(', ')
      const names = (extra.program_names as string[] | undefined)?.join('; ')
      return codes ? `${base} · ${t('regulations.layer.program', { codes })}${names ? ` (${names})` : ''}` : base
    }
    const geo = extra.geo_area as { description?: string | null; group?: boolean } | undefined
    if (geo?.group && geo.description && r.scope === 'origin') return `${base} · ${geo.description}`
    if (r.measure_type === 'other' && r.description) return `${base} · ${r.description}`
    return base
  }
}

export function DutyLayer({ row, general }: { row: DutyRow; general?: string }) {
  const { t, lang } = useI18n()
  const label = useLayerLabel()
  const legal = legalLabel(row)
  const duty = fmtDuty(row, lang, t('regulations.duty.free'))
  return (
    <div className="py-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 text-[0.86rem] leading-snug text-charcoal-soft" title={row.description ?? undefined}>
          {label(row)}
          {row.measure_type === 'trq_in' && <span className="text-muted"> · {t('regulations.quota.inQuota')}</span>}
          {general && <span className="block text-[0.78rem] text-muted">{general}</span>}
        </span>
        <span className={clsx('num shrink-0 text-[1.02rem]', row.needs_review ? 'text-muted' : 'text-charcoal')}
          title={row.duty_text ? t('regulations.duties.publishedText', { text: row.duty_text }) : undefined}>
          {duty}
        </span>
      </div>
      {row.stale && (
        <div className="mt-0.5 text-[0.78rem] text-warn">
          {t('regulations.duties.verified', { date: fmtDate(row.as_of, lang) })} · {t('regulations.duties.notReconfirmed')}
        </div>
      )}
      {row.quota && <QuotaBar quota={row.quota} staleAsOf={row.stale ? row.as_of : null} />}
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.78rem] text-muted">
        {row.is_demo && <DemoBadge />}
        {row.needs_review && (
          <Badge tone="warn" title={t('regulations.duties.reviewTitle', { reason: row.review_reason ?? t('regulations.duties.reviewGeneric') })}>
            {t('regulations.duties.review')}
          </Badge>
        )}
        {row.legal_url && legal && (
          <a href={row.legal_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5"
            title={t('regulations.duties.legalLinkTitle')}>
            {row.jurisdiction === 'EU' ? t('regulations.duties.legalLink', { ref: legal }) : legal} <ExternalLink size={11} />
          </a>
        )}
        {!row.legal_url && row.consult_url && (
          <a href={row.consult_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">
            {t('regulations.duties.consultLink')} <ExternalLink size={11} />
          </a>
        )}
        {row.valid_from && <span>{t('regulations.duties.validFrom', { date: fmtDate(row.valid_from, lang) })}</span>}
        {row.valid_to && <span>{t('regulations.duties.validTo', { date: fmtDate(row.valid_to, lang) })}</span>}
      </div>
    </div>
  )
}
