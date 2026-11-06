// "Segnala o correggi" next to a figure: opens the figure's correction panel. Not shown in the
// read-only phone copy (it shows the "Corretto da …" badge only).
import clsx from 'clsx'
import { PenLine } from 'lucide-react'
import { useState } from 'react'
import { useI18n } from '@/i18n'
import { isMirror } from '@/lib/mirror'
import { CorrectionBadge } from './CorrectionBadge'
import { FigureDialog } from './FigureDialog'
import type { CorrectionBrief, FigureRef } from './types'

export function FixButton({ figure, correction, className, small = false, short = false }: {
  figure: FigureRef | null | undefined; correction?: CorrectionBrief | null; className?: string; small?: boolean; short?: boolean
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  if (!figure || isMirror()) return null
  return (
    <>
      <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(true) }}
        className={clsx('inline-flex items-center gap-1 text-forest-700 underline decoration-gold/50 underline-offset-2 hover:decoration-gold',
          small ? 'text-[0.8rem]' : 'text-[0.9rem]', className)}
        data-fix={figure.row_id}>
        <PenLine size={small ? 12 : 14} aria-hidden /> {short ? t('corrections.fixShort') : t('corrections.fix')}
      </button>
      {open && <FigureDialog figure={figure} correction={correction} open={open} onClose={() => setOpen(false)} />}
    </>
  )
}

/** In a table row: a short "Corretto da …" mark and "Segnala o correggi" (undo is in the panel). */
export function RowCorrection({ figure, correction }: { figure: FigureRef | null | undefined; correction?: CorrectionBrief | null }) {
  if (!figure && !correction) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
      {correction && <CorrectionBadge c={correction} compact />}
      <FixButton figure={figure} correction={correction} small short />
    </span>
  )
}
