import { Info, WifiOff } from 'lucide-react'
import { useI18n } from '@/i18n'
import { fmtDateTime } from '@/lib/format'
import type { CollectState } from '@/lib/types'

// Statuses that mean "this computer reached the sources" (offline runs do not count).
const CHECKED = ['success', 'no_change', 'partial', 'failed', 'skipped']

/** Explains the first minutes after installation: the real starter data shown while this
 *  computer's first collection runs, or why there is no data yet. Hidden afterwards. */
export function FirstRunBanner({ status }: { status: CollectState | undefined }) {
  const { t, lang } = useI18n()
  const fr = status?.first_run
  if (!fr) return null
  const running = status?.running ?? false
  const runs = fr.local_runs ?? {}
  const checked = CHECKED.some((k) => (runs[k] ?? 0) > 0)
  const offline = !checked && (runs.offline ?? 0) > 0

  let key: string | null = null
  if (fr.starter && (running || !checked)) {
    key = running ? 'firstrun.starterUpdating' : offline ? 'firstrun.starterOffline' : 'firstrun.starterWaiting'
  } else if (!fr.has_data) {
    key = running ? 'firstrun.collecting' : offline ? 'firstrun.offline' : 'firstrun.empty'
  }
  if (!key) return null
  const warn = key === 'firstrun.offline' || key === 'firstrun.starterOffline'
  const Icon = warn ? WifiOff : Info
  return (
    <div
      role="status"
      className={
        'flex items-start gap-2 px-8 py-2 text-[0.85rem] leading-snug border-b border-line ' +
        (warn ? 'bg-[#FBF1E6] text-[#7A4A12]' : 'bg-[#EEF3EC] text-forest')
      }
    >
      <Icon size={16} className="mt-[2px] shrink-0" />
      <span>{t(key, { date: fmtDateTime(fr.starter?.data_collected_until, lang) })}</span>
    </div>
  )
}
