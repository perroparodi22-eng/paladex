// Add / edit a supplier quote. Large inputs, plain Italian labels, the Incoterm explained in plain
// words, validation before saving, and a live preview of the landed cost while typing.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Check, Info, Lock, Minus, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ErrorBlock, Loading, Segmented } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtNumber } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { Drawer } from './Drawer'
import type { CostBasis, CostKind, Destination, FreightBasis, Incoterm, Landed, PriceUnit, Quote, QuoteBody, QuoteDetail, QuotesMeta } from './types'
import {
  CONTAINER_KG, COST_BASES, COST_KINDS, DRUM_KG, emptyForm, fmtPerKg, fmtPlain, formFromQuote, FREIGHT_BASES,
  fmtTons, INCOTERM_RULES, INCOTERMS, LB_KG, parseNum, QTY_FACTOR, QTY_UNITS, todayIso, validateForm,
  type FormState, type QtyUnit,
} from './utils'

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const h = setTimeout(() => setV(value), ms)
    return () => clearTimeout(h)
  }, [value, ms])
  return v
}

function Field({ label, error, hint, children, className, required, htmlFor }: {
  label: string; error?: string; hint?: ReactNode; children: ReactNode; className?: string; required?: boolean; htmlFor?: string
}) {
  const { t } = useI18n()
  return (
    <div className={clsx('min-w-0', className, error && '[&_.field]:!border-down')}>
      <label htmlFor={htmlFor} className="label">
        {label}{required && <span className="text-down" aria-hidden> *</span>}
      </label>
      {children}
      {error ? <p className="mt-1 text-[0.86rem] text-down" role="alert">{t(`quotes.${error}`)}</p>
        : hint ? <p className="mt-1 text-[0.84rem] text-muted">{hint}</p> : null}
    </div>
  )
}

function Group({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <fieldset className="mb-6 min-w-0 rounded-sm border border-line bg-white p-4 sm:p-5">
      <legend className="px-1 font-serif text-[1.08rem] font-semibold text-charcoal">{title}</legend>
      {aside && <div className="-mt-1 mb-3 text-[0.86rem] text-muted">{aside}</div>}
      {children}
    </fieldset>
  )
}

const BIG = 'field !py-2.5 text-[1rem]'

function Included({ yes, label }: { yes: boolean; label: string }) {
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-[0.82rem]',
      yes ? 'border-forest-100 bg-forest-50 text-forest-800' : 'border-line bg-paper text-muted')}>
      {yes ? <Check size={13} /> : <Minus size={13} />} {label}
    </span>
  )
}

export function IncotermExplainer({ incoterm }: { incoterm: Incoterm | '' }) {
  const { t } = useI18n()
  if (!incoterm) return <p className="mt-2 text-[0.88rem] text-muted">{t('quotes.incoterm.none')}</p>
  const r = INCOTERM_RULES[incoterm]
  return (
    <div className="mt-2 rounded-sm border border-forest-100 bg-forest-50/60 px-3 py-2">
      <div className="text-[0.9rem] font-medium text-forest-800">{incoterm} · {t(`quotes.incoterm.${incoterm}.name`)}</div>
      <p className="mt-0.5 text-[0.9rem] leading-relaxed text-charcoal-soft">{t(`quotes.incoterm.${incoterm}.plain`)}</p>
      <div className="mt-2 flex flex-wrap gap-1.5" aria-label={t('quotes.incoterm.includes')}>
        <span className="text-[0.82rem] text-muted">{t('quotes.incoterm.includes')}</span>
        <Included yes={r.origin_costs} label={t('quotes.incoterm.originCosts')} />
        <Included yes={r.freight} label={t('quotes.form.freight')} />
        <Included yes={r.insurance} label={t('quotes.form.insurance')} />
        <Included yes={r.duty} label={t('quotes.form.duty')} />
      </div>
    </div>
  )
}

