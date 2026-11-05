// Helpers for the supplier-quote section: formatting, Incoterm rules, form <-> API conversion.
import { fmtMoney, fmtNumber } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type {
  Amount, CostBasis, CostItem, CostKind, Destination, FreightBasis, Incoterm, PriceUnit, Quote, QuoteBody,
  QuoteStatus, Rate,
} from './types'

export const INCOTERMS: Incoterm[] = ['EXW', 'FCA', 'FOB', 'CFR', 'CIF', 'DAP', 'DDP']
export const COST_KINDS: CostKind[] = ['origin', 'port', 'broker', 'inland', 'bank', 'other']
export const COST_BASES: CostBasis[] = ['per_container', 'per_kg', 'total', 'pct_goods']
export const FREIGHT_BASES: FreightBasis[] = ['per_container', 'per_kg', 'total']
export const STATUSES: QuoteStatus[] = ['active', 'expiring', 'expired', 'archived']
export const DRUM_KG = 300
export const CONTAINER_KG = 20_000
export const LB_KG = 0.45359237
export const MAX_COMPARE = 6

/** What the quoted price already includes (mirrors services/landed_cost.INCOTERM_RULES). */
export const INCOTERM_RULES: Record<Incoterm, { origin_costs: boolean; freight: boolean; insurance: boolean; duty: boolean }> = {
  EXW: { origin_costs: false, freight: false, insurance: false, duty: false },
  FCA: { origin_costs: true, freight: false, insurance: false, duty: false },
  FOB: { origin_costs: true, freight: false, insurance: false, duty: false },
  CFR: { origin_costs: true, freight: true, insurance: false, duty: false },
  CIF: { origin_costs: true, freight: true, insurance: true, duty: false },
  DAP: { origin_costs: true, freight: true, insurance: true, duty: false },
  DDP: { origin_costs: true, freight: true, insurance: true, duty: true },
}

export const STATUS_TONE: Record<QuoteStatus, 'up' | 'warn' | 'down' | 'outline'> = {
  active: 'up', expiring: 'warn', expired: 'down', archived: 'outline',
}

/** A landed cost per kg: three decimals, so small differences between offers stay visible. */
export function fmtPerKg(v: number | null | undefined, ccy: 'EUR' | 'USD' | string, lang: Lang): string {
  return fmtMoney(v, ccy, lang, 3)
}

export function fmtAmount(v: number | null | undefined, ccy: string, lang: Lang, digits = 2): string {
  return fmtMoney(v, ccy, lang, digits)
}

/** A quoted price: at least 2 decimals, up to 4 ("3,00", "3,05", "1,3625"). */
export function fmtPrice(v: number | null | undefined, lang: Lang): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  let digits = 2
  while (digits < 4 && Math.abs(v * 10 ** digits - Math.round(v * 10 ** digits)) > 1e-9) digits += 1
  return fmtNumber(v, lang, digits)
}

/** Tonnes with the decimals the figure needs ("20 t", "19,2 t", "0,6 t"). */
export function fmtTons(kg: number | null | undefined, lang: Lang): string {
  if (kg === null || kg === undefined || Number.isNaN(kg)) return '—'
  const t = kg / 1000
  const digits = Number.isInteger(t) ? 0 : Number.isInteger(Math.round(t * 1e6) / 1e5) ? 1 : 2
  return `${fmtNumber(t, lang, digits)}\u00a0t`
}

/** Up to `max` decimals, no trailing zeros ("3", "3,05", "1,36"). */
export function fmtPlain(v: number | null | undefined, lang: Lang, max = 4): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  let digits = 0
  while (digits < max && Math.abs(v * 10 ** digits - Math.round(v * 10 ** digits)) > 1e-9) digits += 1
  return fmtNumber(v, lang, digits)
}

export function amountOf(a: Amount | null | undefined, ccy: 'eur' | 'usd'): number | null {
  return a ? a[ccy] : null
}

