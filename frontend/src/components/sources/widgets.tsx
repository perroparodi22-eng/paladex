// Small interaction widgets used on the Sources page: on/off switch, confirmation dialog, notice line.
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, X } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import { useI18n } from '@/i18n'

export function Switch({ checked, onChange, label, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2 text-sm text-charcoal-soft disabled:opacity-50"
    >
      <span className={clsx('relative inline-flex h-[22px] w-[40px] shrink-0 rounded-full border transition-colors',
        checked ? 'bg-forest-700 border-forest-700' : 'bg-line-soft border-line')}>
        <span className={clsx('absolute top-[2px] h-4 w-4 rounded-full bg-white shadow-panel transition-transform',
          checked ? 'translate-x-[20px]' : 'translate-x-[2px]')} />
      </span>
      <span>{label}</span>
    </button>
  )
}

export function ConfirmDialog({ open, title, body, confirmLabel, danger, busy, onConfirm, onCancel }: {
  open: boolean; title: string; body: ReactNode; confirmLabel: string; danger?: boolean; busy?: boolean
  onConfirm: () => void; onCancel: () => void
}) {
  const { t } = useI18n()
  const confirmRef = useRef<HTMLButtonElement>(null)
  const cancelRef = useRef(onCancel)
  cancelRef.current = onCancel
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    confirmRef.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') cancelRef.current() }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
  }, [open])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-charcoal/40 px-4" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="panel w-full max-w-lg shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 px-6 pt-5">
          <h2 id="confirm-title" className="font-serif text-xl font-semibold">{title}</h2>
          <button className="text-muted hover:text-charcoal" onClick={onCancel} aria-label={t('ui.close')}><X size={20} /></button>
        </div>
        <div className="px-6 pt-3 pb-5 text-charcoal-soft leading-relaxed">{body}</div>
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-line-soft bg-paper">
          <button className="btn-secondary" onClick={onCancel}>{t('ui.cancel')}</button>
          <button
            ref={confirmRef}
            className={clsx(danger ? 'btn bg-down text-white border-down hover:bg-[#8a2f22]' : 'btn-primary')}
            onClick={onConfirm}
            disabled={busy}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/** Result of an action ("Aggiornamento avviato", "Già in corso"...). Announced to screen readers. */
export function Notice({ notice, onClose }: { notice: { tone: 'ok' | 'warn'; text: string } | null; onClose: () => void }) {
  const { t } = useI18n()
  if (!notice) return <div aria-live="polite" className="sr-only" />
  return (
    <div aria-live="polite" className={clsx('flex items-center gap-2 rounded-sm border px-4 py-2.5 text-[0.95rem]',
      notice.tone === 'ok' ? 'border-forest-100 bg-forest-50 text-forest-800' : 'border-[#EED9B0] bg-[#FBF5E8] text-[#7A5414]')}>
      {notice.tone === 'ok' ? <CheckCircle2 size={18} className="shrink-0" /> : <AlertTriangle size={18} className="shrink-0" />}
      <span className="flex-1">{notice.text}</span>
      <button onClick={onClose} className="opacity-70 hover:opacity-100" aria-label={t('ui.close')}><X size={16} /></button>
    </div>
  )
}
