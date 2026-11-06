// Small pieces of the correction flow: who signs, the sync status, a candidate figure with its
// proposed change, the result of a correction.
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, CloudOff, Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '@/i18n'
import { fmtAgo, fmtDate, fmtPeriod } from '@/lib/format'
import { shortSource } from '@/lib/plain'
import { Switch } from '@/components/news/bits'
import { errorText, useCorrSettings, useSaveAuthor, useSaveSync, useSyncNow, useSyncState } from './api'
import { fmtFigureValue } from './format'
import type { Candidate, CorrectionEvent } from './types'

/** "Firmi come: Papà · cambia" — the name shown as "Corretto da <nome>". */
export function AuthorLine({ className }: { className?: string }) {
  const { t, lang } = useI18n()
  const s = useCorrSettings()
  const save = useSaveAuthor()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  useEffect(() => { if (s.data) setName(s.data.author) }, [s.data])
  if (!s.data) return null
  return (
    <div className={clsx('flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[0.95rem]', className)} data-author={s.data.author}>
      <span className="text-muted">{t('corrections.author.signs')}</span>
      {editing ? (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => {
          e.preventDefault()
          save.mutate(name.trim(), { onSuccess: () => setEditing(false) })
        }}>
          <input className="field !w-44 !py-1" value={name} onChange={(e) => setName(e.target.value)} maxLength={120}
            aria-label={t('corrections.author.label')} placeholder={t('corrections.author.placeholder')} autoFocus />
          <button type="submit" className="btn-secondary !py-1" disabled={save.isPending || !name.trim()}>{t('corrections.save')}</button>
          <button type="button" className="link text-[0.9rem]" onClick={() => setEditing(false)}>{t('corrections.cancel')}</button>
          {save.error && <span className="text-down">{errorText(save.error, lang)}</span>}
        </form>
      ) : (
        <>
          <span className="font-semibold text-charcoal">{s.data.author}</span>
          <button type="button" className="link text-[0.9rem]" onClick={() => setEditing(true)}>{t('corrections.author.change')}</button>
        </>
      )}
    </div>
  )
}

/** "Sincronizzate · ultimo invio 10 minuti fa" / "2 in attesa di invio" / the error, with "Sincronizza ora". */
export function SyncStatus({ className, compact = false }: { className?: string; compact?: boolean }) {
  const { t, lang } = useI18n()
  const q = useSyncState()
  const now = useSyncNow()
  const s = q.data
  if (!s) return null
  const err = s.error
  const msg = !s.enabled
    ? ((lang === 'en' ? s.reason_message_en : s.reason_message_it) ?? t('corrections.sync.off'))
    : err ? ((lang === 'en' ? err.message_en : err.message_it) ?? err.code)
      : s.pending > 0 ? t(s.pending === 1 ? 'corrections.sync.pending1' : 'corrections.sync.pending', { n: s.pending })
        : s.last_push_at || s.last_pull_at ? t('corrections.sync.ok', { ago: fmtAgo(s.last_push_at ?? s.last_pull_at, lang) })
          : t('corrections.sync.never')
  const tone = !s.enabled ? 'text-muted' : err ? 'text-down' : s.pending ? 'text-warn' : 'text-up'
  const Icon = !s.enabled ? CloudOff : err ? AlertTriangle : s.running ? Loader2 : CheckCircle2
  return (
    <div className={clsx('flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.9rem]', className)} data-sync={!s.enabled ? 'off' : err ? 'error' : s.pending ? 'pending' : 'ok'}>
      <Icon size={15} className={clsx('shrink-0 self-start mt-[0.2rem]', tone, s.running && 'animate-spin')} aria-hidden />
      <span className={clsx('min-w-0 flex-1 basis-[12rem]', compact ? 'text-muted' : 'text-charcoal-soft')}>
        <span className="font-medium">{t('corrections.sync.label')}:</span> {msg}
      </span>
      {s.enabled && (
        <button type="button" className="inline-flex items-center gap-1 text-forest-700 underline decoration-gold/50 underline-offset-2 hover:decoration-gold disabled:opacity-50"
          onClick={() => now.mutate()} disabled={now.isPending || s.running}>
          <RefreshCw size={13} className={clsx(now.isPending && 'animate-spin')} aria-hidden /> {t('corrections.sync.now')}
        </button>
      )}
      {!s.enabled && compact && (
        <Link to="/fonti#correzioni" className="text-forest-700 underline decoration-gold/50 underline-offset-2 hover:decoration-gold">{t('corrections.sync.settings')}</Link>
      )}
      {now.error && <span className="text-down">{errorText(now.error, lang)}</span>}
    </div>
  )
}

