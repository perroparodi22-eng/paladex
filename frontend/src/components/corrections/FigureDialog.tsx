// "Segnala o correggi" on one figure (one stored row): the right value (in any unit and currency:
// the backend converts it to the figure's own), "this figure looks wrong", or a note on the country.
// Always a plain form; with an AI key, the same can be written in words. Nothing is changed until
// "Conferma"; the result shows who corrected what, with one-click undo.
import clsx from 'clsx'
import { Flag, MessageSquareText, PenLine, Sparkles } from 'lucide-react'
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { Drawer } from '@/components/quotes/Drawer'
import { useI18n } from '@/i18n'
import { useLabels } from '@/lib/meta'
import { CorrectionBadge } from './CorrectionBadge'
import { errorDetail, errorText, useCreateCorrection, useInterpret, useRevert } from './api'
import { CURRENCIES, fmtFigureValue, PRICE_UNITS, typedNumber } from './format'
import { AuthorLine, CandidateView, DoneView } from './parts'
import type { CorrectionBrief, CorrectionEvent, CreateBody, FigureRef, Interpretation } from './types'

type Mode = 'value' | 'flag' | 'note'

function ModeButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button type="button" role="tab" aria-selected={active} onClick={onClick}
      className={clsx('inline-flex items-center gap-1.5 rounded-sm border px-3 py-2 text-[0.95rem] font-medium transition-colors',
        active ? 'border-forest-800 bg-forest-800 text-ivory' : 'border-line bg-white text-charcoal-soft hover:border-forest-300')}>
      {icon}{children}
    </button>
  )
}

