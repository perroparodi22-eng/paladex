// "Vista: Semplice | Completa" — the header switch between the simple view (default) and the full
// view (lib/view.tsx). Two buttons with aria-pressed, readable at phone width.
import clsx from 'clsx'
import { useI18n } from '@/i18n'
import { useView, type View } from '@/lib/view'

/** `label`: show the word "Vista" always, only on wide screens, or never (screen readers still get it). */
export function ViewSwitch({ label = 'wide', small = false, className }: {
  label?: 'always' | 'wide' | 'hidden'; small?: boolean; className?: string
}) {
  const { t } = useI18n()
  const { view, setView } = useView()
  const options: { value: View; label: string; title: string }[] = [
    { value: 'simple', label: t('simple.switch.simple'), title: t('simple.switch.simpleTitle') },
    { value: 'full', label: t('simple.switch.full'), title: t('simple.switch.fullTitle') },
  ]
  return (
    <div className={clsx('flex items-center gap-2', className)} role="group" aria-label={t('simple.switch.label')} data-view-switch={view}>
      <span className={clsx('whitespace-nowrap text-sm text-muted', label === 'hidden' ? 'sr-only' : label === 'wide' && 'max-lg:sr-only')}>
        {t('simple.switch.label')}:
      </span>
      <div className="inline-flex overflow-hidden rounded-sm border border-line bg-white">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={view === o.value}
            title={o.title}
            onClick={() => setView(o.value)}
            className={clsx(
              'border-r border-line last:border-r-0 font-medium transition-colors',
              small ? 'px-2 py-1.5 text-[0.82rem]' : 'px-3 py-1.5 text-[0.9rem]',
              view === o.value ? 'bg-forest-800 text-ivory' : 'text-charcoal-soft hover:bg-forest-50',
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}