/** "17,3 %", "1,9 ¢/kg", "0 %", "Esente", or the published text. */
export function fmtRate(r: Rate | null | undefined, lang: Lang, freeLabel: string): string {
  if (!r) return '—'
  const parts: string[] = []
  if (r.ad_valorem_pct !== null && r.ad_valorem_pct !== undefined) {
    if (r.ad_valorem_pct === 0 && r.duty_text && /^\s*free\s*$/i.test(r.duty_text)) return freeLabel
    parts.push(`${fmtPlain(r.ad_valorem_pct, lang, 2)}\u00a0%`)
  }
  if (r.specific_amount !== null && r.specific_amount !== undefined) {
    if (r.specific_currency === 'USD' && (r.specific_unit ?? 'kg') === 'kg' && r.specific_amount < 1) {
      parts.push(`${fmtPlain(r.specific_amount * 100, lang, 2)}\u00a0¢/kg`)
    } else {
      parts.push(`${fmtPlain(r.specific_amount, lang, 4)} ${r.specific_currency ?? ''}/${r.specific_unit ?? 'kg'}`)
    }
  }
  if (parts.length) return parts.join(' + ')
  if (r.duty_text && /^\s*free\s*$/i.test(r.duty_text)) return freeLabel
  return r.duty_text ?? '—'
}

// ---------------------------------------------------------------------------
// Numbers typed by the user
// ---------------------------------------------------------------------------

/** Parse a number typed in Italian or English ("3,05", "3.05", "20.000", "1.234,5", "1,234.5").
 *  In Italian a single dot followed by exactly three digits is a thousands separator ("20.000").
 *  Returns null for an empty field and NaN for text that is not a number. */
