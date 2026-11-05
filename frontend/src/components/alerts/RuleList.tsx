// The owner's rules: plain-language description, on/off switch, test, edit, delete.
import { useMutation } from '@tanstack/react-query'
import clsx from 'clsx'
import { FlaskConical, Pencil, Trash2 } from 'lucide-react'
import { Badge, ErrorBlock, Loading } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtAgo, fmtDate } from '@/lib/format'
import { PreviewResult } from './PreviewResult'
import type { AlertRule, PreviewResponse } from './types'

export function Switch({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={clsx('relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors disabled:opacity-50',
        on ? 'bg-forest-700 border-forest-700' : 'bg-line border-line')}
    >
      <span className={clsx('inline-block h-[18px] w-[18px] rounded-full bg-white shadow-sm transition-transform',
        on ? 'translate-x-[21px]' : 'translate-x-[2px]')} />
    </button>
  )
}

export function RuleCard({ rule, onToggle, onEdit, onDelete, busy }: {
  rule: AlertRule
  onToggle?: (r: AlertRule, enabled: boolean) => void
  onEdit?: (r: AlertRule) => void
  onDelete?: (r: AlertRule) => void
  busy?: boolean
}) {
  const { t, lang } = useI18n()
  const test = useMutation({ mutationFn: () => api.post<PreviewResponse>(`/alerts/rules/${rule.id}/test`) })
  const events = rule.events_total === 0 ? t('alerts.rules.noEvents')
    : rule.events_total === 1 ? t('alerts.rules.eventsOne') : t('alerts.rules.events', { n: rule.events_total })
  return (
    <li className={clsx('py-4 border-b border-line-soft last:border-0', !rule.enabled && 'opacity-80')}>
      <div className="flex items-start gap-3">
        <div className="pt-0.5">
          <Switch
            on={rule.enabled}
            disabled={busy || !onToggle}
            onChange={(v) => onToggle?.(rule, v)}
            label={rule.enabled ? t('alerts.rules.turnOff', { name: rule.name }) : t('alerts.rules.turnOn', { name: rule.name })}
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-[1.02rem] break-words">{rule.name}</span>
            {rule.is_example && <Badge tone="gold">{t('alerts.rules.example')}</Badge>}
            <Badge tone="outline">{t(`alerts.type.${rule.alert_type}`)}</Badge>
            <Badge tone={rule.enabled ? 'up' : 'neutral'}>{rule.enabled ? t('alerts.rules.on') : t('alerts.rules.off')}</Badge>
          </div>
          <p className="mt-1 text-[0.93rem] leading-relaxed text-charcoal-soft break-words">{lang === 'it' ? rule.description_it : rule.description_en}</p>
          <div className="mt-1 text-sm text-muted flex flex-wrap gap-x-2">
            {rule.watching_since && <span>{t('alerts.rules.since', { d: fmtDate(rule.watching_since, lang) })}</span>}
            <span>· {events}</span>
            {rule.events_unread > 0 && <span className="text-gold-dark font-medium">· {t('alerts.rules.unread', { n: rule.events_unread })}</span>}
            {rule.last_event_at && <span>· {t('alerts.rules.lastEvent', { d: fmtAgo(rule.last_event_at, lang) })}</span>}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" className="btn-secondary !px-2.5 !py-1 text-sm"
              onClick={() => (test.data || test.error ? test.reset() : test.mutate())} disabled={test.isPending}>
              <FlaskConical size={15} /> {test.data || test.error ? t('alerts.rules.hideTest') : t('alerts.rules.test')}
            </button>
            {onEdit && (
              <button type="button" className="btn-secondary !px-2.5 !py-1 text-sm" onClick={() => onEdit(rule)} disabled={busy}>
                <Pencil size={15} /> {t('ui.edit')}
              </button>
            )}
            {onDelete && (
              <button type="button" className="btn-ghost !px-2.5 !py-1 text-sm !text-down" onClick={() => onDelete(rule)} disabled={busy}>
                <Trash2 size={15} /> {t('ui.delete')}
              </button>
            )}
          </div>
          {(test.isPending || test.data || test.error) && (
            <div className="mt-3 border border-line-soft rounded-sm p-3 bg-white">
              <div className="eyebrow mb-1">{t('alerts.pv.title')}</div>
              <p className="text-sm text-muted mb-2">{t('alerts.pv.hint')}</p>
              {test.isPending ? <Loading label={t('alerts.pv.loading')} />
                : test.error ? <ErrorBlock error={test.error} onRetry={() => test.mutate()} />
                : test.data ? <PreviewResult pv={test.data} compact /> : null}
            </div>
          )}
        </div>
      </div>
    </li>
  )
}

export function RuleList({ rules, onToggle, onEdit, onDelete, busy }: {
  rules: AlertRule[]
  onToggle?: (r: AlertRule, enabled: boolean) => void
  onEdit?: (r: AlertRule) => void
  onDelete?: (r: AlertRule) => void
  busy?: boolean
}) {
  const { t } = useI18n()
  if (!rules.length) return <p className="text-muted py-4">{t('alerts.rules.empty')}</p>
  return (
    <ul>
      {rules.map((r) => <RuleCard key={r.id} rule={r} onToggle={onToggle} onEdit={onEdit} onDelete={onDelete} busy={busy} />)}
    </ul>
  )
}
