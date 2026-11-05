// Sequential choropleth classes for the world map: quantile breaks (same number of countries per
// class) and a calm gold -> forest ramp whose lightness falls monotonically (0.92 -> 0.40 OKLab L).

export const RAMP = ['#F2E5BD', '#DDC47E', '#A3AD6C', '#4F8466', '#1F503C']
export const NO_DATA = '#D8D5CD'
export const BORDER = '#FFFFFF'

export interface Classes {
  /** lower bound of each class (first = min value) */
  lows: number[]
  /** upper bound of each class (last = max value) */
  highs: number[]
  colors: string[]
}

/** Pick `n` colours spread over the ramp (keeps the light-to-dark reading with few classes). */
function spread(n: number): string[] {
  if (n <= 1) return [RAMP[RAMP.length - 2]]
  return Array.from({ length: n }, (_, i) => RAMP[Math.round((i * (RAMP.length - 1)) / (n - 1))])
}

export function quantileClasses(values: number[], k = RAMP.length): Classes | null {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b)
  if (!v.length) return null
  const distinct = Array.from(new Set(v))
  const n = Math.min(k, distinct.length)
  const lows: number[] = []
  for (let i = 0; i < n; i++) {
    const q = v[Math.floor((i * v.length) / n)]
    if (!lows.length || q > lows[lows.length - 1]) lows.push(q)
  }
  const highs = lows.map((_, i) => (i < lows.length - 1 ? lows[i + 1] : v[v.length - 1]))
  return { lows, highs, colors: spread(lows.length) }
}

export function classIndex(value: number, c: Classes): number {
  let idx = 0
  for (let i = 0; i < c.lows.length; i++) if (value >= c.lows[i]) idx = i
  return idx
}

export function colorFor(value: number | null | undefined, c: Classes | null): string {
  if (value === null || value === undefined || !c) return NO_DATA
  return c.colors[classIndex(value, c)]
}
