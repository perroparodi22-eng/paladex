// Fixing a number in place (owner's request, 11 Nov 2026: "not like a comment, like fixing the price
// to the real one"): tap the number, type the right one, Enter. No reason to write, no choice to
// make. The number is typed in the unit it is shown in (EUR/kg on screen, even when the source
// publishes USD/lb: the backend converts it); the source's own value is kept and comes back with
// one tap. The doubt flag and the note are one small link away (FigureDialog).
import clsx from 'clsx'
import { useQueryClient } from '@tanstack/react-query'
import { Pencil, Undo2, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '@/i18n'
import { fmtDate } from '@/lib/format'
import { isMirror } from '@/lib/mirror'
import type { Lang } from '@/lib/types'
import { api } from '@/lib/api'
import { errorDetail, errorText, refreshFigures } from './api'
import { FigureDialog } from './FigureDialog'
import { fmtFigureValue } from './format'
import { AuthorLine } from './parts'
import type { CorrectionBrief, CorrectionsList, FigureRef } from './types'

type Basis = { value: number | null; unit: string | null; currency: string | null }

/** What the person sees and types: the figure as shown on screen; big weights in tonnes. */
export function editBasis(figure: FigureRef): Basis {
  let s: Basis = figure.shown ?? { value: figure.value, unit: figure.unit, currency: figure.currency }
  // a converted price is shown with two decimals: the box starts from the number on screen
  if (figure.shown && s.currency && s.value !== null) s = { ...s, value: Math.round(s.value * 100) / 100 }
  if (s.unit === 'kg' && !s.currency && s.value !== null && Math.abs(s.value) >= 10_000) return { value: s.value / 1000, unit: 't', currency: null }
  return s
}

/** The number in the box when it opens: as it reads on screen, without inventing decimals. */
export function inputText(v: number | null, lang: Lang): string {
  if (v === null || Number.isNaN(v)) return ''
  const digits = Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 100 ? 1 : 3
  return new Intl.NumberFormat(lang === 'it' ? 'it-IT' : 'en-US', { maximumFractionDigits: digits }).format(v)
}

/** A typed number in the interface language. "69.298" is sixty-nine thousand in Italian and "3,5"
 * three and a half; where one mark can be read both ways ("3.420": a price of 3,42 or 3.420 tonnes)
 * the reading closer to the current value `near` wins. Null when it is not a number. */
export function parseTyped(raw: string, lang: Lang, near?: number | null): number | null {
  const s = raw.trim().replace(/[\s '’€$]/g, '')
  if (!s || !/^[\d.,]+$/.test(s) || !/\d/.test(s)) return null
  const dots = s.split('.').length - 1, commas = s.split(',').length - 1
  const [dec, thou] = lang === 'it' ? [',', '.'] : ['.', ',']
  const num = (x: string) => { const v = Number(x); return x && Number.isFinite(v) && v >= 0 ? v : null }
  if (dots && commas) {
    const d = s.lastIndexOf('.') > s.lastIndexOf(',') ? '.' : ','
    return num(s.split(d === '.' ? ',' : '.').join('').replace(d, '.'))
  }
  const nThou = thou === '.' ? dots : commas, nDec = dec === '.' ? dots : commas
  if (nDec > 1) return null
  if (!nThou) return num(s.replace(dec, '.'))
  const grouped = /^\d{1,3}([.,]\d{3})+$/.test(s) ? num(s.split(thou).join('')) : null
  const decimal = nThou === 1 ? num(s.replace(thou, '.')) : null
  if (grouped !== null && decimal !== null && near && near > 0 && decimal > 0) {
    return Math.abs(Math.log(decimal / near)) < Math.abs(Math.log(grouped / near)) ? decimal : grouped
  }
  return grouped ?? decimal
}

/** A new value this many times bigger or smaller than the current one asks "are you sure?". */
const BIG_CHANGE = 5

export function QuickFixForm({ figure, correction, onDone, onCancel, onMore }: {
  figure: FigureRef; correction?: CorrectionBrief | null; onDone?: () => void; onCancel?: () => void; onMore?: () => void
}) {
  const { t, lang } = useI18n()
  const qc = useQueryClient()
  const basis = editBasis(figure)
  const start = inputText(basis.value, lang)
  const [typed, setTyped] = useState(start)
  const [sure, setSure] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<unknown>(null)
  const rows = figure.row_ids?.length ? figure.row_ids : [figure.row_id]
  const input = useRef<HTMLInputElement>(null)
  const ids = useId()
  useEffect(() => { input.current?.focus(); input.current?.select() }, [])

  const value = parseTyped(typed, lang, basis.value)
  const unchanged = typed.trim() === start || (value !== null && basis.value !== null && value === basis.value)
  const ratio = value !== null && basis.value ? value / basis.value : null
  const big = ratio !== null && (ratio === 0 || ratio > BIG_CHANGE || ratio < 1 / BIG_CHANGE)
  // as on the pages: "3,42 €/kg", "1,775 $/lb"
  const sym = (x: string) => x.replace('EUR', '€').replace('USD', '$')
  const unitText = sym(basis.currency && basis.unit ? `${basis.currency}/${basis.unit}` : basis.unit ?? basis.currency ?? '')
  const show = (v: number | null) => sym(fmtFigureValue(v, basis.unit, basis.currency, lang))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (value === null || unchanged || busy) return
    if (big && !sure) { setSure(true); return }
    setBusy(true)
    setFailure(null)
    try {
      for (const row_id of rows) {
        try {
          await api.post('/corrections', {
            kind: 'value_correction', target: { table: figure.table, row_id }, value,
            unit: basis.unit, currency: basis.currency, field: figure.table === 'trade_flows' ? figure.field ?? null : null,
          })
        } catch (err) {
          // of several averaged rows, one may already say exactly this: nothing to fix there
          if (rows.length === 1 || !['same_as_official', 'same_as_current'].includes(errorDetail(err)?.code ?? '')) throw err
        }
      }
      void refreshFigures(qc)      // the pages read the figures again; the window does not wait for them
      onDone?.()
    } catch (err) {
      void refreshFigures(qc)      // of several rows, some may have been written
      setFailure(err)
    } finally {
      setBusy(false)
    }
  }

  const undo = (eventId: string) => api.post(`/corrections/${encodeURIComponent(eventId)}/revert`, {})
  const putBack = async () => {
    if (!correction || busy) return
    setBusy(true)
    setFailure(null)
    try {
      if (rows.length === 1) await undo(correction.event_id)
      else {
        for (const row_id of rows) {
          const list = await api.get<CorrectionsList>('/corrections', { table: figure.table, row_id, kind: 'value_correction', status: 'applied' })
          for (const ev of list.items) if (ev.revertible && ev.applied_row_id === row_id) await undo(ev.event_id)
        }
      }
      void refreshFigures(qc)
      onDone?.()
    } catch (err) {
      void refreshFigures(qc)
      setFailure(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" data-quick-fix={figure.row_id}>
      <p className="text-[0.98rem] leading-snug text-charcoal-soft">{figure.label}</p>
      <div>
        <label className="label !text-[0.95rem]" htmlFor={`${ids}-v`}>{t('corrections.quick.right')}</label>
        <div className="flex items-center gap-2.5">
          <input id={`${ids}-v`} ref={input} className="field !w-44 tabular-nums !py-2.5 !text-[1.5rem] font-semibold" inputMode="decimal"
            autoComplete="off" value={typed} onChange={(e) => { setTyped(e.target.value); setSure(false) }} />
          <span className="text-[1.1rem] text-charcoal-soft">{unitText}</span>
        </div>
        <p className="mt-1.5 min-h-[1.4rem] text-[0.95rem] tabular-nums" aria-live="polite" data-preview>
          {typed.trim() && value === null ? <span className="text-down">{t('corrections.quick.notNumber')}</span>
            : value !== null && !unchanged ? <span className="text-charcoal-soft">{show(basis.value)} <span aria-hidden className="text-gold-dark">→</span> <span className="font-semibold text-charcoal">{show(value)}</span></span>
              : <span className="text-muted">{t('corrections.quick.now', { v: show(basis.value) })}</span>}
        </p>
      </div>
      {big && sure && (
        <p className="rounded-md border border-gold-light/60 bg-gold-pale/40 px-3 py-2 text-[0.95rem] text-charcoal" role="alert" data-big-change>
          {t('corrections.quick.bigChange', { from: show(basis.value), to: show(value) })}
        </p>
      )}
      {failure != null && <p className="text-[0.95rem] text-down" role="alert">{errorText(failure, lang)}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className="btn-primary !px-6 !text-[1.05rem]" disabled={value === null || unchanged || busy}>
          {big && sure ? t('corrections.quick.yesSave') : t('corrections.save')}
        </button>
        {onCancel && <button type="button" className="btn-ghost" onClick={onCancel}>{t('corrections.cancel')}</button>}
      </div>
      {correction ? (
        <div className="rounded-md border border-[#C9DAEA] bg-[#EDF3F9] px-3 py-2.5 text-[0.92rem] text-[#24507A]" data-corrected>
          <div>
            {t('corrections.quick.corrected', {
              who: correction.author || t('corrections.someone'),
              when: correction.created_at ? fmtDate(correction.created_at, lang, { day: 'numeric', month: 'short', year: 'numeric' }) : '—',
              v: sym(fmtFigureValue(correction.official_value, correction.unit, correction.currency, lang)),
            })}
          </div>
          <button type="button" className="mt-1.5 inline-flex items-center gap-1 font-medium underline underline-offset-2" disabled={busy} onClick={putBack}>
            <Undo2 size={14} aria-hidden /> {t('corrections.quick.back')}
          </button>
        </div>
      ) : (
        <p className="text-[0.86rem] leading-snug text-muted">{t('corrections.quick.kept')}</p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-line-soft pt-3">
        <AuthorLine className="!text-[0.86rem]" />
        {onMore && <button type="button" className="link text-[0.86rem]" onClick={onMore}>{t('corrections.quick.more')}</button>}
      </div>
    </form>
  )
}

/** The small window in the middle of the screen. Escape and a tap outside close it. */
export function QuickFixDialog({ figure, correction, onClose }: { figure: FigureRef; correction?: CorrectionBrief | null; onClose: () => void }) {
  const { t } = useI18n()
  const [more, setMore] = useState(false)
  const labelId = useId()
  const close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); close.current() } }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); previous?.focus?.() }
  }, [])
  if (more) return createPortal(<FigureDialog figure={figure} correction={correction} open onClose={onClose} />, document.body)
  return createPortal(
    <div className="fixed inset-0 z-[1500] flex items-start justify-center overflow-y-auto bg-charcoal/40 px-4 py-[12vh]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }} onClick={(e) => e.stopPropagation()}>
      <div role="dialog" aria-modal="true" aria-labelledby={labelId} className="w-full max-w-[26rem] rounded-lg border border-line bg-white p-5 shadow-xl">
        <div className="mb-3 flex items-start justify-between gap-3">
          <h2 id={labelId} className="text-[1.3rem] font-semibold leading-tight">{t('corrections.quick.title')}</h2>
          <button type="button" className="-mr-1.5 -mt-1 rounded-md p-1.5 text-muted hover:bg-forest-50 hover:text-charcoal" onClick={onClose} aria-label={t('corrections.cancel')}>
            <X size={20} />
          </button>
        </div>
        <QuickFixForm figure={figure} correction={correction} onDone={onClose} onCancel={onClose} onMore={() => setMore(true)} />
      </div>
    </div>,
    document.body,
  )
}

/** A number a person can fix: the number itself is the button (a small pencil says so). In the
 * read-only phone copy, or where the figure is not one stored row, it is just the number. */
export function FixValue({ figure, correction, children, className, pencil = true }: {
  figure: FigureRef | null | undefined; correction?: CorrectionBrief | null; children: ReactNode; className?: string; pencil?: boolean
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  if (!figure || isMirror()) return <>{children}</>
  return (
    <>
      <button type="button" title={t('corrections.quick.tip')} data-fix-value={figure.row_id}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(true) }}
        className={clsx('fix-value group/fix', className)}>
        {children}
        {pencil && <Pencil size={13} aria-hidden className="ml-1.5 inline-block shrink-0 align-baseline text-muted/50 transition-colors group-hover/fix:text-forest-700" />}
        <span className="sr-only"> {t('corrections.quick.tip')}</span>
      </button>
      {open && <QuickFixDialog figure={figure} correction={correction} onClose={() => setOpen(false)} />}
    </>
  )
}
