// "Corretto da Papà il 6 nov 2026" on a figure whose value a person corrected: the official value it
// replaced, the reason, and "Annulla correzione" (a new revision with the official value back). The
// read-only phone copy shows the badge but no action.
import clsx from 'clsx'
import { PenLine, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { useI18n } from '@/i18n'
import { fmtDate } from '@/lib/format'
import { isMirror } from '@/lib/mirror'
import { errorText, useRevert } from './api'
import { fmtFigureValue } from './format'
import type { CorrectionBrief } from './types'

export function CorrectionBadge({ c, compact = false, className }: { c: CorrectionBrief | null | undefined; compact?: boolean; className?: string }) {
  const { t, lang } = useI18n()
  const revert = useRevert()
  const [asking, setAsking] = useState(false)
  if (!c) return null
  const who = c.author || t('corrections.someone')
  const when = c.created_at ? fmtDate(c.created_at, lang, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
  const official = fmtFigureValue(c.official_value, c.unit, c.currency, lang)
  const title = t('corrections.badge.title', { who, when, official })
  return (
    <div className={clsx('min-w-0 text-[0.86rem]', className)} data-correction={c.event_id}>
      <span className={clsx('inline-flex max-w-full items-center gap-x-1.5 gap-y-1 rounded-sm border border-[#C9DAEA] bg-[#EDF3F9] text-[#24507A]',
        compact ? 'whitespace-nowrap px-1.5 py-[1px] text-[0.78rem]' : 'flex-wrap px-2 py-[3px]')} title={title}>
        <PenLine size={compact ? 11 : 13} className="shrink-0" aria-hidden />
        <span className="font-medium">{compact ? t('corrections.badge.byShort', { who }) : t('corrections.badge.by', { who, when })}</span>
        {!compact && (
          <span className="text-[#3B6890]">· {c.part_of_total ? t('corrections.badge.partOf', { n: c.rows ?? 1 }) : t('corrections.badge.official', { v: official })}</span>
        )}
      </span>
      {!compact && c.reason && <span className="ml-1.5 text-muted">«{c.reason}»</span>}
      {!isMirror() && !compact && (
        asking ? (
          <span className="ml-2 inline-flex flex-wrap items-center gap-2">
            <span className="text-charcoal-soft">{t('corrections.badge.confirmUndo', { official })}</span>
            <button type="button" className="btn-secondary !px-2 !py-0.5 !text-[0.85rem]" disabled={revert.isPending}
              onClick={() => revert.mutate({ eventId: c.event_id }, { onSuccess: () => setAsking(false) })}>
              {t('corrections.badge.yesUndo')}
            </button>
            <button type="button" className="link text-[0.85rem]" onClick={() => setAsking(false)}>{t('corrections.cancel')}</button>
          </span>
        ) : (
          <button type="button" className="ml-2 inline-flex items-center gap-1 text-[0.85rem] text-forest-700 underline decoration-gold/50 underline-offset-2 hover:decoration-gold"
            onClick={() => setAsking(true)}>
            <Undo2 size={13} aria-hidden /> {t('corrections.badge.undo')}
          </button>
        )
      )}
      {revert.error && <span className="ml-2 text-down">{errorText(revert.error, lang)}</span>}
    </div>
  )
}

/** The same mark where only a label is known ("Corretto da Papà il 6 nov 2026", e.g. the assistant's
 * facts), in the badge's colours: a person's correction, never mistaken for an AI text. */
export function CorrectedTag({ label, title, className }: { label: string; title?: string; className?: string }) {
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-sm border border-[#C9DAEA] bg-[#EDF3F9] px-1.5 py-[1px] text-[0.78rem] font-medium text-[#24507A]', className)}
      title={title} data-corrected-tag>
      <PenLine size={11} aria-hidden /> {label}
    </span>
  )
}
