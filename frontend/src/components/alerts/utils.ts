// Helpers for the alert center: default conditions per rule type, what the editor can offer
// (only things that have data), and messages in the UI language.
import { ApiError } from '@/lib/api'
import type { Lang } from '@/lib/types'
import type { AlertType, OptionsResponse, PriceOption, RuleParams, TradeOption } from './types'

export function str(v: unknown): string | null {
  return typeof v === 'string' && v ? v : null
}

export function strList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x !== '') : []
}

export function num(v: unknown, fallback: number): number {
  const n = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
  return Number.isFinite(n) ? n : fallback
}

/** Backend messages are "Italiano / English": keep the half in the UI language. */
export function errorText(err: unknown, lang: Lang): string {
  const msg = err instanceof ApiError || err instanceof Error ? err.message : String(err)
  const parts = msg.split(' / ')
  return parts.length === 2 ? parts[lang === 'it' ? 0 : 1] : msg
}

const uniq = <T,>(xs: T[]): T[] => [...new Set(xs)]

/** Price options narrowed step by step: type → origin → variety → market → colour. */
export function priceChoices(options: PriceOption[], p: RuleParams) {
  const types = uniq(options.map((o) => o.price_type))
  const ofType = options.filter((o) => o.price_type === p.price_type)
  const origins = uniq(ofType.map((o) => o.origin))
  const ofOrigin = ofType.filter((o) => o.origin === p.origin)
  const varieties = uniq(ofOrigin.map((o) => o.variety))
  const ofVariety = ofOrigin.filter((o) => o.variety === p.variety)
  const markets = uniq(ofVariety.map((o) => o.market).filter((m): m is string => Boolean(m)))
  const ofMarket = p.market ? ofVariety.filter((o) => o.market === p.market) : ofVariety
  const colors = uniq(ofMarket.map((o) => o.color_grade).filter((c): c is string => Boolean(c)))
  const lastPeriod = ofMarket.map((o) => o.last_period).filter(Boolean).sort().at(-1) ?? null
  return { types, origins, varieties, markets, colors, lastPeriod }
}

/** Keep a price selection valid when an upper choice changes (first available value below it). */
export function fixPrice(options: PriceOption[], p: RuleParams): RuleParams {
  const out = { ...p }
  let c = priceChoices(options, out)
  if (!c.types.includes(out.price_type as string)) out.price_type = c.types.includes('wholesale_bulk') ? 'wholesale_bulk' : c.types[0] ?? null
  c = priceChoices(options, out)
  if (!c.origins.includes(out.origin as string)) out.origin = c.origins.includes('ARG') ? 'ARG' : c.origins[0] ?? null
  c = priceChoices(options, out)
  if (!c.varieties.includes(out.variety as string)) out.variety = c.varieties.includes('polyflora') ? 'polyflora' : c.varieties[0] ?? null
  c = priceChoices(options, out)
  if (out.market && !c.markets.includes(out.market as string)) out.market = null
  c = priceChoices(options, out)
  if (out.color_grade && !c.colors.includes(out.color_grade as string)) out.color_grade = null
  return out
}

export function tradeChoices(options: TradeOption[], p: RuleParams) {
  const reporters = options.map((o) => o.iso3)
  const rep = options.find((o) => o.iso3 === p.reporter)
  const flows = (['import', 'export'] as const).filter((f) => rep?.flows[f])
  const f = rep?.flows[(p.flow as 'import' | 'export') ?? 'import']
  return { reporters, flows, partners: f?.partners ?? [], freqs: f?.freqs ?? [], lastPeriod: f?.last_period ?? null }
}

export function fixTrade(options: TradeOption[], p: RuleParams): RuleParams {
  const out = { ...p }
  let c = tradeChoices(options, out)
  if (!c.reporters.includes(out.reporter as string)) out.reporter = c.reporters.includes('EU27') ? 'EU27' : c.reporters[0] ?? null
  c = tradeChoices(options, out)
  if (!c.flows.includes(out.flow as 'import')) out.flow = c.flows[0] ?? 'import'
  c = tradeChoices(options, out)
  if (!c.partners.includes(out.partner as string)) out.partner = c.partners.includes('WLD') ? 'WLD' : c.partners[0] ?? 'WLD'
  if (!c.freqs.includes(out.freq as 'M')) out.freq = c.freqs.includes('M') ? 'M' : c.freqs[0] ?? 'M'
  return out
}

/** Starting conditions of a new rule of `type`, picked among what has data. */
export function defaultParams(type: AlertType, o: OptionsResponse | undefined): RuleParams {
  switch (type) {
    case 'price_change':
      return fixPrice(o?.price ?? [], { price_type: 'wholesale_bulk', origin: 'ARG', variety: 'polyflora', market: null,
        color_grade: null, threshold_pct: 5, direction: 'up' })
    case 'new_report': {
      const keys = (o?.report_sources ?? []).map((s) => s.key)
      return { source_keys: keys.includes('usda_honey_report') ? ['usda_honey_report'] : keys.slice(0, 1) }
    }
    case 'news_keyword':
      return { keywords: [], countries: [], min_relevance: 60 }
    case 'regulation':
      return { jurisdictions: ['EU'], doc_types: [], countries: [], include_tariffs: true }
    case 'trade_change':
      return fixTrade(o?.trade ?? [], { reporter: 'EU27', partner: 'WLD', flow: 'import', freq: 'M', threshold_pct: 20,
        direction: 'any' })
  }
}

/** Whether the conditions are complete enough to ask the backend for a preview / save. */
export function paramsReady(type: AlertType, p: RuleParams): boolean {
  switch (type) {
    case 'price_change':
      return Boolean(str(p.price_type) && str(p.origin) && str(p.variety)) && num(p.threshold_pct, 0) > 0
    case 'new_report':
      return strList(p.source_keys).length > 0
    case 'news_keyword':
      return strList(p.keywords).length > 0 || strList(p.countries).length > 0
    case 'regulation':
      return true
    case 'trade_change':
      return Boolean(str(p.reporter)) && num(p.threshold_pct, 0) > 0
  }
}

/** Keywords typed as text ("export, dazi") → list, and back. */
export function parseKeywords(text: string): string[] {
  return uniq(text.split(',').map((s) => s.trim()).filter(Boolean)).slice(0, 20)
}

export const RELEVANCE_STEPS = [0, 40, 60, 80] as const
