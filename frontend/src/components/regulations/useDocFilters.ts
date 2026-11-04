// Filter state for the "Documenti ufficiali" list, kept in the URL so a view can be linked to
// (global search links to /normative?q=…).
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { DocFilterState } from './types'

export function useDocFilters() {
  const [sp, setSp] = useSearchParams()

  const state: DocFilterState = useMemo(() => ({
    q: sp.get('q') ?? '',
    jurisdiction: (sp.get('jurisdiction') ?? '').toUpperCase(),
    docType: sp.get('type') ?? '',
    country: (sp.get('country') ?? '').toUpperCase(),
  }), [sp])

  const update = useCallback((patch: Partial<DocFilterState>) => {
    setSp((prev) => {
      const next = new URLSearchParams(prev)
      const set = (k: string, v: string | undefined) => {
        if (v === undefined) return
        if (v.trim() === '') next.delete(k)
        else next.set(k, v.trim())
      }
      set('q', patch.q)
      set('jurisdiction', patch.jurisdiction)
      set('type', patch.docType)
      set('country', patch.country)
      return next
    }, { replace: true })
  }, [setSp])

  const reset = useCallback(() => update({ q: '', jurisdiction: '', docType: '', country: '' }), [update])
  const hasFilters = Boolean(state.q || state.jurisdiction || state.docType || state.country)

  /** Query parameters for GET /api/regulations (without page). */
  const apiParams = useMemo(() => ({
    q: state.q || undefined,
    jurisdiction: state.jurisdiction || undefined,
    doc_type: state.docType || undefined,
    country: state.country || undefined,
  }), [state])

  return { state, update, reset, hasFilters, apiParams }
}
