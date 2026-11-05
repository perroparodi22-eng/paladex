// Editable assumptions in the quote drawer: change the freight, insurance, duty, destination, the
// exchange-rate date or the container weight and see the landed cost again. Nothing is saved until
// "Salva nell'offerta" (the exchange-rate date and container weight are view settings only).
import clsx from 'clsx'
import { RotateCcw, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Segmented } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type { Destination, FreightBasis, FxMode, QuoteBody } from './types'
import { FREIGHT_BASES, INCOTERM_RULES, numText, parseNum } from './utils'

export function NumField({ value, onCommit, lang, label, ariaLabel, suffix, min = 0, max, disabled, id, placeholder, className }: {
  value: number | null
  onCommit: (v: number | null) => void
  lang: Lang
  label?: string
  ariaLabel?: string
  suffix?: string
  min?: number
  max?: number
  disabled?: boolean
  id: string
  placeholder?: string
  className?: string
}) {
  const [text, setText] = useState(numText(value, lang))
  const [bad, setBad] = useState(false)
  useEffect(() => {
    const parsed = parseNum(text, lang)
    if (parsed !== value && !(parsed === null && value === null)) setText(numText(value, lang))
    // only a change from outside (a reset, another field) rewrites the text being typed
  }, [value, lang])
  return (
    <label htmlFor={id} className={clsx('block min-w-0', className)}>
      {label && <span className="label">{label}</span>}
      <span className="relative block">
        <input id={id} aria-label={label ? undefined : ariaLabel} type="text" inputMode="decimal" className={clsx('field num', suffix && '!pr-12', bad && '!border-down')}
          value={text} disabled={disabled} placeholder={placeholder} aria-invalid={bad}
          onChange={(e) => {
            setText(e.target.value)
            const v = parseNum(e.target.value, lang)
            const ok = v === null || (!Number.isNaN(v) && v >= min && (max === undefined || v <= max))
            setBad(!ok)
            if (ok) onCommit(v)
          }} />
        {suffix && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[0.85rem] text-muted">{suffix}</span>}
      </span>
    </label>
  )
}

export function Assumptions({ draft, onChange, fx, onFx, receivedOn, containerKg, onContainerKg, currencies, dirty, onSave, onReset, saving, saveError }: {
  draft: QuoteBody
  onChange: (patch: Partial<QuoteBody>) => void
  fx: FxMode
  onFx: (v: FxMode) => void
  receivedOn: string
  containerKg: number
  onContainerKg: (v: number) => void
  currencies: string[]
  dirty: boolean
  onSave: () => void
  onReset: () => void
  saving: boolean
  saveError?: string | null
}) {
  const { t, lang } = useI18n()
  const rule = draft.incoterm ? INCOTERM_RULES[draft.incoterm] : null
  const ccys = currencies.includes(draft.shipping_cost_currency ?? '') || !draft.shipping_cost_currency ? currencies : [...currencies, draft.shipping_cost_currency]
  return (
    <div className="rounded-sm border border-line bg-white p-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="min-w-0">
          <span className="label">{t('quotes.form.destination')}</span>
          <Segmented<Destination> value={draft.destination} onChange={(destination) => onChange({ destination })}
            options={[{ value: 'ITA', label: t('quotes.dest.ITA') }, { value: 'USA', label: t('quotes.dest.USA') }]} />
        </div>
        <div className="min-w-0">
          <span className="label">{t('quotes.fx.label')}</span>
          <Segmented<FxMode> value={fx} onChange={onFx}
            options={[{ value: 'received', label: t('quotes.fx.receivedOn', { date: fmtDate(receivedOn, lang) }) }, { value: 'today', label: t('quotes.fx.today') }]} />
        </div>

        <fieldset className="min-w-0 md:col-span-2">
          <legend className="label">{t('quotes.form.freight')}</legend>
          {rule?.freight ? (
            <p className="text-[0.88rem] text-muted">{t('quotes.form.freightIncluded', { incoterm: draft.incoterm ?? '' })}</p>
          ) : (
            <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_7rem_minmax(0,11rem)]">
              <NumField id="wi-freight" label={t('quotes.form.amount')} value={draft.shipping_cost} lang={lang} max={1e9}
                placeholder={t('quotes.notGiven')}
                onCommit={(v) => onChange({
                  shipping_cost: v,
                  shipping_cost_currency: v === null ? null : draft.shipping_cost_currency ?? draft.currency,
                  shipping_cost_basis: v === null ? null : draft.shipping_cost_basis ?? 'per_container',
                })} />
              <label className="block min-w-0">
                <span className="label">{t('quotes.form.currency')}</span>
                <select className="field pr-7" value={draft.shipping_cost_currency ?? draft.currency} disabled={draft.shipping_cost === null}
                  onChange={(e) => onChange({ shipping_cost_currency: e.target.value })}>
                  {ccys.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
              <label className="block min-w-0">
                <span className="label">{t('quotes.form.basis')}</span>
                <select className="field pr-7" value={draft.shipping_cost_basis ?? 'per_container'} disabled={draft.shipping_cost === null}
                  onChange={(e) => onChange({ shipping_cost_basis: e.target.value as FreightBasis })}>
                  {FREIGHT_BASES.map((b) => <option key={b} value={b}>{t(`quotes.basis.${b}`)}</option>)}
                </select>
              </label>
            </div>
          )}
        </fieldset>

        {rule?.insurance ? (
          <div className="min-w-0">
            <span className="label">{t('quotes.form.insurance')}</span>
            <p className="text-[0.88rem] text-muted">{t('quotes.form.insuranceIncluded', { incoterm: draft.incoterm ?? '' })}</p>
          </div>
        ) : (
          <NumField id="wi-insurance" label={t('quotes.form.insurance')} value={draft.insurance_pct} lang={lang} max={20} suffix="%"
            placeholder={t('quotes.notGivenF')} onCommit={(v) => onChange({ insurance_pct: v })} />
        )}

        <div className="min-w-0">
          <span className="label">{t('quotes.form.duty')}</span>
          <div className="flex flex-wrap items-end gap-2">
            <Segmented<'auto' | 'manual'> value={draft.duty_pct === null ? 'auto' : 'manual'}
              onChange={(m) => onChange({ duty_pct: m === 'auto' ? null : draft.duty_pct ?? 0 })}
              options={[{ value: 'auto', label: t('quotes.form.dutyAuto') }, { value: 'manual', label: t('quotes.form.dutyManual') }]} />
            {draft.duty_pct !== null && (
              <NumField id="wi-duty" ariaLabel={t('quotes.form.dutyPct')} className="w-28" value={draft.duty_pct} lang={lang} max={200} suffix="%"
                onCommit={(v) => onChange({ duty_pct: v ?? 0 })} />
            )}
          </div>
        </div>

        <NumField id="wi-container" label={t('quotes.form.containerKg')} value={containerKg} lang={lang} min={1000} max={40000} suffix="kg"
          onCommit={(v) => { if (v !== null) onContainerKg(v) }} />
      </div>

      {dirty && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-sm border border-gold-light/60 bg-gold-pale/60 px-3 py-2 text-[0.9rem] text-gold-dark">
          <span>{t('quotes.whatif.banner')}</span>
          <span className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary !py-1" onClick={onReset}><RotateCcw size={15} /> {t('quotes.whatif.reset')}</button>
            <button type="button" className="btn-primary !py-1" onClick={onSave} disabled={saving}><Save size={15} /> {t('quotes.whatif.save')}</button>
          </span>
          {saveError && <span className="w-full text-down">{saveError}</span>}
        </div>
      )}
    </div>
  )
}