export function FigureForm({ figure, correction, onDone, defaultMode = 'value' }: {
  figure: FigureRef; correction?: CorrectionBrief | null; onDone?: (ev: CorrectionEvent) => void; defaultMode?: Mode
}) {
  const { t, lang } = useI18n()
  const { meta, country } = useLabels()
  const create = useCreateCorrection()
  const revert = useRevert()
  const interpret = useInterpret()
  const [mode, setMode] = useState<Mode>(defaultMode)
  const isPrice = figure.table === 'price_observations'
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState(figure.unit ?? '')
  const [currency, setCurrency] = useState(figure.currency ?? '')
  const [reason, setReason] = useState('')
  const [text, setText] = useState('')
  const [iso3, setIso3] = useState(figure.country_iso3 ?? '')
  const [words, setWords] = useState('')
  const [result, setResult] = useState<CorrectionEvent | null>(null)
  const [aiAnswer, setAiAnswer] = useState<Interpretation | null>(null)
  const [aiValue, setAiValue] = useState('')
  const ids = useId()
  const aiOn = Boolean(meta?.flags.llm_enabled)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const target = { table: figure.table, row_id: figure.row_id }
    const body: CreateBody = mode === 'value'
      ? { kind: 'value_correction', target, value: value.trim(), unit: unit || null, currency: currency || null,
          field: figure.table === 'trade_flows' ? figure.field ?? null : null, reason: reason.trim() || null }
      : mode === 'flag' ? { kind: 'flag_wrong', target, reason: reason.trim() || null }
        : { kind: 'note', target, text: text.trim(), country_iso3: iso3 || null }
    create.mutate(body, { onSuccess: (r) => { setResult(r.event); onDone?.(r.event) } })
  }

  if (result) {
    return (
      <div className="space-y-4">
        <DoneView ev={result} />
        {result.revertible && (
          <button type="button" className="btn-secondary" disabled={revert.isPending}
            onClick={() => revert.mutate({ eventId: result.event_id }, { onSuccess: () => setResult(null) })}>
            {result.kind === 'value_correction' ? t('corrections.badge.undo') : t('corrections.done.remove')}
          </button>
        )}
        {revert.error && <p className="text-down">{errorText(revert.error, lang)}</p>}
      </div>
    )
  }

  const err = create.error ? errorText(create.error, lang) : null
  const errCode = errorDetail(create.error)?.code
  const candidate = aiAnswer?.candidates[0]
  return (
    <div className="space-y-5" data-figure-form={figure.row_id}>
      <div className="rounded-sm border border-line-soft bg-white px-4 py-3">
        <div className="text-[1.02rem] font-semibold leading-snug text-charcoal">{figure.label}</div>
        <div className="mt-1 text-[0.98rem]">
          <span className="text-muted">{t('corrections.form.current')}</span>{' '}
          <span className="tabular-nums font-semibold">{fmtFigureValue(figure.value, figure.unit, figure.currency, lang)}</span>
        </div>
        {correction && <CorrectionBadge c={correction} className="mt-2" />}
      </div>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label={t('corrections.form.what')}>
        <ModeButton active={mode === 'value'} onClick={() => setMode('value')} icon={<PenLine size={16} />}>{t('corrections.form.modeValue')}</ModeButton>
        <ModeButton active={mode === 'flag'} onClick={() => setMode('flag')} icon={<Flag size={16} />}>{t('corrections.form.modeFlag')}</ModeButton>
        <ModeButton active={mode === 'note'} onClick={() => setMode('note')} icon={<MessageSquareText size={16} />}>{t('corrections.form.modeNote')}</ModeButton>
      </div>

      <form onSubmit={submit} className="space-y-4">
        {mode === 'value' && (
          <div>
            <label className="label" htmlFor={`${ids}-v`}>{t('corrections.form.right')}</label>
            <div className="flex flex-wrap items-center gap-2">
              <input id={`${ids}-v`} className="field !w-36 tabular-nums !text-[1.1rem]" inputMode="decimal" value={value}
                onChange={(e) => setValue(e.target.value)} placeholder={typedNumber(figure.value, lang)} required />
              {(isPrice || (figure.table === 'trade_flows' && figure.field === 'value')) && (
                <select className="field !w-auto" value={currency} onChange={(e) => setCurrency(e.target.value)} aria-label={t('corrections.form.currency')}>
                  {[...new Set([figure.currency, ...CURRENCIES].filter(Boolean))].map((c) => <option key={c!} value={c!}>{c}</option>)}
                </select>
              )}
              {(isPrice || figure.table === 'production_stats' || (figure.table === 'trade_flows' && figure.field !== 'value')) && (
                <>
                  {isPrice && <span className="text-muted">/</span>}
                  <select className="field !w-auto" value={unit} onChange={(e) => setUnit(e.target.value)} aria-label={t('corrections.form.unit')}>
                    {[...new Set([figure.unit, ...(isPrice ? PRICE_UNITS : ['t', 'kg'])].filter(Boolean))].map((u) => <option key={u!} value={u!}>{u}</option>)}
                  </select>
                </>
              )}
            </div>
            <p className="mt-1 text-[0.88rem] text-muted">{t('corrections.form.convertHint')}</p>
          </div>
        )}
        {mode !== 'note' ? (
          <div>
            <label className="label" htmlFor={`${ids}-r`}>{mode === 'flag' ? t('corrections.form.whyWrong') : t('corrections.form.reason')}</label>
            <textarea id={`${ids}-r`} className="field min-h-[4.5rem]" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000}
              placeholder={mode === 'flag' ? t('corrections.form.whyWrongPh') : t('corrections.form.reasonPh')} />
          </div>
        ) : (
          <>
            <div>
              <label className="label" htmlFor={`${ids}-c`}>{t('corrections.form.country')}</label>
              <select id={`${ids}-c`} className="field !w-auto" value={iso3} onChange={(e) => setIso3(e.target.value)} required>
                <option value="">—</option>
                {(meta?.countries ?? []).slice().sort((a, b) => country(a.iso3).localeCompare(country(b.iso3)))
                  .map((c) => <option key={c.iso3} value={c.iso3}>{country(c.iso3)}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor={`${ids}-n`}>{t('corrections.form.note')}</label>
              <textarea id={`${ids}-n`} className="field min-h-[5rem]" value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} required
                placeholder={t('corrections.form.notePh')} />
            </div>
          </>
        )}
        {err && <p className="text-[0.95rem] text-down" role="alert" data-error={errCode}>{err}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" className="btn-primary !text-[1.02rem]" disabled={create.isPending}>{t('corrections.confirm')}</button>
          <span className="text-[0.88rem] text-muted">{t('corrections.form.officialKept')}</span>
        </div>
      </form>

      {aiOn && (
        <div className="border-t border-line-soft pt-4">
          <label className="label inline-flex items-center gap-1.5" htmlFor={`${ids}-w`}><Sparkles size={14} /> {t('corrections.form.inWords')}</label>
          <div className="flex flex-wrap gap-2">
            <input id={`${ids}-w`} className="field min-w-0 flex-1" value={words} onChange={(e) => setWords(e.target.value)} placeholder={t('corrections.form.inWordsPh')} />
            <button type="button" className="btn-secondary" disabled={!words.trim() || interpret.isPending}
              onClick={() => interpret.mutate({ text: words.trim(), lang, context: { table: figure.table, row_id: figure.row_id } }, {
                onSuccess: (r) => { setAiAnswer(r); setAiValue(typedNumber(r.candidates[0]?.proposal?.entered?.value, lang)) },
              })}>
              {interpret.isPending ? t('corrections.box.reading') : t('corrections.box.read')}
            </button>
          </div>
          {interpret.error && <p className="mt-2 text-down">{errorText(interpret.error, lang)}</p>}
          {aiAnswer && (
            <div className="mt-3 space-y-2">
              {(lang === 'en' ? aiAnswer.message_en : aiAnswer.message_it) && <p className="text-[0.95rem] text-charcoal-soft">{lang === 'en' ? aiAnswer.message_en : aiAnswer.message_it}</p>}
              {candidate?.proposal && (
                <>
                  <CandidateView c={candidate} selected onSelect={() => {}} value={aiValue} onValue={setAiValue} />
                  <button type="button" className="btn-primary" disabled={create.isPending}
                    onClick={() => create.mutate({ ...candidate.proposal!.create, ...(candidate.proposal!.create.kind === 'value_correction' ? { value: aiValue } : {}),
                      ai_interpretation: aiAnswer.ai_interpretation }, { onSuccess: (r) => { setResult(r.event); onDone?.(r.event) } })}>
                    {t('corrections.confirm')}
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )}
      <AuthorLine className="border-t border-line-soft pt-3" />
    </div>
  )
}

/** The button under a figure and the panel it opens. Nothing in the read-only phone copy. */
export function FigureDialog({ figure, correction, open, onClose }: {
  figure: FigureRef; correction?: CorrectionBrief | null; open: boolean; onClose: () => void
}) {
  const { t } = useI18n()
  const labelId = useId()
  return (
    <Drawer open={open} onClose={onClose} title={t('corrections.form.title')} eyebrow={t('corrections.form.eyebrow')} size="md" labelId={labelId}>
      <FigureForm figure={figure} correction={correction} />
    </Drawer>
  )
}
