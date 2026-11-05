// /offerte state kept in the page address, so a view (a filter, an open offer, a comparison) can be
// bookmarked and reopened: ?stato=&origine=&varieta=&fornitore=&cerca=&cambio=oggi&offerta=12
// &confronta=3,5,9&base=migliore&nuova=1&modifica=12
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { CompareBasis, FxMode, QuoteStatus } from './types'
import { MAX_COMPARE, STATUSES } from './utils'

export type StatusFilter = '' | QuoteStatus | 'all'

export interface QuoteView {
  status: StatusFilter
  origin: string
  variety: string
  supplier: string
  text: string
  fx: FxMode
  open: number | null
  compare: number[]
  basis: CompareBasis
  form: { mode: 'new' } | { mode: 'edit'; id: number } | null
}

const id = (v: string | null): number | null => (v && /^\d+$/.test(v) ? Number(v) : null)

export function readQuoteView(sp: URLSearchParams): QuoteView {
  const st = sp.get('stato') ?? ''
  const edit = id(sp.get('modifica'))
  return {
    status: st === 'all' || (STATUSES as string[]).includes(st) ? (st as StatusFilter) : '',
    origin: sp.get('origine') ?? '',
    variety: sp.get('varieta') ?? '',
    supplier: sp.get('fornitore') ?? '',
    text: sp.get('cerca') ?? '',
    fx: sp.get('cambio') === 'oggi' ? 'today' : 'received',
    open: id(sp.get('offerta')),
    compare: [...new Set((sp.get('confronta') ?? '').split(',').map((x) => id(x.trim())).filter((x): x is number => x !== null))].slice(0, MAX_COMPARE),
    basis: sp.get('base') === 'migliore' ? 'best' : 'conservative',
    form: edit !== null ? { mode: 'edit', id: edit } : sp.get('nuova') === '1' ? { mode: 'new' } : null,
  }
}

export function patchQuoteParams(prev: URLSearchParams, patch: Partial<QuoteView>): URLSearchParams {
  const next = new URLSearchParams(prev)
  const set = (k: string, v: string | null | undefined) => {
    if (v === undefined) return
    if (v === null || v === '') next.delete(k)
    else next.set(k, v)
  }
  set('stato', patch.status)
  set('origine', patch.origin)
  set('varieta', patch.variety)
  set('fornitore', patch.supplier)
  set('cerca', patch.text)
  if (patch.fx !== undefined) set('cambio', patch.fx === 'today' ? 'oggi' : null)
  if (patch.open !== undefined) set('offerta', patch.open === null ? null : String(patch.open))
  if (patch.compare !== undefined) set('confronta', patch.compare.length ? patch.compare.join(',') : null)
  if (patch.basis !== undefined) set('base', patch.basis === 'best' ? 'migliore' : null)
  if (patch.form !== undefined) {
    next.delete('nuova')
    next.delete('modifica')
    if (patch.form?.mode === 'new') next.set('nuova', '1')
    if (patch.form?.mode === 'edit') next.set('modifica', String(patch.form.id))
  }
  return next
}

export function useQuoteParams() {
  const [sp, setSp] = useSearchParams()
  const view = useMemo(() => readQuoteView(sp), [sp])
  const update = useCallback(
    (patch: Partial<QuoteView>, opts: { replace?: boolean } = {}) => setSp((prev) => patchQuoteParams(prev, patch), { replace: opts.replace }),
    [setSp],
  )
  const apiFilters = useMemo(() => ({
    status: view.status || undefined,
    origin: view.origin || undefined,
    variety: view.variety || undefined,
    supplier: view.supplier || undefined,
    q: view.text || undefined,
    fx: view.fx,
  }), [view.status, view.origin, view.variety, view.supplier, view.text, view.fx])
  const hasFilters = Boolean(view.status || view.origin || view.variety || view.supplier || view.text)
  return { view, update, apiFilters, hasFilters }
}