function Preview({ landed, loading, valid }: { landed: Landed | undefined; loading: boolean; valid: boolean }) {
  const { t, lang } = useI18n()
  if (!valid) return <span className="text-muted">{t('quotes.form.previewNeeds')}</span>
  if (!landed) return <span className="text-muted">{loading ? t('ui.loading') : t('quotes.form.previewNeeds')}</span>
  const h = landed.headline
  if (h.eur_per_kg_min === null || h.eur_per_kg_max === null) {
    return <span className="text-warn">{t('quotes.form.previewNone')}</span>
  }
  const range = h.alternatives && Math.abs(h.eur_per_kg_max - h.eur_per_kg_min) > 1e-9
  return (
    <span className="flex flex-wrap items-baseline gap-x-2">
      <span className="text-muted">{t('quotes.form.preview')}</span>
      <span className="num text-[1.05rem] text-charcoal">
        {range ? `${fmtPerKg(h.eur_per_kg_min, 'EUR', lang)} – ${fmtPerKg(h.eur_per_kg_max, 'EUR', lang)}` : fmtPerKg(h.eur_per_kg_max, 'EUR', lang)} /kg
      </span>
      {range && <span className="text-[0.84rem] text-muted">{t('quotes.form.previewAlternatives')}</span>}
      {!h.complete && <span className="text-[0.84rem] text-warn">{t('quotes.form.previewIncomplete', { n: h.missing.length })}</span>}
    </span>
  )
}

