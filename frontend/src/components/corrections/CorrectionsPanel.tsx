// The corrections, flags and notes made by people, newest first, each with what happened to it:
// applied, undone, replaced by a newer correction, the source published a new value (it wins), the
// source now publishes the same value, a conflict with the official value on this computer, or
// waiting for the figure to arrive here. Plus the notes on a country (country page).
import clsx from 'clsx'
import { AlertTriangle, Flag, MessageSquareText, PenLine, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Loading } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate } from '@/lib/format'
import { isMirror } from '@/lib/mirror'
import { errorText, useCorrections, useCreateCorrection, useRevert } from './api'
import { fmtFigureValue } from './format'
import type { CorrectionEvent } from './types'

const NOTICE = new Set(['conflict', 'superseded_by_source', 'waiting'])

export function useStatusText() {
  const { t, lang } = useI18n()
  return (ev: CorrectionEvent): { text: string; tone: 'ok' | 'warn' | 'muted' } => {
    const d = ev.status_detail ?? {}
    const u = (d.unit as string | undefined) ?? ev.target?.unit ?? null
    const c = (d.currency as string | undefined) ?? ev.target?.currency ?? null
    switch (ev.status) {
      case 'applied': return { text: ev.kind === 'revert' ? t('corrections.status.revertApplied') : t('corrections.status.applied'), tone: 'ok' }
      case 'recorded': return { text: t(ev.kind === 'note' ? 'corrections.status.noteRecorded' : 'corrections.status.flagRecorded'), tone: 'ok' }
      case 'reverted': return { text: t('corrections.status.reverted'), tone: 'muted' }
      case 'replaced': return { text: t('corrections.status.replaced', { who: String(d.by_author ?? '—') }), tone: 'muted' }
      case 'confirmed_by_source': return { text: t('corrections.status.confirmed', { v: fmtFigureValue(d.new_official_value as number, u, c, lang) }), tone: 'ok' }
      case 'superseded_by_source': return d.withdrawn
        ? { text: t('corrections.status.withdrawn'), tone: 'warn' }
        : { text: t('corrections.status.superseded', { v: fmtFigureValue(d.new_official_value as number, u, c, lang) }), tone: 'warn' }
      case 'conflict': return { text: t('corrections.status.conflict'), tone: 'warn' }
      case 'waiting': return { text: t('corrections.status.waiting'), tone: 'warn' }
      default: return { text: ev.status, tone: 'muted' }
    }
  }
}

function EventRow({ ev }: { ev: CorrectionEvent }) {
  const { t, lang } = useI18n()
  const status = useStatusText()(ev)
  const revert = useRevert()
  const u = ev.target?.unit ?? null
  const c = ev.target?.currency ?? null
  const Icon = ev.kind === 'note' ? MessageSquareText : ev.kind === 'flag_wrong' ? Flag : ev.kind === 'revert' ? Undo2 : PenLine
  const what = ev.kind === 'value_correction'
    ? `${fmtFigureValue(ev.official_value, u, c, lang)} → ${fmtFigureValue(ev.corrected_value, u, c, lang)}`
    : ev.kind === 'note' ? ev.text : ev.kind === 'flag_wrong' ? t('corrections.list.flag') : t('corrections.list.revert')
  return (
    <li className="grid grid-cols-[1.4rem_minmax(0,1fr)] gap-x-2 border-b border-line-soft py-3 last:border-0" data-event={ev.event_id} data-status={ev.status}>
      <Icon size={17} className="mt-0.5 text-gold-dark" aria-hidden />
      <div className="min-w-0">
        <div className="text-[1rem] leading-snug text-charcoal">
          {ev.target?.label && <span className="font-semibold">{ev.target.label}: </span>}
          <span className={ev.kind === 'value_correction' ? 'tabular-nums' : undefined}>{what}</span>
        </div>
        {ev.reason && <div className="text-[0.9rem] text-charcoal-soft">«{ev.reason}»</div>}
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.86rem] text-muted">
          <span>{t('corrections.done.by', { who: ev.author ?? '—', when: fmtDate(ev.created_at, lang, { day: 'numeric', month: 'short', year: 'numeric' }) })}</span>
          <span className={clsx('inline-flex items-center gap-1', status.tone === 'warn' ? 'text-warn' : status.tone === 'ok' ? 'text-up' : 'text-muted')}>
            {NOTICE.has(ev.status) && <AlertTriangle size={13} aria-hidden />}{status.text}
          </span>
          {ev.sync.state === 'pending_sync' && <span>· {t('corrections.done.pendingSync')}</span>}
          {ev.sync.error && <span className="text-down">· {ev.sync.error}</span>}
          {ev.revertible && !isMirror() && (
            <button type="button" className="link" disabled={revert.isPending} onClick={() => revert.mutate({ eventId: ev.event_id })}>
              {ev.kind === 'value_correction' ? t('corrections.badge.undo') : t('corrections.done.remove')}
            </button>
          )}
        </div>
        {revert.error && <div className="text-[0.86rem] text-down">{errorText(revert.error, lang)}</div>}
      </div>
    </li>
  )
}

