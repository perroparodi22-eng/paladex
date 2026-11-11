// Which series are drawn on the chart, and with which colour.
//
// Colour follows the series, never its rank: a series keeps its colour slot while it stays
// visible, so filtering or hiding another line never repaints it. At most MAX_VISIBLE lines
// are drawn (one per palette slot; hues are never cycled). Asking for one more shows it in
// place of the line shown longest (it used to refuse the click: "I click them and they do not
// appear", 11 Nov 2026).
import { useCallback, useEffect, useRef, useState } from 'react'
import { DEFAULT_VISIBLE, MAX_VISIBLE, SERIES_COLORS } from './utils'

function lowestFree(used: Set<number>): number {
  let s = 0
  while (used.has(s)) s++
  return s
}

function fill(ids: string[], base: Record<string, number>, skip: Set<string>, target: number): Record<string, number> {
  const next: Record<string, number> = {}
  for (const id of ids) if (base[id] !== undefined) next[id] = base[id]
  const used = new Set(Object.values(next))
  for (const id of ids) {
    if (Object.keys(next).length >= target) break
    if (next[id] !== undefined || skip.has(id)) continue
    const s = lowestFree(used)
    next[id] = s
    used.add(s)
  }
  return next
}

/** `ids`: series in display order. `resetKey`: changing it (e.g. a new price type) restarts the selection. */
export function useSeriesSlots(ids: string[], resetKey: string) {
  const [slots, setSlots] = useState<Record<string, number>>({})
  const [limitHit, setLimitHit] = useState(false)
  const userHidden = useRef<Set<string>>(new Set())
  const shownOrder = useRef<string[]>([])      // series the person switched on, oldest first
  const lastKey = useRef(resetKey)
  const idsKey = ids.join(',')

  useEffect(() => {
    setSlots((prev) => {
      let base = prev
      if (lastKey.current !== resetKey) {
        lastKey.current = resetKey
        userHidden.current = new Set()
        base = {}
      }
      let next = fill(ids, base, userHidden.current, DEFAULT_VISIBLE)
      // never leave the chart empty just because the filters now match only hidden series
      if (Object.keys(next).length === 0 && ids.length) next = fill(ids, {}, new Set(), DEFAULT_VISIBLE)
      return next
    })
    setLimitHit(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, resetKey])

  const toggle = useCallback((id: string) => {
    setSlots((prev) => {
      if (prev[id] !== undefined) {
        const { [id]: _drop, ...rest } = prev
        userHidden.current.add(id)
        shownOrder.current = shownOrder.current.filter((x) => x !== id)
        setLimitHit(false)
        return rest
      }
      userHidden.current.delete(id)
      shownOrder.current = [...shownOrder.current.filter((x) => x !== id), id]
      if (Object.keys(prev).length >= MAX_VISIBLE) {
        // the palette is full: the new line takes the place (and the colour) of the one shown
        // longest, first among those Paladex chose by itself
        const out = Object.keys(prev).find((x) => !shownOrder.current.includes(x)) ?? shownOrder.current.find((x) => prev[x] !== undefined && x !== id)
        if (out === undefined) return prev
        const { [out]: slot, ...rest } = prev
        shownOrder.current = shownOrder.current.filter((x) => x !== out)
        setLimitHit(true)
        return { ...rest, [id]: slot }
      }
      return { ...prev, [id]: lowestFree(new Set(Object.values(prev))) }
    })
  }, [])

  const hideAll = useCallback(() => {
    setSlots((prev) => {
      Object.keys(prev).forEach((id) => userHidden.current.add(id))
      return {}
    })
    setLimitHit(false)
  }, [])

  const restore = useCallback(() => {
    userHidden.current = new Set()
    setSlots(fill(ids, {}, new Set(), DEFAULT_VISIBLE))
    setLimitHit(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey])

  const colorOf = useCallback((id: string) => (slots[id] !== undefined ? SERIES_COLORS[slots[id]] : undefined), [slots])

  return { slots, colorOf, toggle, hideAll, restore, limitHit, visibleCount: Object.keys(slots).length }
}
