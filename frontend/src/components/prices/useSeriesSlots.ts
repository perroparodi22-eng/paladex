// Which series are drawn on the chart, and with which colour.
//
// Colour follows the series, never its rank: a series keeps its colour slot while it stays
// visible, so filtering or hiding another line never repaints it. At most MAX_VISIBLE lines
// are drawn (one per palette slot; hues are never cycled).
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
        setLimitHit(false)
        return rest
      }
      if (Object.keys(prev).length >= MAX_VISIBLE) {
        setLimitHit(true)
        return prev
      }
      userHidden.current.delete(id)
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
