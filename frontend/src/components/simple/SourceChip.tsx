// The simple view's provenance: a compact chip "Fonte: USDA · set 2026" under a figure that opens
// (tap or click) to the full provenance line — publisher and full source name, period, publication
// date, when it was collected, the figure's full technical label and the link to the original.
// `actions` is the place for actions on the figure (e.g. "Segnala o correggi").
import clsx from 'clsx'
import { ChevronDown, ExternalLink } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { DemoBadge, StatusBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtAgo, fmtDate, fmtPeriod } from '@/lib/format'
import { isMappedUrl, pageUrl } from '@/lib/links'
import { sourceName } from '@/lib/meta'
import { shortSource } from '@/lib/plain'
import type { CorrectionInfo, SourceBrief } from '@/lib/types'
import { CorrectionBadge } from '@/components/corrections/CorrectionBadge'
import { FixButton } from '@/components/corrections/FixButton'
import type { FigureRef } from '@/components/corrections/types'

export interface ChipProv {
  source: SourceBrief | null
  /** period of the figure ("2026-09"), shown with fmtPeriod */
  period_label?: string | null
  /** the period already in words ("gen–set 2026"), when it is not a single period label */
  period_text?: string | null
  published_at?: string | null
  collected_at?: string | null
  source_url?: string | null
  data_status?: string | null
  is_demo?: boolean
  /** the figure's full technical label, as the source and the full view name it */
  technical?: string | null
  /** one more line of explanation (e.g. how a change is computed) */
  note?: string | null
  /** a value corrected by a person: "Corretto da … il …" under the chip, with undo */
  correction?: CorrectionInfo | null
}

const SHOWN_STATUS = (s: string | null | undefined) => Boolean(s) && !['published', 'live', 'demo'].includes(s as string)

/** `figure`: the stored row behind the figure, when it is one row: "Segnala o correggi" in the details. */
export function SourceChip({ p, actions, defaultOpen = false, className, figure }: {
  p: ChipProv; actions?: ReactNode; defaultOpen?: boolean; className?: string; figure?: FigureRef | null
}) {
  const { t, lang } = useI18n()
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  const period = p.period_text ?? (p.period_label ? fmtPeriod(p.period_label, lang) : null)
  const short = shortSource(p.source, lang)
  const full = p.source ? sourceName(p.source, lang) : null
  const href = p.source_url ? pageUrl(p.source_url) : undefined
  return (
    <div className={clsx('min-w-0', className)} data-source-chip>
      <span className="inline-flex max-w-full flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={id}
          title={t('simple.chip.open')}
          className={clsx(
            'inline-flex max-w-full items-center gap-1 rounded-full border px-2.5 py-[3px] text-left text-[0.84rem] leading-snug transition-colors',
            open ? 'border-forest-700 bg-forest-50 text-forest-900' : 'border-line bg-paper text-charcoal-soft hover:border-forest-300 hover:bg-forest-50',
          )}
        >
          <span className="min-w-0 break-words">
            {t('simple.chip.source')}: <span className="font-medium">{short}</span>{period ? <> · <span className="tabular-nums">{period}</span></> : null}
          </span>
          <ChevronDown size={14} className={clsx('shrink-0 transition-transform', open && 'rotate-180')} aria-hidden />
        </button>
        {p.is_demo && <DemoBadge />}
        {!p.is_demo && SHOWN_STATUS(p.data_status) && !(p.correction && p.data_status === 'user_entered') && <StatusBadge status={p.data_status as string} />}
      </span>
      {p.correction && <CorrectionBadge c={p.correction} className="mt-1.5" />}
      {open && (
        <div id={id} className="mt-1.5 rounded-sm border border-line-soft bg-white px-3 py-2.5 text-[0.86rem] leading-relaxed text-charcoal-soft shadow-panel">
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
            <dt className="text-muted">{t('prov.source')}</dt>
            <dd className="min-w-0 break-words">
              <span className="font-medium text-charcoal">{p.source?.publisher || full || '—'}</span>
              {full && p.source?.publisher && full !== p.source.publisher && <span className="block text-muted">{full}</span>}
            </dd>
            {period && (<><dt className="text-muted">{t('prov.period')}</dt><dd className="tabular-nums">{period}</dd></>)}
            <dt className="text-muted">{t('simple.chip.published')}</dt>
            <dd>{p.published_at ? fmtDate(p.published_at, lang) : t('simple.chip.noDate')}</dd>
            {p.collected_at && (
              <><dt className="text-muted">{t('simple.chip.collected')}</dt><dd>{fmtAgo(p.collected_at, lang)} ({fmtDate(p.collected_at, lang)})</dd></>
            )}
            {p.technical && (<><dt className="text-muted">{t('simple.chip.technical')}</dt><dd className="min-w-0 break-words">{p.technical}</dd></>)}
            {SHOWN_STATUS(p.data_status) && (<><dt className="text-muted">{t('simple.chip.status')}</dt><dd><StatusBadge status={p.data_status as string} /></dd></>)}
          </dl>
          {p.note && <p className="mt-1.5 text-muted">{p.note}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5">
            {href ? (
              <a href={href} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1"
                title={p.source_url && isMappedUrl(p.source_url) ? t('prov.exactAddress', { url: p.source_url }) : undefined}>
                {t(p.source_url && isMappedUrl(p.source_url) ? 'prov.officialPage' : 'prov.original')} <ExternalLink size={13} />
              </a>
            ) : p.source?.homepage ? (
              <a href={p.source.homepage} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1">
                {t('simple.chip.homepage')} <ExternalLink size={13} />
              </a>
            ) : null}
            {actions}
            <FixButton figure={figure} correction={p.correction} />
          </div>
        </div>
      )}
    </div>
  )
}
