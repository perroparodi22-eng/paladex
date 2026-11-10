// /avvisi — alert center: the alerts received (unread first) and the rules that produce them.
// Rules only report data that arrives after they start watching; every alert cites its source.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Plus, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useUnreadCount } from '@/components/alerts/AlertBell'
import { EventFeed, type FeedFilters } from '@/components/alerts/EventFeed'
import { RuleEditor } from '@/components/alerts/RuleEditor'
import { RuleList } from '@/components/alerts/RuleList'
import type { AlertEventItem, AlertRule, EventsResponse, OptionsResponse, RulesResponse } from '@/components/alerts/types'
import { Note, PageHeader, Panel, QueryState, StatTile } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtAgo, fmtDateTime } from '@/lib/format'
import { isMirror } from '@/lib/mirror'

export default function Alerts() {
  const { t, lang } = useI18n()
  const qc = useQueryClient()
  const [filters, setFilters] = useState<FeedFilters>({ status: 'all', type: '', page: 1 })
  const [editing, setEditing] = useState<AlertRule | 'new' | null>(null)

  const rules = useQuery({ queryKey: ['alerts', 'rules'], queryFn: () => api.get<RulesResponse>('/alerts/rules') })
  const events = useQuery({
    queryKey: ['alerts', 'events', filters],
    queryFn: () => api.get<EventsResponse>('/alerts/events', {
      status: filters.status, alert_type: filters.type || undefined, page: filters.page, page_size: 20,
    }),
    placeholderData: keepPreviousData,
  })
  // After alerts on the last page are marked as read (filter "to read"), that page no longer
  // exists: go back to the last page that does instead of showing an empty list without a pager.
  const lastPage = events.data && !events.isPlaceholderData && events.data.items.length === 0 && filters.page > 1
    ? Math.max(1, events.data.pages) : null
  useEffect(() => {
    if (lastPage !== null && lastPage < filters.page) setFilters((f) => ({ ...f, page: lastPage }))
  }, [lastPage, filters.page])
  const count = useUnreadCount()
  const options = useQuery({
    queryKey: ['alerts', 'options'], queryFn: () => api.get<OptionsResponse>('/alerts/options'),
    enabled: editing !== null, staleTime: 60_000,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['alerts'] })
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => api.put(`/alerts/rules/${id}`, { enabled }),
    onSuccess: invalidate,
  })
  const remove = useMutation({ mutationFn: (id: number) => api.del(`/alerts/rules/${id}`), onSuccess: invalidate })
  const mark = useMutation({
    mutationFn: (e: AlertEventItem) => api.put(`/alerts/events/${e.id}`, { read: !e.read }),
    onSuccess: invalidate,
  })
  const markAll = useMutation({ mutationFn: () => api.post('/alerts/events/read-all', {}), onSuccess: invalidate })
  const check = useMutation({
    mutationFn: () => api.post<{ new_events: number; failed: number[]; checked_at: string }>('/alerts/evaluate'),
    onSuccess: invalidate,
  })

  const ruleList = rules.data?.rules ?? []
  const active = ruleList.filter((r) => r.enabled).length
  const lastCheck = rules.data?.last_checked_at ?? null
  const busy = toggle.isPending || remove.isPending

  const edit = (r: AlertRule | 'new') => {
    setEditing(r)
    if (typeof window !== 'undefined') window.scrollTo(0, 0)
  }
  const del = (r: AlertRule) => {
    if (typeof window === 'undefined' || window.confirm(t('alerts.rules.confirmDelete', { name: r.name }))) remove.mutate(r.id)
  }
  const checkMsg = check.data
    ? check.data.new_events === 0 ? t('alerts.checkedNone')
      : check.data.new_events === 1 ? t('alerts.checkedOne') : t('alerts.checked', { n: check.data.new_events })
    : null

  return (
    <div>
      <PageHeader
        eyebrow={t('alerts.eyebrow')}
        title={t('alerts.title')}
        subtitle={t('alerts.subtitle')}
        actions={isMirror() ? undefined : (
          <>
            <button type="button" className="btn-secondary" onClick={() => check.mutate()} disabled={check.isPending}>
              <RefreshCw size={16} className={clsx(check.isPending && 'animate-spin')} />
              {check.isPending ? t('alerts.checking') : t('alerts.checkNow')}
            </button>
            <button type="button" className="btn-primary" onClick={() => edit('new')}>
              <Plus size={16} /> {t('alerts.newRule')}
            </button>
          </>
        )}
      />

      {checkMsg && <div className="mb-4"><Note>{checkMsg}</Note></div>}

      {editing !== null && (
        <RuleEditor key={editing === 'new' ? 'new' : editing.id} rule={editing === 'new' ? null : editing}
          options={options.data} optionsLoading={options.isLoading} onDone={() => setEditing(null)} />
      )}

      <div className="grid gap-4 sm:grid-cols-3 mb-6">
        <StatTile label={t('alerts.stat.unread')} value={count.data?.unread ?? '—'}
          sub={count.data && count.data.unread_warning > 0 ? t('alerts.stat.important', { n: count.data.unread_warning }) : undefined} />
        <StatTile label={t('alerts.stat.rules')} value={rules.data ? active : '—'}
          sub={rules.data ? t('alerts.stat.rulesOf', { n: ruleList.length }) : undefined} />
        <StatTile label={t('alerts.stat.lastCheck')}
          value={<span className="font-sans text-[1.45rem]" title={lastCheck ? fmtDateTime(lastCheck, lang) : undefined}>{lastCheck ? fmtAgo(lastCheck, lang) : t('alerts.never')}</span>}
          sub={t('alerts.stat.lastCheckSub')} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] items-start">
        <Panel title={t('alerts.feed.title')}>
          <QueryState q={events}>
            {(d) => (
              <EventFeed data={d} filters={filters} onFilters={(f) => setFilters((x) => ({ ...x, ...f }))}
                onToggleRead={(e) => mark.mutate(e)} onMarkAll={() => markAll.mutate()} busy={mark.isPending || markAll.isPending} />
            )}
          </QueryState>
        </Panel>
        <Panel title={t('alerts.rules.title')} footer={t('alerts.rules.how')}>
          <QueryState q={rules}>
            {(d) => (
              <RuleList rules={d.rules} busy={busy} onToggle={(r, enabled) => toggle.mutate({ id: r.id, enabled })}
                onEdit={(r) => edit(r)} onDelete={del} />
            )}
          </QueryState>
        </Panel>
      </div>
    </div>
  )
}
