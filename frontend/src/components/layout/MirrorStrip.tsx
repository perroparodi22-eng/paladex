// Read-only online copy (lib/mirror.ts): the strip at the top of every page that says when the
// copy's data was collected, and the notice shown instead of the tools the copy does not contain.
import clsx from 'clsx'
import { AlertTriangle, Eye } from 'lucide-react'
import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { parseBackendDate } from '@/lib/format'
import { copyAgeHours, isMirror, MIRROR_HIDDEN_ROUTES, useMirrorManifest } from '@/lib/mirror'
import type { Lang } from '@/lib/types'

/** The copy is refreshed every morning: older than this, the strip turns into a warning. */
export const STALE_AFTER_HOURS = 36
/** No successful check of the sources for this long: the strip warns even if the copy is new. */
export const DATA_STALE_AFTER_HOURS = 72

/** "4 nov 2026 22:40" / "4 Nov 2026 22:40" in the viewer's time zone. */
export function fmtStripDate(iso: string, lang: Lang): string {
  const d = parseBackendDate(iso)
  if (Number.isNaN(d.getTime())) return iso
  const loc = lang === 'it' ? 'it-IT' : 'en-GB'
  const day = new Intl.DateTimeFormat(loc, { day: 'numeric', month: 'short', year: 'numeric' }).format(d)
  const time = new Intl.DateTimeFormat(loc, { hour: '2-digit', minute: '2-digit' }).format(d)
  return `${day} ${time}`
}

export function MirrorStrip() {
  const { t, lang } = useI18n()
  const m = useMirrorManifest()

  // Each daily refresh replaces the scripts of the previous copy: a page left open across a
  // refresh reloads itself instead of failing to open a section.
  useEffect(() => {
    const reload = () => window.location.reload()
    window.addEventListener('vite:preloadError', reload)
    return () => window.removeEventListener('vite:preloadError', reload)
  }, [])

  const age = copyAgeHours(m.data)
  const collected = m.data?.data_collected_until
  // The copy itself is late (the daily refresh stopped), or it is fresh but the sources have not
  // answered for days (the collection keeps failing): either way the data must not look current.
  const copyStale = age !== null && age >= STALE_AFTER_HOURS
  const dataAge = collected ? copyAgeHours({ generated_at: collected }) : null
  const dataStale = !copyStale && dataAge !== null && dataAge >= DATA_STALE_AFTER_HOURS
  const stale = copyStale || dataStale
  const days = Math.floor((copyStale ? age ?? 0 : dataAge ?? 0) / 24)
  const produced = m.data?.generated_at ? t('mirror.produced', { when: fmtStripDate(m.data.generated_at, lang) }) : undefined
  return (
    <div role="note" title={produced}
      className={clsx('flex items-start gap-1.5 px-3 sm:px-4 md:px-8 py-1 text-[0.76rem] leading-snug border-b',
        stale ? 'bg-[#FBF0DC] text-[#7A5414] border-[#EED9B0]' : 'bg-forest-800 text-ivory border-forest-700')}>
      {stale ? <AlertTriangle size={13} className="mt-[2px] shrink-0" /> : <Eye size={13} className="mt-[2px] shrink-0 text-gold-light" />}
      <span>
        <span className="font-semibold">{t('mirror.strip')}</span>
        <span aria-hidden> · </span>
        {collected ? t('mirror.collected', { when: fmtStripDate(collected, lang) }) : m.isLoading ? '…' : t('mirror.collectedUnknown')}
        {stale ? (
          <><span aria-hidden> · </span><strong>{dataStale ? t('mirror.dataStale', { n: days })
            : days <= 1 ? t('mirror.stale1') : t('mirror.stale', { n: days })}</strong></>
        ) : (
          <span className="hidden sm:inline"><span aria-hidden> · </span>{t('mirror.daily')}</span>
        )}
      </span>
    </div>
  )
}

/** In the online copy: is this address one of the tools the copy does not contain? */
export function mirrorHidesRoute(pathname: string): boolean {
  return isMirror() && MIRROR_HIDDEN_ROUTES.some((r) => pathname === r || pathname.startsWith(`${r}/`))
}

/** Shown in the online copy instead of a tool that only exists on the computer. */
export function NotInCopy() {
  const { t } = useI18n()
  return (
    <Panel>
      <EmptyState title={t('mirror.missingTitle')} hint={t('mirror.missing')}
        action={<Link to="/" className="btn-secondary">{t('later.notfoundHome')}</Link>} />
    </Panel>
  )
}
