// Side panel used by the quote detail, the form and the comparison. Full screen on a phone,
// a wide panel on the right from 640 px up. Escape closes it (through `onClose`, which may ask
// first), focus moves into the panel and goes back to where it was when it closes.
import clsx from 'clsx'
import { X } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import { useI18n } from '@/i18n'

export function Drawer({ open, onClose, title, eyebrow, meta, actions, children, footer, size = 'lg', labelId, closeOnBackdrop = true }: {
  open: boolean
  onClose: () => void
  title: ReactNode
  eyebrow?: ReactNode
  meta?: ReactNode
  actions?: ReactNode
  children: ReactNode
  footer?: ReactNode
  size?: 'md' | 'lg' | 'xl'
  labelId: string
  closeOnBackdrop?: boolean
}) {
  const { t } = useI18n()
  const panel = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        close.current()
      }
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panel.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      previous?.focus?.()
    }
  }, [open])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-[1500] flex justify-end bg-charcoal/35"
      onMouseDown={(e) => { if (closeOnBackdrop && e.target === e.currentTarget) onClose() }}
    >
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
        className={clsx('flex h-full w-full min-w-0 flex-col bg-paper shadow-xl outline-none sm:border-l sm:border-line', {
          'sm:max-w-[min(760px,96vw)]': size === 'md',
          'sm:max-w-[min(940px,96vw)]': size === 'lg',
          'sm:max-w-[min(1180px,96vw)]': size === 'xl',
        })}
      >
        <header className="flex items-start justify-between gap-3 border-b border-line bg-white px-4 py-3 sm:px-6 sm:py-4">
          <div className="min-w-0">
            {eyebrow && <div className="eyebrow mb-0.5">{eyebrow}</div>}
            <h2 id={labelId} className="break-words font-serif text-[1.3rem] font-semibold leading-tight sm:text-[1.5rem]">{title}</h2>
            {meta && <div className="mt-1 text-[0.9rem] text-muted">{meta}</div>}
          </div>
          <button type="button" onClick={onClose} aria-label={t('ui.close')} title={t('ui.close')}
            className="-mr-1 shrink-0 rounded-sm p-1.5 text-muted hover:bg-paper hover:text-charcoal">
            <X size={22} />
          </button>
        </header>
        {actions && <div className="flex flex-wrap gap-2 border-b border-line-soft bg-white px-4 py-2.5 sm:px-6">{actions}</div>}
        <div className="min-w-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-6 sm:py-5">{children}</div>
        {footer && <div className="border-t border-line bg-white px-4 py-3 sm:px-6">{footer}</div>}
      </div>
    </div>
  )
}

/** A titled block inside a drawer. */
export function Section({ title, aside, children, className }: { title: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={clsx('mb-6 min-w-0', className)}>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-line-soft pb-1.5">
        <h3 className="font-serif text-[1.12rem] font-semibold text-charcoal">{title}</h3>
        {aside && <div className="text-[0.82rem] text-muted">{aside}</div>}
      </div>
      {children}
    </section>
  )
}
