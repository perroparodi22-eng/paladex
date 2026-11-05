// Top-bar bell: number of unread alerts, links to /avvisi (red when an important one is unread).
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bell } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import type { UnreadCount } from './types'

export const UNREAD_KEY = ['alerts', 'unread-count'] as const

export function useUnreadCount() {
  return useQuery({
    queryKey: UNREAD_KEY,
    queryFn: () => api.get<UnreadCount>('/alerts/unread-count'),
    refetchInterval: 60_000,
  })
}

export function AlertBell() {
  const { t } = useI18n()
  const q = useUnreadCount()
  const n = q.data?.unread ?? 0
  const important = (q.data?.unread_warning ?? 0) > 0
  const label = n > 0 ? t('alerts.bell.label', { n }) : t('alerts.bell.none')
  return (
    <Link to="/avvisi" aria-label={label} title={label}
      className="relative inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-sm border border-line bg-white text-forest-800 hover:border-forest-600">
      <Bell size={18} />
      {n > 0 && (
        <span className={clsx('num absolute -top-1.5 -right-1.5 min-w-[1.25rem] h-5 px-1 rounded-full text-[0.7rem] font-semibold leading-5 text-center',
          important ? 'bg-down text-white' : 'bg-gold text-forest-950')}>
          {n > 99 ? '99+' : n}
        </span>
      )}
    </Link>
  )
}
