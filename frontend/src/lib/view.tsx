// "Vista: Semplice | Completa" — how much the interface shows at once (owner's choice, 6 Nov 2026).
//
// SIMPLE (the default) shows the same data with the same provenance, answer first and in plain
// words, with fewer numbers per screen; FULL is the interface as it was (every table, filter and
// technical label). The choice is remembered per browser (localStorage, also in the read-only
// online copy) and read by the pages through useView().
//
// Outside <ViewProvider> (components rendered on their own, e.g. in tests) the view is FULL, so
// every page renders exactly as before unless the application opts in.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

export type View = 'simple' | 'full'

export const VIEW_STORAGE_KEY = 'paladex.view'
export const DEFAULT_VIEW: View = 'simple'

/** The view saved in this browser; the default when nothing (or something unreadable) is saved. */
export function readStoredView(): View {
  try {
    const v = globalThis.localStorage?.getItem(VIEW_STORAGE_KEY)
    return v === 'full' || v === 'simple' ? v : DEFAULT_VIEW
  } catch {
    return DEFAULT_VIEW
  }
}

/** Remember the view in this browser (silently skipped where storage is blocked). */
export function storeView(v: View): void {
  try {
    globalThis.localStorage?.setItem(VIEW_STORAGE_KEY, v)
  } catch {
    /* private window or blocked storage: the choice lasts for this visit only */
  }
}

interface ViewCtx {
  view: View
  simple: boolean
  setView: (v: View) => void
}

const OUTSIDE: ViewCtx = { view: 'full', simple: false, setView: () => {} }
const Ctx = createContext<ViewCtx>(OUTSIDE)

export function ViewProvider({ children, initial }: { children: ReactNode; initial?: View }) {
  const [view, setState] = useState<View>(() => initial ?? readStoredView())
  const setView = useCallback((v: View) => {
    setState(v)
    storeView(v)
  }, [])
  const value = useMemo(() => ({ view, simple: view === 'simple', setView }), [view, setView])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useView(): ViewCtx {
  return useContext(Ctx)
}