/** Recent events; `notices` first lists those that need a look (conflict, source published, waiting). */
export function CorrectionsList({ limit = 20, className }: { limit?: number; className?: string }) {
  const { t } = useI18n()
  const q = useCorrections({ limit })
  if (isMirror()) return null
  if (q.isLoading) return <Loading />
  const items = q.data?.items ?? []
  const attention = items.filter((e) => NOTICE.has(e.status))
  return (
    <div className={className} data-corrections-list>
      {items.length === 0 ? (
        <p className="text-[0.95rem] text-muted">{t('corrections.list.none')}</p>
      ) : (
        <>
          {attention.length > 0 && (
            <p className="mb-2 flex items-start gap-1.5 text-[0.95rem] text-warn"><AlertTriangle size={16} className="mt-0.5 shrink-0" />
              {t(attention.length === 1 ? 'corrections.list.attention1' : 'corrections.list.attention', { n: attention.length })}</p>
          )}
          <ul>{[...attention, ...items.filter((e) => !NOTICE.has(e.status))].map((ev) => <EventRow key={ev.event_id} ev={ev} />)}</ul>
        </>
      )}
    </div>
  )
}

/** Notes left on a country (country page), newest first, and a box to add one. */
export function CountryNotes({ iso3, name, className }: { iso3: string; name: string; className?: string }) {
  const { t, lang } = useI18n()
  const q = useCorrections({ kind: 'note', country: iso3, status: 'recorded', limit: 50 })
  const create = useCreateCorrection()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  if (isMirror()) return null
  const items = q.data?.items ?? []
  return (
    <section className={clsx('panel px-4 py-3 sm:px-5', className)} data-country-notes={iso3}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="panel-title">{t('corrections.notes.title', { c: name })}</h2>
        {!open && <button type="button" className="btn-secondary !py-1" onClick={() => setOpen(true)}>{t('corrections.notes.add')}</button>}
      </div>
      {open && (
        <form className="mt-2 space-y-2" onSubmit={(e) => {
          e.preventDefault()
          create.mutate({ kind: 'note', country_iso3: iso3, text: text.trim() }, { onSuccess: () => { setText(''); setOpen(false) } })
        }}>
          <textarea className="field min-h-[4rem]" value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} required
            aria-label={t('corrections.form.note')} placeholder={t('corrections.form.notePh')} />
          {create.error && <p className="text-down" role="alert">{errorText(create.error, lang)}</p>}
          <div className="flex gap-3">
            <button type="submit" className="btn-primary !py-1.5" disabled={create.isPending || !text.trim()}>{t('corrections.box.saveNote')}</button>
            <button type="button" className="link" onClick={() => setOpen(false)}>{t('corrections.cancel')}</button>
          </div>
        </form>
      )}
      {items.length > 0 ? <ul className="mt-1">{items.map((ev) => <EventRow key={ev.event_id} ev={ev} />)}</ul>
        : !open && <p className="mt-1 text-[0.92rem] text-muted">{t('corrections.notes.none')}</p>}
    </section>
  )
}

/** One line when corrections need a look (conflict, the source published a new value, waiting),
 * linking to the full list on the Sources page. */
export function AttentionLine({ className }: { className?: string }) {
  const { t } = useI18n()
  const q = useCorrections({ status: 'conflict,superseded_by_source,waiting', limit: 20 })
  const n = q.data?.total ?? 0
  if (isMirror() || n === 0) return null
  return (
    <Link to="/fonti#correzioni" className={clsx('flex items-start gap-1.5 text-[0.92rem] text-warn hover:underline', className)} data-attention={n}>
      <AlertTriangle size={15} className="mt-0.5 shrink-0" aria-hidden />
      {t(n === 1 ? 'corrections.list.attention1' : 'corrections.list.attention', { n })} {t('corrections.list.see')} →
    </Link>
  )
}
