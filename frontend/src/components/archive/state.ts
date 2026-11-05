// /archivio state lives in the address (a view can be bookmarked or shared) and the price, trade
// and production selections are shared by their tab and by the "Revisioni" tab.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '@/lib/api'
import type { Ccy, PriceCombo, PriceHistoryResponse, PriceOptionsResponse, PriceSelection, TradeOptionsResponse } from './types'

export type Patch = Record<string, string | null | undefined>

export function useArchiveParams() {
  const [sp, setSp] = useSearchParams()
  const set = useCallback((patch: Patch) => {
    setSp((prev) => {
      const next = new URLSearchParams(prev)
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === undefined || v === '') next.delete(k)
        else next.set(k, v)
      }
      return next
    }, { replace: true })
  }, [setSp])
  return { sp, set }
}

const uniq = <T,>(xs: T[]): T[] => [...new Set(xs)]

/** The price series to show: what the address asks for when it has data, else the backend's
 * default (EU import unit value of Argentina), else the first combination with data. */
export function resolvePriceSelection(o: PriceOptionsResponse | undefined, sp: URLSearchParams): PriceSelection | null {
  if (!o || !o.price_type || !o.combos.length) return null
  const def = o.default && o.default.price_type === o.price_type ? o.default : null
  const combos = o.combos
  const pick = <T,>(wanted: T | null, have: T[], fallback: T | null | undefined): T | null =>
    wanted !== null && have.includes(wanted) ? wanted : fallback !== undefined && fallback !== null && have.includes(fallback) ? fallback : have[0] ?? null
  const origin = pick(sp.get('origine'), uniq(combos.map((c) => c.origin)), def?.origin)
  const ofOrigin = combos.filter((c) => c.origin === origin)
  const variety = pick(sp.get('varieta'), uniq(ofOrigin.map((c) => c.variety)), def?.variety)
  const ofVariety = ofOrigin.filter((c) => c.variety === variety)
  const markets = uniq(ofVariety.map((c) => c.market).filter((m): m is string => Boolean(m)))
  const mParam = sp.get('mercato')
  // 'tutti' = every market (explicit choice); no parameter = the default market when there is one
  const market = mParam === 'tutti' ? null : mParam && markets.includes(mParam) ? mParam
    : def?.market && markets.includes(def.market) && origin === def.origin && variety === def.variety ? def.market : null
  const ofMarket = market ? ofVariety.filter((c) => c.market === market) : ofVariety
  const colors = uniq(ofMarket.map((c) => c.color_grade).filter((c): c is string => Boolean(c)))
  const cParam = sp.get('colore')
  const color_grade = cParam && colors.includes(cParam) ? cParam : null
  if (!origin || !variety) return null
  return { price_type: o.price_type, origin, variety, market, color_grade }
}

export function priceChoices(combos: PriceCombo[], sel: PriceSelection | null) {
  const origins = uniq(combos.map((c) => c.origin))
  const ofOrigin = combos.filter((c) => c.origin === sel?.origin)
  const varieties = uniq(ofOrigin.map((c) => c.variety))
  const ofVariety = ofOrigin.filter((c) => c.variety === sel?.variety)
  const markets = uniq(ofVariety.map((c) => c.market).filter((m): m is string => Boolean(m)))
  const ofMarket = sel?.market ? ofVariety.filter((c) => c.market === sel.market) : ofVariety
  const colors = uniq(ofMarket.map((c) => c.color_grade).filter((c): c is string => Boolean(c)))
  return { origins, varieties, markets, colors }
}

export function readCcy(sp: URLSearchParams): Ccy {
  const v = sp.get('valuta')
  return v === 'USD' || v === 'EUR' ? v : 'ORIGINAL'
}

export function readUnit(sp: URLSearchParams): 'kg' | 'lb' {
  return sp.get('unita') === 'lb' ? 'lb' : 'kg'
}

export function priceParams(sel: PriceSelection, ccy: Ccy, series: string | null) {
  return {
    price_type: sel.price_type, origin: sel.origin, variety: sel.variety ?? undefined, market: sel.market ?? undefined,
    color: sel.color_grade ?? undefined, currency: ccy, series: series ?? undefined,
  }
}

/** Options + selection + history of the chosen price series (shared by Prezzi and Revisioni). */
export function usePriceArchive() {
  const { sp, set } = useArchiveParams()
  const tipo = sp.get('tipo')
  const options = useQuery({
    queryKey: ['archive', 'price-options', tipo],
    queryFn: () => api.get<PriceOptionsResponse>('/archive/prices/options', { price_type: tipo ?? undefined }),
    placeholderData: keepPreviousData,
  })
  const sel = useMemo(() => resolvePriceSelection(options.data, sp), [options.data, sp])
  const ccy = readCcy(sp)
  const series = sp.get('serie')
  const history = useQuery({
    queryKey: ['archive', 'prices', sel, ccy, series],
    queryFn: () => api.get<PriceHistoryResponse>('/archive/prices', priceParams(sel!, ccy, series)),
    enabled: sel !== null,
    placeholderData: keepPreviousData,
  })
  return { sp, set, options, sel, ccy, unit: readUnit(sp), series, history }
}

export interface TradeSelection { reporter: string; partner: string; flow: 'import' | 'export' }

export function useTradeSelection() {
  const { sp, set } = useArchiveParams()
  const options = useQuery({ queryKey: ['archive', 'trade-options'], queryFn: () => api.get<TradeOptionsResponse>('/archive/trade/options'), staleTime: 5 * 60_000 })
  const sel = useMemo<TradeSelection | null>(() => {
    const reps = options.data?.reporters ?? []
    if (!reps.length) return null
    const r = reps.find((x) => x.iso3 === sp.get('dichiarante')) ?? reps.find((x) => x.iso3 === 'EU27') ?? reps[0]
    const flowWanted = sp.get('flusso') === 'export' ? 'export' : 'import'
    const flow = r.flows[flowWanted] ? flowWanted : (r.flows.import ? 'import' : 'export')
    const partners = r.flows[flow]?.partners ?? []
    const pWanted = sp.get('partner')
    const partner = pWanted && partners.includes(pWanted) ? pWanted
      : !pWanted && r.iso3 === 'EU27' && flow === 'import' && partners.includes('ARG') ? 'ARG'
        : partners.includes('WLD') ? 'WLD' : partners[0] ?? 'WLD'
    return { reporter: r.iso3, partner, flow }
  }, [options.data, sp])
  return { sp, set, options, sel }
}

export function readProduction(sp: URLSearchParams): { country: string; metric: string } {
  const c = (sp.get('paese') ?? 'ARG').toUpperCase()
  const m = sp.get('dato') ?? 'production'
  return { country: /^[A-Z]{3}$/.test(c) ? c : 'ARG', metric: /^[a-z_]{2,40}$/.test(m) ? m : 'production' }
}
