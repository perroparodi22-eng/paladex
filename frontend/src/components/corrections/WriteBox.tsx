// "Scrivi a Paladex": the owner's father writes what is wrong as he would say it ("il miele argentino
// di settembre era 3,60 dollari al chilo, non 3,91"); the AI finds the figures it may be about and
// proposes "valore attuale → correzione"; he picks one, can change the number, and confirms. A
// supplier's offer goes to the private Offerte page instead. Without an AI key: how to correct a
// figure from the figure itself, and a plain form for a note on a country.
import { ArrowRight, Send } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '@/i18n'
import { useLabels } from '@/lib/meta'
import { isMirror } from '@/lib/mirror'
import { errorDetail, errorText, useCreateCorrection, useInterpret } from './api'
import { AttentionLine } from './CorrectionsPanel'
import { typedNumber } from './format'
import { AuthorLine, CandidateView, DoneView, SyncStatus } from './parts'
import type { CorrectionEvent, Interpretation } from './types'

function NoteForm({ onDone }: { onDone: (ev: CorrectionEvent) => void }) {
  const { t, lang } = useI18n()
  const { meta, country } = useLabels()
  const create = useCreateCorrection()
  const [iso3, setIso3] = useState('')
  const [text, setText] = useState('')
  const ids = useId()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate({ kind: 'note', country_iso3: iso3, text: text.trim() }, { onSuccess: (r) => onDone(r.event) })
  }
  return (
    <form onSubmit={submit} className="space-y-3" data-note-form>
      <div>
        <label className="label" htmlFor={`${ids}-c`}>{t('corrections.form.country')}</label>
        <select id={`${ids}-c`} className="field !w-auto" value={iso3} onChange={(e) => setIso3(e.target.value)} required>
          <option value="">—</option>
          {(meta?.countries ?? []).filter((c) => c.priority).sort((a, b) => country(a.iso3).localeCompare(country(b.iso3)))
            .map((c) => <option key={c.iso3} value={c.iso3}>{country(c.iso3)}</option>)}
        </select>
      </div>
      <div>
        <label className="label" htmlFor={`${ids}-t`}>{t('corrections.form.note')}</label>
        <textarea id={`${ids}-t`} className="field min-h-[4.5rem]" value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} required
          placeholder={t('corrections.form.notePh')} />
      </div>
      {create.error && <p className="text-down" role="alert">{errorText(create.error, lang)}</p>}
      <button type="submit" className="btn-primary" disabled={create.isPending}>{t('corrections.box.saveNote')}</button>
    </form>
  )
}

