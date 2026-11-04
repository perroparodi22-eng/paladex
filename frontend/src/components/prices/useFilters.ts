// Filter state for /prezzi, kept in the URL so a view can be bookmarked or shared.
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { Ccy, Freq, MassUnit, PriceFilterState, PriceTypeKey, RangePreset } from './types'
import { PRICE_TYPE_ORDER, rangeFrom } from './utils'

const DEFAULTS: Omit<PriceFilterState, 'type'> = {
  origins: [], variety: '', market: '', source: '', color: '', ccy: 'USD', unit: 'kg', range: '3y', freq: 'M',
}

function oneOf<T extends string>(v: string | null, allowed: readonly T[], fallback: T): T {
  return v && (allowed as readonly string[]).includes(v) ? (v as T) : fallback
}

/** English parameter names used by links the backend builds (overview briefing and price tiles,
 * global search, data-quality issues: /prezzi?origin=ARG&variety=acacia&price_type=…). They are
 * read when the Italian name is absent and dropped as soon as that filter is changed here. */
const ALIASES: Record<string, string> = {
  tipo: 'price_type', origini: 'origin', varieta: 'variety', mercato: 'market', fonte: 'source', colore: 'color_grade',
}

function param(sp: URLSearchParams, key: string): string | null {
  const v = sp.get(key)
  if (v !== null) return v
  const alias = ALIASES[key]
  if (!alias) return null
  const all = sp.getAll(alias).filter(Boolean)
  return all.length ? all.join(',') : null
}

/** Filter state from the page address (Italian names first, then the English aliases). */
export function readPriceFilters(sp: URLSearchParams): PriceFilterState {
  const tipo = param(sp, 'tipo') ?? ''
  return {
    type: [...PRICE_TYPE_ORDER, 'other'].includes(tipo) ? (tipo as PriceTypeKey) : null,
    origins: (param(sp, 'origini') ?? '').split(',').map((x) => x.trim()).filter(Boolean),
    variety: param(sp, 'varieta') ?? '',
    market: param(sp, 'mercato') ?? '',
    source: param(sp, 'fonte') ?? '',
    color: param(sp, 'colore') ?? '',
    ccy: oneOf<Ccy>(sp.get('valuta'), ['USD', 'EUR'], DEFAULTS.ccy),
    unit: oneOf<MassUnit>(sp.get('unita'), ['kg', 'lb'], DEFAULTS.unit),
    range: oneOf<RangePreset>(sp.get('periodo'), ['1y', '3y', '5y', 'all'], DEFAULTS.range),
    freq: oneOf<Freq>(sp.get('freq'), ['M', 'Q', 'A'], DEFAULTS.freq),
  }
}

/** New page address after a filter change; `currentType` is the price type shown now. */
export function patchPriceParams(prev: URLSearchParams, patch: Partial<PriceFilterState>, currentType: PriceTypeKey | null): URLSearchParams {
  const next = new URLSearchParams(prev)
  const set = (k: string, v: string | null | undefined, def = '') => {
    if (v === undefined) return
    if (ALIASES[k]) next.delete(ALIASES[k])
    if (v === null || v === def) next.delete(k)
    else next.set(k, v)
  }
  // Changing the price type resets every filter that depends on it: the set of
  // origins, varieties, markets and sources differs per type, and the chart restarts.
  // (Not when the default type is first filled in: filters from a shared link survive.)
  if (patch.type !== undefined && currentType !== null && patch.type !== currentType) {
    for (const k of ['origini', 'varieta', 'mercato', 'fonte', 'colore']) {
      next.delete(k)
      next.delete(ALIASES[k])
    }
  }
  set('tipo', patch.type)
  if (patch.origins !== undefined) set('origini', patch.origins.join(','))
  set('varieta', patch.variety)
  set('mercato', patch.market)
  set('fonte', patch.source)
  set('colore', patch.color)
  set('valuta', patch.ccy, DEFAULTS.ccy)
  set('unita', patch.unit, DEFAULTS.unit)
  set('periodo', patch.range, DEFAULTS.range)
  set('freq', patch.freq, DEFAULTS.freq)
  return next
}

export function usePriceFilters() {
  const [sp, setSp] = useSearchParams()

  const state: PriceFilterState = useMemo(() => readPriceFilters(sp), [sp])

  const update = useCallback((patch: Partial<PriceFilterState>) => {
    setSp((prev) => patchPriceParams(prev, patch, state.type), { replace: true })
  }, [setSp, state.type])

  const reset = useCallback(() => update({ origins: [], variety: '', market: '', source: '', color: '' }), [update])

  /** Query parameters for the API (dimension filters only). */
  const apiFilters = useMemo(() => ({
    price_type: state.type ?? undefined,
    origin: state.origins.length ? state.origins : undefined,
    variety: state.variety || undefined,
    market: state.market || undefined,
    source: state.source || undefined,
    color_grade: state.color || undefined,
  }), [state])

  const from = rangeFrom(state.range)
  const hasDimFilters = Boolean(state.origins.length || state.variety || state.market || state.source || state.color)

  return { state, update, reset, apiFilters, from, hasDimFilters }
}