export function parseNum(raw: string, lang: Lang): number | null {
  const s = raw.trim().replace(/\s| |'/g, '')
  if (s === '') return null
  let n = s
  const lastComma = n.lastIndexOf(',')
  const lastDot = n.lastIndexOf('.')
  if (lastComma >= 0 && lastDot >= 0) {
    const dec = lastComma > lastDot ? ',' : '.'
    const thou = dec === ',' ? '.' : ','
    n = n.split(thou).join('').replace(dec, '.')
  } else if (lastComma >= 0) {
    n = /^-?\d{1,3}(,\d{3})+$/.test(n) && lang === 'en' ? n.split(',').join('') : n.replace(',', '.')
  } else if (lastDot >= 0 && lang === 'it' && /^-?\d{1,3}(\.\d{3})+$/.test(n)) {
    n = n.split('.').join('')
  }
  if (!/^-?\d*\.?\d+$/.test(n) && !/^-?\d+\.$/.test(n)) return Number.NaN
  return Number(n)
}

/** A number for an input field, in the reader's convention but without thousands separators. */
export function numText(v: number | null | undefined, lang: Lang): string {
  if (v === null || v === undefined) return ''
  const s = String(Math.round(v * 1e6) / 1e6)
  return lang === 'it' ? s.replace('.', ',') : s
}

// ---------------------------------------------------------------------------
// Form state
// ---------------------------------------------------------------------------

export type QtyUnit = 'kg' | 't' | 'drums' | 'containers'
export const QTY_UNITS: QtyUnit[] = ['t', 'kg', 'drums', 'containers']
export const QTY_FACTOR: Record<QtyUnit, number> = { kg: 1, t: 1000, drums: DRUM_KG, containers: CONTAINER_KG }

export interface CostRowState { kind: CostKind; amount: string; basis: CostBasis; currency: string; note: string }

export interface FormState {
  supplier_name: string
  origin_iso3: string
  variety: string
  variety_note: string
  price: string
  price_unit: PriceUnit
  currency: string
  quantity: string
  quantity_unit: QtyUnit
  packaging: string
  incoterm: Incoterm | ''
  incoterm_place: string
  destination: Destination
  shipping_cost: string
  shipping_cost_currency: string
  shipping_cost_basis: FreightBasis
  insurance_pct: string
  duty_mode: 'auto' | 'manual'
  duty_pct: string
  cost_items: CostRowState[]
  date_received: string
  valid_until: string
  notes: string
  // a single "other costs" amount from older records: kept as it is unless removed
  other_costs: number | null
  other_costs_currency: string | null
}

export function todayIso(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export function emptyForm(today = todayIso()): FormState {
  return {
    supplier_name: '', origin_iso3: '', variety: '', variety_note: '', price: '', price_unit: 'kg', currency: 'USD',
    quantity: '', quantity_unit: 't', packaging: '', incoterm: '', incoterm_place: '', destination: 'ITA',
    shipping_cost: '', shipping_cost_currency: 'USD', shipping_cost_basis: 'per_container', insurance_pct: '',
    duty_mode: 'auto', duty_pct: '', cost_items: [], date_received: today, valid_until: '', notes: '',
    other_costs: null, other_costs_currency: null,
  }
}

function bestQtyUnit(kg: number): QtyUnit {
  if (kg >= 1000 && Number.isInteger(kg / 1000)) return 't'
  return 'kg'
}

export function formFromQuote(q: Quote, lang: Lang): FormState {
  const unit = q.quantity_kg ? bestQtyUnit(q.quantity_kg) : 't'
  return {
    supplier_name: q.supplier_name,
    origin_iso3: q.origin_iso3,
    variety: q.variety,
    variety_note: q.variety_note ?? '',
    price: numText(q.price, lang),
    price_unit: q.price_unit,
    currency: q.currency,
    quantity: q.quantity_kg ? numText(q.quantity_kg / QTY_FACTOR[unit], lang) : '',
    quantity_unit: unit,
    packaging: q.packaging ?? '',
    incoterm: q.incoterm ?? '',
    incoterm_place: q.incoterm_place ?? '',
    destination: q.destination,
    shipping_cost: numText(q.shipping_cost, lang),
    shipping_cost_currency: q.shipping_cost_currency ?? q.currency,
    shipping_cost_basis: q.shipping_cost_basis ?? 'per_container',
    insurance_pct: numText(q.insurance_pct, lang),
    duty_mode: q.duty_pct !== null ? 'manual' : 'auto',
    duty_pct: numText(q.duty_pct, lang),
    cost_items: (q.cost_items ?? []).map((c) => ({
      kind: c.kind, amount: numText(c.amount, lang), basis: c.basis, currency: c.currency ?? q.currency, note: c.note ?? '',
    })),
    date_received: q.date_received,
    valid_until: q.valid_until ?? '',
    notes: q.notes ?? '',
    other_costs: q.other_costs,
    other_costs_currency: q.other_costs_currency,
  }
}

/** Field -> message key (in the quotes dictionary). */
export type FormErrors = Partial<Record<string, string>>

export function validateForm(f: FormState, lang: Lang, today = todayIso(), requireSupplier = true): { body: QuoteBody | null; errors: FormErrors } {
  const e: FormErrors = {}
  const num = (raw: string, key: string, { min, max, gt }: { min?: number; max?: number; gt?: number } = {}) => {
    const v = parseNum(raw, lang)
    if (v === null) return null
    if (Number.isNaN(v)) { e[key] = 'form.err.number'; return null }
    if (gt !== undefined && !(v > gt)) { e[key] = 'form.err.positive'; return null }
    if (min !== undefined && v < min) { e[key] = 'form.err.range'; return null }
    if (max !== undefined && v > max) { e[key] = 'form.err.range'; return null }
    return v
  }
  if (requireSupplier && !f.supplier_name.trim()) e.supplier_name = 'form.err.supplier'
  if (!f.origin_iso3) e.origin_iso3 = 'form.err.origin'
  if (!f.variety) e.variety = 'form.err.variety'
  const price = num(f.price, 'price', { gt: 0, max: 1_000_000 })
  if (price === null && !e.price) e.price = 'form.err.price'
  if (!/^[A-Z]{3}$/.test(f.currency)) e.currency = 'form.err.currency'
  const qty = num(f.quantity, 'quantity', { gt: 0 })
  const quantityKg = qty === null ? null : qty * QTY_FACTOR[f.quantity_unit]
  if (quantityKg !== null && quantityKg > 10_000_000) e.quantity = 'form.err.range'
  if (!f.date_received) e.date_received = 'form.err.date'
  else if (f.date_received > today) e.date_received = 'form.err.future'
  if (f.valid_until && f.date_received && f.valid_until < f.date_received) e.valid_until = 'form.err.validBefore'
  const freight = num(f.shipping_cost, 'shipping_cost', { min: 0, max: 1e9 })
  if (freight !== null && !/^[A-Z]{3}$/.test(f.shipping_cost_currency)) e.shipping_cost = 'form.err.currency'
  const insurance = num(f.insurance_pct, 'insurance_pct', { min: 0, max: 20 })
  const duty = f.duty_mode === 'manual' ? num(f.duty_pct, 'duty_pct', { min: 0, max: 200 }) : null
  if (f.duty_mode === 'manual' && duty === null && !e.duty_pct) e.duty_pct = 'form.err.duty'
  const items: CostItem[] = []
  f.cost_items.forEach((c, i) => {
    const key = `cost_${i}`
    const v = parseNum(c.amount, lang)
    if (v === null) { e[key] = 'form.err.amount'; return }
    if (Number.isNaN(v) || v < 0) { e[key] = 'form.err.number'; return }
    if (c.basis === 'pct_goods' && v > 100) { e[key] = 'form.err.pct'; return }
    if (v > 1e9) { e[key] = 'form.err.range'; return }
    items.push({ kind: c.kind, amount: v, basis: c.basis, currency: c.basis === 'pct_goods' ? null : c.currency,
      note: c.note.trim() || null })
  })
  if (Object.keys(e).length || price === null) return { body: null, errors: e }
  return {
    errors: e,
    body: {
      supplier_name: f.supplier_name.trim() || null,
      origin_iso3: f.origin_iso3,
      variety: f.variety,
      variety_note: f.variety_note.trim() || null,
      price,
      price_unit: f.price_unit,
      currency: f.currency,
      quantity_kg: quantityKg,
      packaging: f.packaging.trim() || null,
      incoterm: f.incoterm || null,
      incoterm_place: f.incoterm_place.trim() || null,
      shipping_cost: freight,
      shipping_cost_currency: freight === null ? null : f.shipping_cost_currency,
      shipping_cost_basis: freight === null ? null : f.shipping_cost_basis,
      insurance_pct: insurance,
      duty_pct: duty,
      other_costs: f.other_costs,
      other_costs_currency: f.other_costs === null ? null : f.other_costs_currency ?? f.currency,
      cost_items: items,
      destination: f.destination,
      date_received: f.date_received,
      valid_until: f.valid_until || null,
      notes: f.notes.trim() || null,
    },
  }
}

/** The editable body of a saved quote (for what-if recalculations and saving them). */
export function bodyFromQuote(q: Quote): QuoteBody {
  return {
    supplier_name: q.supplier_name, origin_iso3: q.origin_iso3, variety: q.variety, variety_note: q.variety_note,
    price: q.price, price_unit: q.price_unit, currency: q.currency, quantity_kg: q.quantity_kg, packaging: q.packaging,
    incoterm: q.incoterm, incoterm_place: q.incoterm_place, shipping_cost: q.shipping_cost,
    shipping_cost_currency: q.shipping_cost_currency, shipping_cost_basis: q.shipping_cost_basis,
    insurance_pct: q.insurance_pct, duty_pct: q.duty_pct, other_costs: q.other_costs,
    other_costs_currency: q.other_costs_currency, cost_items: q.cost_items ?? [], destination: q.destination,
    date_received: q.date_received, valid_until: q.valid_until, notes: q.notes,
  }
}

export function sameBody(a: QuoteBody, b: QuoteBody): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}