export function WriteBox({ compact = false }: { compact?: boolean }) {
  const { t, lang } = useI18n()
  const { meta } = useLabels()
  const interpret = useInterpret()
  const create = useCreateCorrection()
  const [text, setText] = useState('')
  const [answer, setAnswer] = useState<Interpretation | null>(null)
  const [pick, setPick] = useState(0)
  const [values, setValues] = useState<Record<number, string>>({})
  const [done, setDone] = useState<CorrectionEvent | null>(null)
  const [plain, setPlain] = useState(false)
  const [noteOpen, setNoteOpen] = useState(false)
  const ids = useId()
  if (isMirror()) return null
  const aiOn = Boolean(meta?.flags.llm_enabled) && !plain

  const read = (e: FormEvent) => {
    e.preventDefault()
    setAnswer(null)
    setDone(null)
    interpret.mutate({ text: text.trim(), lang }, {
      onSuccess: (r) => {
        setAnswer(r)
        setPick(0)
        setValues(Object.fromEntries(r.candidates.map((c, i) => [i, typedNumber(c.proposal?.entered?.value, lang)])))
      },
      onError: (err) => { if (errorDetail(err)?.code === 'ai_unavailable') setPlain(true) },
    })
  }
  const confirm = () => {
    if (!answer) return
    const c = answer.candidates[pick]
    const body = answer.note && !c ? answer.note.create : c?.proposal?.create
    if (!body) return
    create.mutate({
      ...body, ai_interpretation: answer.ai_interpretation,
      ...(body.kind === 'value_correction' ? { value: values[pick] ?? body.value } : {}),
    }, { onSuccess: (r) => { setDone(r.event); setAnswer(null); setText('') } })
  }
  const message = answer ? (lang === 'en' ? answer.message_en : answer.message_it) : null
  const canConfirm = answer && ((answer.candidates[pick]?.proposal && !answer.candidates[pick]?.proposal_error) || (answer.note && !answer.candidates.length))

  return (
    <div className="space-y-4" data-write-box={aiOn ? 'ai' : 'plain'}>
      {done && <DoneView ev={done} />}
      {aiOn ? (
        <form onSubmit={read} className="space-y-2.5">
          <label htmlFor={`${ids}-t`} className="sr-only">{t('corrections.box.title')}</label>
          <textarea id={`${ids}-t`} className="field min-h-[5.5rem] !text-[1.05rem]" value={text} onChange={(e) => setText(e.target.value)}
            maxLength={2000} placeholder={t('corrections.box.placeholder')} />
          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" className="btn-primary !text-[1.02rem]" disabled={!text.trim() || interpret.isPending}>
              <Send size={16} aria-hidden /> {interpret.isPending ? t('corrections.box.reading') : t('corrections.box.read')}
            </button>
            {!compact && <span className="text-[0.88rem] text-muted">{t('corrections.box.nothingYet')}</span>}
          </div>
          {interpret.error && errorDetail(interpret.error)?.code !== 'ai_unavailable' && (
            <p className="text-down" role="alert">{errorText(interpret.error, lang)}</p>
          )}
        </form>
      ) : (
        // without an AI key a number is fixed by tapping it; what is left here is the note on a country
        noteOpen ? <NoteForm onDone={setDone} />
          : <button type="button" className="link text-[1rem]" onClick={() => setNoteOpen(true)} data-note-open>{t('corrections.quick.noteOpen')}</button>
      )}

      {answer && (
        <div className="space-y-3" data-answer={answer.route}>
          {answer.route === 'quotes' ? (
            <div className="rounded-sm border border-gold-light/60 bg-gold-pale/30 px-4 py-3 text-[0.98rem]">
              <p>{message}</p>
              <Link to="/offerte" className="mt-1.5 inline-flex items-center gap-1 font-medium text-forest-700">{t('corrections.box.toQuotes')} <ArrowRight size={15} /></Link>
            </div>
          ) : (
            <>
              {message && <p className="text-[0.98rem] text-charcoal-soft">{message}</p>}
              {answer.note && !answer.candidates.length && (
                <div className="rounded-sm border border-line bg-white px-4 py-3">
                  <div className="text-[0.88rem] text-muted">{t('corrections.box.noteFor', { c: answer.note.country_name ?? answer.note.country_iso3 ?? '—' })}</div>
                  <p className="mt-1 text-[1rem] text-charcoal">{answer.note.text}</p>
                </div>
              )}
              {answer.candidates.length > 0 && (
                <>
                  <p className="text-[0.95rem] font-medium text-charcoal-soft">
                    {answer.candidates.length === 1 ? t('corrections.box.oneCandidate') : t('corrections.box.candidates', { n: answer.candidates.length })}
                  </p>
                  <div className="space-y-2">
                    {answer.candidates.map((c, i) => (
                      <CandidateView key={`${c.table}-${c.row_id}`} c={c} selected={pick === i} onSelect={() => setPick(i)}
                        value={values[i] ?? ''} onValue={(v) => setValues((x) => ({ ...x, [i]: v }))} />
                    ))}
                  </div>
                </>
              )}
              {!answer.candidates.length && !answer.note && <p className="text-[0.95rem] text-muted">{t('corrections.box.noneFound')}</p>}
              {create.error && <p className="text-down" role="alert">{errorText(create.error, lang)}</p>}
              <div className="flex flex-wrap items-center gap-3">
                {canConfirm && <button type="button" className="btn-primary !text-[1.02rem]" onClick={confirm} disabled={create.isPending}>{t('corrections.confirm')}</button>}
                <button type="button" className="link text-[0.95rem]" onClick={() => setAnswer(null)}>{t('corrections.cancel')}</button>
              </div>
              {answer.ai && <p className="text-[0.82rem] text-muted">{t('corrections.box.aiRead', { m: answer.ai.model })}</p>}
            </>
          )}
        </div>
      )}

      <div className="space-y-1.5 border-t border-line-soft pt-3">
        <AuthorLine />
        <SyncStatus compact />
        <AttentionLine />
      </div>
    </div>
  )
}