/** "Scambia le correzioni con gli altri computer" (off by default, per computer), with what it means. */
export function SyncSwitch({ className }: { className?: string }) {
  const { t, lang } = useI18n()
  const s = useCorrSettings()
  const save = useSaveSync()
  if (!s.data) return null
  const on = Boolean(s.data.sync_enabled)
  return (
    <div className={clsx('space-y-1', className)} data-sync-switch={on ? 'on' : 'off'}>
      <Switch checked={on} onChange={(v) => save.mutate(v)} label={t('corrections.sync.switch')} />
      <p className="pl-[3.1rem] text-[0.86rem] leading-snug text-muted">{t('corrections.sync.switchHint')}</p>
      {save.error && <p className="pl-[3.1rem] text-[0.86rem] text-down">{errorText(save.error, lang)}</p>}
    </div>
  )
}

/** One figure the words may be about: what it is, its source, "valore attuale → correzione". */
export function CandidateView({ c, selected, onSelect, value, onValue }: {
  c: Candidate; selected: boolean; onSelect: () => void; value: string; onValue: (v: string) => void
}) {
  const { t, lang } = useI18n()
  const p = c.proposal
  const isValue = p?.create.kind === 'value_correction'
  const entered = p?.entered
  const unitTyped = entered?.currency && entered?.unit ? `${entered.currency}/${entered.unit}` : entered?.unit ?? entered?.currency ?? ''
  return (
    <label className={clsx('block cursor-pointer rounded-sm border px-3 py-3 transition-colors',
      selected ? 'border-forest-700 bg-forest-50' : 'border-line bg-white hover:border-forest-300')} data-candidate={c.row_id}>
      <span className="flex items-start gap-3">
        <input type="radio" className="mt-1.5 h-4 w-4 accent-[#143A2B]" checked={selected} onChange={onSelect} name="candidate" />
        <span className="min-w-0 flex-1">
          <span className="block text-[1.02rem] font-semibold leading-snug text-charcoal">{c.label}</span>
          <span className="mt-0.5 block text-[0.88rem] text-muted">
            {t('corrections.cand.source', { s: shortSource(c.source, lang), p: fmtPeriod(c.period_label, lang) })}
            {c.provenance.published_at && <> · {t('prov.published')} {fmtDate(c.provenance.published_at, lang)}</>}
            {c.matches_old_value && <> · <span className="text-forest-700">{t('corrections.cand.matches')}</span></>}
          </span>
          <span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[1rem]">
            <span className="text-muted">{t('corrections.cand.now')}</span>
            <span className="tabular-nums font-semibold text-charcoal">{fmtFigureValue(c.current.value, c.current.unit, c.current.currency, lang)}</span>
            {isValue && (
              <>
                <span aria-hidden className="text-gold-dark">→</span>
                <span className="text-muted">{t('corrections.cand.to')}</span>
                <input className="field !w-28 !py-1 tabular-nums" inputMode="decimal" value={value} onChange={(e) => onValue(e.target.value)}
                  aria-label={t('corrections.cand.newValue')} onClick={(e) => e.stopPropagation()} />
                <span className="text-charcoal-soft">{unitTyped}</span>
                {p?.to != null && (p.unit !== p.entered?.unit || p.currency !== p.entered?.currency) && (
                  <span className="text-[0.88rem] text-muted">({t('corrections.cand.stored', { v: fmtFigureValue(p.to, p.unit, p.currency, lang) })})</span>
                )}
              </>
            )}
            {p?.create.kind === 'flag_wrong' && <span className="text-warn">{t('corrections.cand.flag')}</span>}
          </span>
          {c.correction && <span className="mt-1 block text-[0.88rem] text-[#24507A]">{t('corrections.cand.already', { who: c.correction.author ?? '—' })}</span>}
          {c.proposal_error && <span className="mt-1 block text-[0.9rem] text-down">{lang === 'en' ? c.proposal_error.message_en : c.proposal_error.message_it}</span>}
        </span>
      </span>
    </label>
  )
}

/** "Fatto: corretto 1,77 → 1,85 USD/lb" with the event's state. */
export function DoneView({ ev }: { ev: CorrectionEvent }) {
  const { t, lang } = useI18n()
  const u = ev.target?.unit ?? null
  const c = ev.target?.currency ?? null
  const text = ev.kind === 'value_correction'
    ? t('corrections.done.value', { from: fmtFigureValue(ev.official_value, u, c, lang), to: fmtFigureValue(ev.corrected_value, u, c, lang) })
    : ev.kind === 'flag_wrong' ? t('corrections.done.flag') : t('corrections.done.note')
  return (
    <div className="flex items-start gap-2.5 rounded-sm border border-forest-100 bg-forest-50 px-4 py-3 text-[1rem] text-forest-900" role="status" data-done={ev.kind}>
      <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-up" />
      <div>
        <div className="font-semibold">{text}</div>
        {ev.target?.label && <div className="text-[0.92rem] text-charcoal-soft">{ev.target.label}</div>}
        <div className="mt-0.5 text-[0.9rem] text-muted">
          {t('corrections.done.by', { who: ev.author ?? '—', when: fmtDate(ev.created_at, lang, { day: 'numeric', month: 'long', year: 'numeric' }) })}
          {' · '}{ev.sync.state === 'pending_sync' ? t('corrections.done.pendingSync') : t('corrections.done.saved')}
        </div>
      </div>
    </div>
  )
}
