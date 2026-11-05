// Alert feed: unread first, each alert with its figures, period, source and links.
import clsx from 'clsx'
import { ArrowRight, BellOff, CheckCheck, Circle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, DemoBadge, EmptyState, Segmented, Select, SourceLine } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtAgo, fmtDateTime } from '@/lib/format'
import { ALERT_TYPES, type AlertEventItem, type EventsResponse, type Severity } from './types'

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useI18n()
  const tone = severity === 'critical' ? 'down' : severity === 'warning' ? 'warn' : 'outline'
  return <Badge tone={tone}>{t(`alerts.sev.${severity}`)}</Badge>
}

export function EventCard({ e, onToggleRead, busy }: { e: AlertEventItem; onToggleRead?: (e: AlertEventItem) => void; busy?: boolean }) {
  const { t, lang } = useI18n()
  const title = lang === 'it' ? e.title_it : e.title_en
  const body = lang === 'it' ? e.body_it : e.body_en
  return (
    <article
      data-read={e.read ? 'true' : 'false'}
      className={clsx('rounded-sm border p-4 min-w-0', e.read ? 'border-line bg-white' : 'border-gold-light/60 border-l-[3px] border-l-gold bg-[#FFFCF4]')}
    >
      <div className="flex flex-wrap items-center gap-2 mb-1.5">
        {!e.read && (
          <span className="inline-flex items-center gap-1.5 text-[0.72rem] uppercase tracking-wide font-semibold text-gold-dark">
            <span className="h-2 w-2 rounded-full bg-gold" aria-hidden /> {t('alerts.feed.unreadLabel')}
          </span>
        )}
        <SeverityBadge severity={e.severity} />
        {e.alert_type && <Badge tone="outline">{t(`alerts.type.${e.alert_type}`)}</Badge>}
        {e.is_demo && <DemoBadge />}
        <span className="ml-auto text-sm text-muted whitespace-nowrap" title={fmtDateTime(e.triggered_at, lang)}>{fmtAgo(e.triggered_at, lang)}</span>
      </div>
      <h3 className={clsx('font-serif text-[1.08rem] leading-snug break-words', e.read ? 'font-medium text-charcoal-soft' : 'font-semibold')}>{title}</h3>
      {body && <p className="mt-1 text-[0.95rem] leading-relaxed text-charcoal-soft break-words">{body}</p>}
      <SourceLine
        className="mt-2"
        p={{ source: e.source, period_label: e.period_label ?? undefined, published_at: e.published_at,
          collected_at: e.collected_at, source_url: e.source_url ?? (e.link_internal ? null : e.link), is_demo: false }}
      />
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        {e.link && e.link_internal && (
          <Link to={e.link} className="link inline-flex items-center gap-1 text-[0.95rem]">
            {t('alerts.feed.openData')} <ArrowRight size={14} />
          </Link>
        )}
        <span className="text-sm text-muted break-words">{t('alerts.feed.rule', { name: e.rule_name ?? t('alerts.feed.ruleDeleted') })}</span>
        {onToggleRead && (
          <button type="button" className="btn-ghost !px-2 !py-1 text-sm ml-auto" disabled={busy} onClick={() => onToggleRead(e)}>
            {e.read ? <Circle size={15} /> : <CheckCheck size={15} />}
            {e.read ? t('alerts.feed.markUnread') : t('alerts.feed.markRead')}
          </button>
        )}
      </div>
    </article>
  )
}

export interface FeedFilters { status: 'all' | 'unread'; type: string; page: number }

export function EventFeed({ data, filters, onFilters, onToggleRead, onMarkAll, busy }: {
  data: EventsResponse
  filters: FeedFilters
  onFilters: (f: Partial<FeedFilters>) => void
  onToggleRead?: (e: AlertEventItem) => void
  onMarkAll?: () => void
  busy?: boolean
}) {
  const { t } = useI18n()
  const filtered = filters.status === 'unread' || filters.type !== ''
  return (
    <div>
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <Segmented
          value={filters.status}
          onChange={(status) => onFilters({ status, page: 1 })}
          options={[{ value: 'all', label: t('alerts.feed.all') }, { value: 'unread', label: `${t('alerts.feed.unread')} (${data.unread})` }]}
        />
        <Select aria-label={t('alerts.feed.anyType')} value={filters.type} onChange={(e) => onFilters({ type: e.target.value, page: 1 })}
          className="min-w-[11rem] flex-1 sm:flex-none">
          <option value="">{t('alerts.feed.anyType')}</option>
          {ALERT_TYPES.map((k) => <option key={k} value={k}>{t(`alerts.type.${k}`)}</option>)}
        </Select>
        {onMarkAll && data.unread > 0 && (
          <button type="button" className="btn-secondary ml-auto" onClick={onMarkAll} disabled={busy}>
            <CheckCheck size={16} /> {t('alerts.feed.markAll')}
          </button>
        )}
      </div>
      {data.items.length === 0 ? (
        filters.status === 'unread' && filters.type === '' ? (
          <EmptyState icon={<CheckCheck size={22} />} title={t('alerts.feed.emptyUnreadTitle')} hint={t('alerts.feed.emptyUnreadHint')} />
        ) : filtered ? (
          <EmptyState icon={<BellOff size={22} />} title={t('alerts.feed.emptyFilteredTitle')} hint={t('alerts.feed.emptyFilteredHint')} />
        ) : (
          <EmptyState icon={<BellOff size={22} />} title={t('alerts.feed.emptyTitle')} hint={t('alerts.feed.emptyHint')} />
        )
      ) : (
        <>
          <div className="text-sm text-muted mb-2">{data.total === 1 ? t('alerts.feed.countOne') : t('alerts.feed.count', { n: data.total })}</div>
          <div className="flex flex-col gap-3">
            {data.items.map((e) => <EventCard key={e.id} e={e} onToggleRead={onToggleRead} busy={busy} />)}
          </div>
          {data.pages > 1 && (
            <div className="flex items-center justify-between gap-3 mt-4">
              <button type="button" className="btn-secondary" disabled={filters.page <= 1} onClick={() => onFilters({ page: filters.page - 1 })}>
                {t('alerts.feed.prev')}
              </button>
              <span className="text-sm text-muted">{t('alerts.feed.page', { p: filters.page, n: data.pages })}</span>
              <button type="button" className="btn-secondary" disabled={filters.page >= data.pages} onClick={() => onFilters({ page: filters.page + 1 })}>
                {t('alerts.feed.next')}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
