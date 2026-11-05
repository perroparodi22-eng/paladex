// Small building blocks shared by the price components.
import clsx from 'clsx'
import { ExternalLink } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { useI18n } from '@/i18n'
import { fmtPct } from '@/lib/format'
import type { MassUnit, PointRef } from './types'
import { fmtPeriodLabel, fmtPrice, toUnit } from './utils'

/** Coloured ▲▼ change with a tooltip naming the exact comparison period; "—" when not computable. */
export function Change({ pct, cmp, expectedLabel, unit, unitText }: {
  pct: number | null; cmp: PointRef | null; expectedLabel: string; unit: MassUnit; unitText: string
}) {
  const { t, lang } = useI18n()
  if (pct === null || cmp === null) {
    return (
      <span className="num text-muted" title={t('prices.latest.noCompare', { p: fmtPeriodLabel(expectedLabel, lang) })}>—</span>
    )
  }
  const title = t('prices.latest.vs', {
    p: fmtPeriodLabel(cmp.period_label, lang),
    v: `${fmtPrice(toUnit(cmp.value, unit), lang)} ${unitText}`,
  })
  return (
    <span title={title} className={clsx('num whitespace-nowrap', pct > 0 ? 'text-up' : pct < 0 ? 'text-down' : 'text-muted')}>
      <span className="text-[0.7rem] mr-0.5 align-[1px]">{pct > 0 ? '▲' : pct < 0 ? '▼' : '■'}</span>
      {fmtPct(pct, lang, 1)}
    </span>
  )
}

/** Labelled control group used in the filter bar. */
export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={clsx('flex flex-col gap-1 min-w-0', className)}>
      <span className="text-[0.78rem] font-medium text-muted uppercase tracking-[0.08em]">{label}</span>
      {children}
    </div>
  )
}

/** Toggle chip (origins). */
export function Chip({ active, onClick, children, title, muted }: {
  active: boolean; onClick: () => void; children: ReactNode; title?: string; muted?: boolean
}) {
  return (
    <button
      type="button"
      title={title}
      aria-pressed={active}
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-1 text-[0.92rem] leading-tight transition-colors',
        active ? 'border-forest-700 bg-forest-800 text-ivory' : 'border-line bg-white text-charcoal-soft hover:border-forest-600 hover:text-forest-800',
        muted && !active && 'text-muted',
      )}
    >
      {children}
    </button>
  )
}

/** Small external-document link, or a muted dash with an explanation when there is none. */
export function DocLink({ url, label }: { url: string | null | undefined; label?: string }) {
  const { t } = useI18n()
  if (!url) return <span className="text-muted" title={t('prices.latest.noDoc')}>—</span>
  return (
    <a href={url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1" title={t('prov.original')}>
      {label}
      <ExternalLink size={14} />
    </a>
  )
}

/** Colour swatch used for chart identity (line legend, table toggle). */
export function Swatch({ color, on, size = 12 }: { color?: string; on: boolean; size?: number }) {
  return (
    <span
      aria-hidden
      className="inline-block shrink-0 rounded-[2px] border"
      style={{
        width: size, height: size,
        background: on && color ? color : 'transparent',
        borderColor: on && color ? color : '#C9C2AE',
      }}
    />
  )
}

/** True while the element is wider than its box (a table that has to scroll sideways). `dep` re-runs
 * the check when the content changes. */
export function useOverflows<T extends HTMLElement>(dep: unknown): [RefObject<T>, boolean] {
  const ref = useRef<T>(null)
  const [overflows, setOverflows] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const check = () => setOverflows(el.scrollWidth > el.clientWidth + 1)
    check()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(check)
    ro.observe(el)
    if (el.firstElementChild) ro.observe(el.firstElementChild)
    return () => ro.disconnect()
  }, [dep])
  return [ref, overflows]
}

/** Shown above a table only while some of its columns are off-screen. */
export function ScrollHint() {
  const { t } = useI18n()
  return <div className="px-4 py-1.5 text-[0.8rem] text-muted border-b border-line-soft">{t('prices.latest.scrollHint')}</div>
}
