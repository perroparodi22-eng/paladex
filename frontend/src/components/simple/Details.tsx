// "Mostra dettagli" in the simple view: what the full view shows (filters, long tables, secondary
// sections) stays one click away. The content mounts only when opened, so its data is fetched only
// when asked for.
import clsx from 'clsx'
import { ChevronDown } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { useI18n } from '@/i18n'

export function Details({ children, label, hideLabel, defaultOpen = false, className, hint, bare = false }: {
  children: ReactNode; label?: string; hideLabel?: string; defaultOpen?: boolean; className?: string; hint?: string
  /** no separating line above (the page header already draws one) */
  bare?: boolean
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  return (
    <section className={clsx('mt-6', className)} data-details={open ? 'open' : 'closed'}>
      <div className={clsx('flex flex-wrap items-center gap-x-3 gap-y-1', !bare && 'border-t border-line pt-4')}>
        <button type="button" className="btn-secondary !text-[1rem]" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
          <ChevronDown size={17} className={clsx('transition-transform', open && 'rotate-180')} aria-hidden />
          {open ? (hideLabel ?? t('simple.details.hide')) : (label ?? t('simple.details.show'))}
        </button>
        {hint && !open && <span className="text-[0.9rem] text-muted">{hint}</span>}
      </div>
      {open && <div id={id} className="mt-5">{children}</div>}
    </section>
  )
}