export function QuoteForm({ mode, quoteId, suppliers, onClose, onSaved }: {
  mode: 'new' | 'edit'
  quoteId?: number
  suppliers: string[]
  onClose: () => void
  onSaved: (q: Quote) => void
}) {
  const { t, lang } = useI18n()
  const { meta, country } = useLabels()
  const qc = useQueryClient()
  const today = todayIso()
  const qmeta = useQuery({ queryKey: ['quotes', 'meta'], queryFn: () => api.get<QuotesMeta>('/quotes/meta'), staleTime: 10 * 60_000 })
  const existing = useQuery({
    queryKey: ['quotes', 'detail', quoteId, 'received', CONTAINER_KG],
    queryFn: () => api.get<QuoteDetail>(`/quotes/${quoteId}`, { fx: 'received' }),
    enabled: mode === 'edit' && quoteId !== undefined,
  })
  const [form, setForm] = useState<FormState>(() => emptyForm(today))
  const [initial, setInitial] = useState<FormState | null>(mode === 'new' ? emptyForm(today) : null)
  useEffect(() => {
    if (mode === 'edit' && existing.data && initial === null) {
      const f = formFromQuote(existing.data.quote, lang)
      setForm(f)
      setInitial(f)
    }
  }, [mode, existing.data, initial, lang])
  const [submitted, setSubmitted] = useState(false)
  const [confirmClose, setConfirmClose] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)

  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }))
  const { body, errors } = validateForm(form, lang, today)
  const previewBody = useMemo(() => validateForm(form, lang, today, false).body, [form, lang, today])
  const debounced = useDebounced<QuoteBody | null>(previewBody, 450)
  const preview = useQuery({
    queryKey: ['quotes', 'calc', debounced, 'received', CONTAINER_KG],
    queryFn: () => api.post<Landed>('/quotes/calculate', debounced),
    enabled: Boolean(debounced),
    placeholderData: keepPreviousData,
    retry: false,
  })
  const dirty = initial !== null && JSON.stringify(form) !== JSON.stringify(initial)
  const err = (k: string) => (submitted ? errors[k] : undefined)

  const save = useMutation({
    mutationFn: (b: QuoteBody) => (mode === 'new' ? api.post<Quote>('/quotes', b) : api.put<Quote>(`/quotes/${quoteId}`, b)),
    onSuccess: (q) => { qc.invalidateQueries({ queryKey: ['quotes'] }); onSaved(q) },
  })

  const submit = () => {
    setSubmitted(true)
    if (!body) {
      requestAnimationFrame(() => bodyRef.current?.querySelector('[role="alert"]')?.scrollIntoView({ block: 'center', behavior: 'smooth' }))
      return
    }
    save.mutate(body)
  }
  const requestClose = () => (dirty ? setConfirmClose(true) : onClose())

  const countries = useMemo(() => {
    const list = [...(meta?.countries ?? [])].filter((c) => c.iso3 !== 'WLD')
    const name = (c: (typeof list)[number]) => (lang === 'it' ? c.name_it : c.name_en)
    list.sort((a, b) => name(a).localeCompare(name(b), lang))
    return { prio: list.filter((c) => c.priority), rest: list.filter((c) => !c.priority), name }
  }, [meta, lang])
  const varieties = useMemo(() => {
    const list = [...(meta?.varieties ?? [])].filter((v) => v.key !== 'unspecified')
    return { core: list.filter((v) => v.core), rest: list.filter((v) => !v.core) }
  }, [meta])
  const currencies = qmeta.data?.currencies ?? ['EUR', 'USD']
  const otherCcy = !currencies.includes(form.currency)
  const rule = form.incoterm ? INCOTERM_RULES[form.incoterm] : null
  const price = parseNum(form.price, lang)
  const qty = parseNum(form.quantity, lang)
  const qtyKg = qty !== null && !Number.isNaN(qty) ? qty * QTY_FACTOR[form.quantity_unit] : null
  const perKgPrice = price !== null && !Number.isNaN(price) ? (form.price_unit === 'lb' ? price / LB_KG : price) : null
  const implausible = perKgPrice !== null && ['EUR', 'USD', 'GBP', 'CHF'].includes(form.currency) && (perKgPrice > 60 || perKgPrice < 0.3)

  const title = mode === 'new' ? t('quotes.form.titleNew') : t('quotes.form.titleEdit')
  const footer = (
    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div className="min-w-0 flex-1 text-[0.92rem]" aria-live="polite">
        <Preview landed={preview.data} loading={preview.isFetching} valid={Boolean(previewBody)} />
      </div>
      {confirmClose ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <span className="text-[0.9rem] text-charcoal-soft">{t('quotes.form.confirmClose')}</span>
          <button type="button" className="btn-secondary" onClick={() => setConfirmClose(false)}>{t('quotes.form.keepEditing')}</button>
          <button type="button" className="btn bg-down text-white border-down hover:bg-[#8a2f22]" onClick={onClose}>{t('quotes.form.discard')}</button>
        </div>
      ) : (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <button type="button" className="btn-secondary" onClick={requestClose}>{t('ui.cancel')}</button>
          <button type="button" className="btn-primary !px-5" onClick={submit} disabled={save.isPending || (mode === 'edit' && !initial)}>
            {mode === 'new' ? t('quotes.form.saveNew') : t('quotes.form.saveEdit')}
          </button>
        </div>
      )}
    </div>
  )

  if (mode === 'edit' && (existing.isLoading || existing.error)) {
    return (
      <Drawer open onClose={onClose} labelId="quote-form-title" title={title} size="lg">
        {existing.error ? <ErrorBlock error={existing.error} onRetry={() => existing.refetch()} /> : <Loading />}
      </Drawer>
    )
  }

  return (
    <Drawer open onClose={requestClose} labelId="quote-form-title" title={title} eyebrow={t('quotes.form.eyebrow')}
      meta={<span className="inline-flex items-center gap-1.5"><Lock size={14} /> {t('quotes.privacyShort')}</span>}
      footer={footer} size="lg" closeOnBackdrop={false}>
      <div ref={bodyRef}>
        <p className="mb-4 text-[0.9rem] text-muted">{t('quotes.form.required')}</p>
        {submitted && !body && <div className="mb-4 rounded-sm border border-[#EBCDC6] bg-[#FBF1EE] px-3 py-2 text-[0.92rem] text-down">{t('quotes.form.fixErrors')}</div>}
        {save.error && <div className="mb-4"><ErrorBlock error={save.error} /></div>}

        <Group title={t('quotes.form.groupProduct')}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('quotes.form.supplier')} required error={err('supplier_name')} htmlFor="qf-supplier" className="sm:col-span-2">
              <input id="qf-supplier" className={BIG} value={form.supplier_name} list="qf-suppliers" autoComplete="off" maxLength={200}
                placeholder={t('quotes.form.supplierPlaceholder')} onChange={(e) => set({ supplier_name: e.target.value })} />
              <datalist id="qf-suppliers">{suppliers.map((s) => <option key={s} value={s} />)}</datalist>
            </Field>
            <Field label={t('quotes.form.origin')} required error={err('origin_iso3')} htmlFor="qf-origin">
              <select id="qf-origin" className={clsx(BIG, 'pr-8')} value={form.origin_iso3} onChange={(e) => set({ origin_iso3: e.target.value })}>
                <option value="">{t('quotes.form.choose')}</option>
                <optgroup label={t('quotes.form.originsMain')}>
                  {countries.prio.map((c) => <option key={c.iso3} value={c.iso3}>{countries.name(c)}</option>)}
                </optgroup>
                <optgroup label={t('quotes.form.originsAll')}>
                  {countries.rest.map((c) => <option key={c.iso3} value={c.iso3}>{countries.name(c)}</option>)}
                </optgroup>
              </select>
            </Field>
            <Field label={t('quotes.form.variety')} required error={err('variety')} htmlFor="qf-variety">
              <select id="qf-variety" className={clsx(BIG, 'pr-8')} value={form.variety} onChange={(e) => set({ variety: e.target.value })}>
                <option value="">{t('quotes.form.choose')}</option>
                {varieties.core.map((v) => <option key={v.key} value={v.key}>{v[lang]}</option>)}
                {varieties.rest.length > 0 && (
                  <optgroup label={t('quotes.form.varietiesMore')}>
                    {varieties.rest.map((v) => <option key={v.key} value={v.key}>{v[lang]}</option>)}
                  </optgroup>
                )}
              </select>
            </Field>
            <Field label={t('quotes.form.varietyNote')} htmlFor="qf-vnote" hint={t('quotes.form.varietyNoteHint')}>
              <input id="qf-vnote" className={BIG} value={form.variety_note} maxLength={200} onChange={(e) => set({ variety_note: e.target.value })} />
            </Field>
            <Field label={t('quotes.form.packaging')} htmlFor="qf-pack" hint={t('quotes.form.packagingHint')}>
              <input id="qf-pack" className={BIG} value={form.packaging} list="qf-packs" maxLength={120} onChange={(e) => set({ packaging: e.target.value })} />
              <datalist id="qf-packs">
                {['packDrums', 'packDrumsLiner', 'packIbc'].map((k) => <option key={k} value={t(`quotes.form.${k}`)} />)}
              </datalist>
            </Field>
            <Field label={t('quotes.form.quantity')} error={err('quantity')} htmlFor="qf-qty" className="sm:col-span-2"
              hint={qtyKg ? t('quotes.form.quantityHint', {
                kg: fmtNumber(qtyKg, lang), t: fmtTons(qtyKg, lang),
                drums: fmtNumber(qtyKg / DRUM_KG, lang, Number.isInteger(qtyKg / DRUM_KG) ? 0 : 1),
                containers: fmtNumber(qtyKg / CONTAINER_KG, lang, Number.isInteger(qtyKg / CONTAINER_KG) ? 0 : 2),
              }) : t('quotes.form.quantityEmpty')}>
              <div className="flex gap-2">
                <input id="qf-qty" className={clsx(BIG, 'num min-w-0 flex-1')} inputMode="decimal" value={form.quantity}
                  onChange={(e) => set({ quantity: e.target.value })} />
                <select className={clsx(BIG, 'w-auto pr-8')} value={form.quantity_unit} aria-label={t('quotes.form.quantityUnit')}
                  onChange={(e) => set({ quantity_unit: e.target.value as QtyUnit })}>
                  {QTY_UNITS.map((u) => <option key={u} value={u}>{t(`quotes.qty.${u}`)}</option>)}
                </select>
              </div>
            </Field>
          </div>
        </Group>

        <Group title={t('quotes.form.groupPrice')}>
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,9rem)_minmax(0,10rem)]">
            <Field label={t('quotes.form.price')} required error={err('price')} htmlFor="qf-price"
              hint={implausible ? <span className="text-warn">{t('quotes.form.priceImplausible')}</span>
                : form.price_unit === 'lb' && perKgPrice ? t('quotes.form.perKgEquivalent', { v: fmtPlain(Math.round(perKgPrice * 1e4) / 1e4, lang), ccy: form.currency }) : undefined}>
              <input id="qf-price" className={clsx(BIG, 'num')} inputMode="decimal" value={form.price} placeholder={t('quotes.form.pricePlaceholder')}
                onChange={(e) => set({ price: e.target.value })} />
            </Field>
            <Field label={t('quotes.form.currency')} required error={err('currency')} htmlFor="qf-ccy">
              <select id="qf-ccy" className={clsx(BIG, 'pr-8')} value={otherCcy ? '__other' : form.currency}
                onChange={(e) => set({ currency: e.target.value === '__other' ? '' : e.target.value })}>
                {currencies.map((c) => <option key={c} value={c}>{c}</option>)}
                <option value="__other">{t('quotes.form.otherCurrency')}</option>
              </select>
              {otherCcy && (
                <input className={clsx(BIG, 'mt-2 uppercase')} maxLength={3} value={form.currency} placeholder="ARS"
                  aria-label={t('quotes.form.otherCurrency')} onChange={(e) => set({ currency: e.target.value.toUpperCase() })} />
              )}
            </Field>
            <Field label={t('quotes.form.priceUnit')} htmlFor="qf-unit">
              <select id="qf-unit" className={clsx(BIG, 'pr-8')} value={form.price_unit} onChange={(e) => set({ price_unit: e.target.value as PriceUnit })}>
                <option value="kg">{t('quotes.form.perKg')}</option>
                <option value="lb">{t('quotes.form.perLb')}</option>
              </select>
            </Field>
          </div>
          {otherCcy && <p className="mt-2 text-[0.86rem] text-warn">{t('quotes.form.otherCurrencyHint')}</p>}
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label={t('quotes.form.incoterm')} htmlFor="qf-inco">
              <select id="qf-inco" className={clsx(BIG, 'pr-8')} value={form.incoterm} onChange={(e) => set({ incoterm: e.target.value as Incoterm | '' })}>
                <option value="">{t('quotes.form.incotermNone')}</option>
                {INCOTERMS.map((i) => <option key={i} value={i}>{i} – {t(`quotes.incoterm.${i}.name`)}</option>)}
              </select>
            </Field>
            <Field label={t('quotes.form.place')} htmlFor="qf-place" hint={t('quotes.form.placeHint')}>
              <input id="qf-place" className={BIG} value={form.incoterm_place} maxLength={120} onChange={(e) => set({ incoterm_place: e.target.value })} />
            </Field>
          </div>
          <IncotermExplainer incoterm={form.incoterm} />
          <div className="mt-4">
            <span className="label">{t('quotes.form.destination')}</span>
            <Segmented<Destination> value={form.destination} onChange={(destination) => set({ destination })}
              options={[{ value: 'ITA', label: t('quotes.dest.ITA') }, { value: 'USA', label: t('quotes.dest.USA') }]} />
          </div>
        </Group>

        <Group title={t('quotes.form.groupTransport')} aside={t('quotes.form.groupTransportHint')}>
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,8rem)_minmax(0,12rem)]">
            <Field label={t('quotes.form.freight')} error={err('shipping_cost')} htmlFor="qf-freight"
              hint={rule?.freight ? t('quotes.form.freightIncluded', { incoterm: form.incoterm }) : t('quotes.form.freightHint')}>
              <input id="qf-freight" className={clsx(BIG, 'num')} inputMode="decimal" value={form.shipping_cost}
                placeholder={t('quotes.notGiven')} onChange={(e) => set({ shipping_cost: e.target.value })} />
            </Field>
            <Field label={t('quotes.form.currency')} htmlFor="qf-fccy">
              <select id="qf-fccy" className={clsx(BIG, 'pr-8')} value={form.shipping_cost_currency} onChange={(e) => set({ shipping_cost_currency: e.target.value })}>
                {currencies.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <Field label={t('quotes.form.basis')} htmlFor="qf-fbasis">
              <select id="qf-fbasis" className={clsx(BIG, 'pr-8')} value={form.shipping_cost_basis} onChange={(e) => set({ shipping_cost_basis: e.target.value as FreightBasis })}>
                {FREIGHT_BASES.map((b) => <option key={b} value={b}>{t(`quotes.basis.${b}`)}</option>)}
              </select>
            </Field>
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label={t('quotes.form.insurancePct')} error={err('insurance_pct')} htmlFor="qf-ins"
              hint={rule?.insurance ? t('quotes.form.insuranceIncluded', { incoterm: form.incoterm }) : t('quotes.form.insuranceHint')}>
              <div className="relative">
                <input id="qf-ins" className={clsx(BIG, 'num !pr-10')} inputMode="decimal" value={form.insurance_pct}
                  placeholder={t('quotes.notGivenF')} onChange={(e) => set({ insurance_pct: e.target.value })} />
                <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted">%</span>
              </div>
            </Field>
            <div className="min-w-0">
              <span className="label">{t('quotes.form.duty')}</span>
              <Segmented<'auto' | 'manual'> value={form.duty_mode} onChange={(duty_mode) => set({ duty_mode })}
                options={[{ value: 'auto', label: t('quotes.form.dutyAuto') }, { value: 'manual', label: t('quotes.form.dutyManual') }]} />
              {form.duty_mode === 'manual' ? (
                <div className="mt-2">
                  <div className="relative max-w-[12rem]">
                    <input className={clsx(BIG, 'num !pr-10')} inputMode="decimal" value={form.duty_pct} aria-label={t('quotes.form.dutyPct')}
                      onChange={(e) => set({ duty_pct: e.target.value })} />
                    <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted">%</span>
                  </div>
                  {err('duty_pct') ? <p className="mt-1 text-[0.86rem] text-down" role="alert">{t(`quotes.${err('duty_pct')}`)}</p>
                    : <p className="mt-1 text-[0.84rem] text-muted">{t('quotes.form.dutyManualHint')}</p>}
                </div>
              ) : (
                <p className="mt-1 text-[0.84rem] text-muted">{t('quotes.form.dutyAutoHint')}</p>
              )}
            </div>
          </div>
        </Group>

        <Group title={t('quotes.form.groupCosts')} aside={t('quotes.form.groupCostsHint')}>
          {form.cost_items.length === 0 && <p className="mb-3 text-[0.9rem] text-muted">{t('quotes.form.noCosts')}</p>}
          <div className="space-y-3">
            {form.cost_items.map((c, i) => {
              const upd = (patch: Partial<FormState['cost_items'][number]>) =>
                set({ cost_items: form.cost_items.map((x, j) => (j === i ? { ...x, ...patch } : x)) })
              return (
                <div key={i} className="rounded-sm border border-line-soft bg-paper/60 p-3">
                  <div className="grid gap-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_minmax(0,7rem)_minmax(0,11rem)_auto] sm:items-end">
                    <Field label={t('quotes.form.costKind')} htmlFor={`qf-ck-${i}`}>
                      <select id={`qf-ck-${i}`} className={clsx(BIG, 'pr-8')} value={c.kind} onChange={(e) => upd({ kind: e.target.value as CostKind })}>
                        {COST_KINDS.map((k) => <option key={k} value={k}>{t(`quotes.cost.${k}`)}</option>)}
                      </select>
                    </Field>
                    <Field label={t('quotes.form.amount')} error={err(`cost_${i}`)} htmlFor={`qf-ca-${i}`}>
                      <input id={`qf-ca-${i}`} className={clsx(BIG, 'num')} inputMode="decimal" value={c.amount} onChange={(e) => upd({ amount: e.target.value })} />
                    </Field>
                    <Field label={t('quotes.form.currency')} htmlFor={`qf-cc-${i}`}>
                      <select id={`qf-cc-${i}`} className={clsx(BIG, 'pr-7')} value={c.basis === 'pct_goods' ? '%' : c.currency}
                        disabled={c.basis === 'pct_goods'} onChange={(e) => upd({ currency: e.target.value })}>
                        {c.basis === 'pct_goods' ? <option value="%">%</option> : currencies.map((x) => <option key={x} value={x}>{x}</option>)}
                      </select>
                    </Field>
                    <Field label={t('quotes.form.basis')} htmlFor={`qf-cb-${i}`}>
                      <select id={`qf-cb-${i}`} className={clsx(BIG, 'pr-8')} value={c.basis} onChange={(e) => upd({ basis: e.target.value as CostBasis })}>
                        {COST_BASES.map((b) => <option key={b} value={b}>{t(`quotes.basis.${b}`)}</option>)}
                      </select>
                    </Field>
                    <button type="button" className="btn-ghost justify-center !px-2.5 !py-2.5 text-down" aria-label={t('quotes.form.removeCost')}
                      title={t('quotes.form.removeCost')} onClick={() => set({ cost_items: form.cost_items.filter((_, j) => j !== i) })}>
                      <Trash2 size={18} />
                    </button>
                  </div>
                  <input className="field mt-2 text-[0.92rem]" value={c.note} maxLength={200} placeholder={t('quotes.form.costNote')}
                    aria-label={t('quotes.form.costNote')} onChange={(e) => upd({ note: e.target.value })} />
                </div>
              )
            })}
          </div>
          {form.other_costs !== null && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-sm border border-line-soft bg-paper/60 px-3 py-2 text-[0.9rem]">
              <span>{t('quotes.form.legacyOther', { v: `${fmtPlain(form.other_costs, lang)} ${form.other_costs_currency ?? form.currency}` })}</span>
              <button type="button" className="btn-ghost !py-1 text-down" onClick={() => set({ other_costs: null, other_costs_currency: null })}>
                <Trash2 size={15} /> {t('quotes.form.removeCost')}
              </button>
            </div>
          )}
          <button type="button" className="btn-secondary mt-3" disabled={form.cost_items.length >= 12}
            onClick={() => set({ cost_items: [...form.cost_items, { kind: 'port', amount: '', basis: 'per_container', currency: 'EUR', note: '' }] })}>
            <Plus size={16} /> {t('quotes.form.addCost')}
          </button>
        </Group>

        <Group title={t('quotes.form.groupDates')}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('quotes.form.dateReceived')} required error={err('date_received')} htmlFor="qf-date"
              hint={t('quotes.form.dateReceivedHint')}>
              <input id="qf-date" type="date" className={BIG} value={form.date_received} max={today} onChange={(e) => set({ date_received: e.target.value })} />
            </Field>
            <Field label={t('quotes.form.validUntil')} error={err('valid_until')} htmlFor="qf-valid" hint={t('quotes.form.validUntilHint')}>
              <input id="qf-valid" type="date" className={BIG} value={form.valid_until} min={form.date_received || undefined}
                onChange={(e) => set({ valid_until: e.target.value })} />
            </Field>
            <Field label={t('quotes.form.notes')} htmlFor="qf-notes" className="sm:col-span-2">
              <textarea id="qf-notes" className={clsx(BIG, 'min-h-[6rem]')} value={form.notes} maxLength={4000}
                onChange={(e) => set({ notes: e.target.value })} />
            </Field>
          </div>
        </Group>

        <p className="flex items-start gap-2 text-[0.86rem] text-muted"><Info size={15} className="mt-0.5 shrink-0" />{t('quotes.form.afterSave', { origin: form.origin_iso3 ? country(form.origin_iso3) : t('quotes.form.theOrigin') })}</p>
      </div>
    </Drawer>
  )
}
