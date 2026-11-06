// World-map colours: FIXED, round class breaks chosen for the honey market, and a calm gold -> forest
// ramp whose lightness falls monotonically (OKLab L 0.91 -> 0.33, steps of 0.09-0.16).
//
// Why fixed breaks and not quantiles: honey trade is extremely concentrated. Quantile classes (same
// number of countries per colour) put China (175,521 t of exports), India (120,074 t) and Hungary
// (15,802 t) in the same darkest colour while the light classes split fractions of a tonne between
// island states. Fixed, roughly logarithmic breaks keep a colour meaning the same tonnage on every
// visit and make the few large players stand out.
//
// Checked against the real data of 5 Nov 2026 (countries with a figure no more than 2 years older
// than the newest year shown; older ones are hatched, see below):
//   exports    (169 countries, 2023-2025)  < 100 t: 102 · 100-1,000: 21 · 1,000-5,000: 21 ·
//              5,000-20,000: 15 · 20,000-50,000: 6 (Belgium, Brazil, Germany, Mexico, Spain, Vietnam) ·
//              >= 50,000: 4 (China, India, Argentina, Ukraine)
//   imports    (194 countries)  < 100 t: 102 · 100-1,000: 41 · 1,000-5,000: 28 · 5,000-20,000: 13 ·
//              20,000-50,000: 6 (Spain, France, Poland, Italy, Belgium, Saudi Arabia) ·
//              >= 50,000: 4 (USA, Germany, United Kingdom, Japan)
//   production (129 countries, FAOSTAT 2022-2024)  < 1,000 t: 42 · 1,000-5,000: 38 · 5,000-20,000: 25 ·
//              20,000-50,000: 13 · 50,000-100,000: 9 (Turkey, Ethiopia, Iran, Argentina, Brazil,
//              Russia, USA, Mexico, Ukraine) · >= 100,000: 2 (China, India)
// Every class is populated; the top two classes hold the market's main exporters / importers /
// producers. The lowest class is wide on purpose: below 100 t a country is not a bulk market.
// News counts (articles in 30 days) are small integers: fixed small steps.
import type { MapMetric } from './types'

export const RAMP = ['#F2E3AE', '#DEC277', '#B0AD66', '#729565', '#357050', '#173F2F']
export const NO_DATA = '#D8D5CD'
export const BORDER = '#FFFFFF'

/** Lower bounds of classes 2..6 (class 1 is everything below the first break). */
export const BREAKS: Record<MapMetric, number[]> = {
  exports: [100, 1_000, 5_000, 20_000, 50_000],
  imports: [100, 1_000, 5_000, 20_000, 50_000],
  production: [1_000, 5_000, 20_000, 50_000, 100_000],
  news: [2, 4, 7, 11, 21],
}

/** A figure whose year is more than this many years before the newest year shown for the metric is
 * "old": drawn hatched, never coloured as if it were current (exports mix 2025, 2024, 2023 and, for a
 * few small countries, 2013-2022). */
export const OLD_AFTER_YEARS = 2

/** SVG pattern used as fill for old figures (defined once by <OldDataPattern/> in the page). */
export const OLD_PATTERN_ID = 'pdx-old-hatch'
export const OLD_FILL = `url(#${OLD_PATTERN_ID})`
export const OLD_BASE = '#F4F2EC'
export const OLD_STRIPE = '#A39E8F'
/** The same hatch for HTML swatches (legend). */
export const OLD_SWATCH_CSS = `repeating-linear-gradient(135deg, ${OLD_BASE} 0 3px, ${OLD_STRIPE} 3px 4.5px)`

export interface Classes {
  /** lower bound of each class (null = open below) */
  lows: (number | null)[]
  /** upper bound of each class, exclusive (null = open above) */
  highs: (number | null)[]
  colors: string[]
}

export function fixedClasses(metric: MapMetric): Classes {
  const b = BREAKS[metric]
  return {
    lows: [null, ...b],
    highs: [...b, null],
    colors: RAMP.slice(0, b.length + 1),
  }
}

/** Index of the class holding `value`: the number of breaks it reaches. */
export function classIndex(value: number, c: Classes): number {
  let idx = 0
  for (let i = 1; i < c.lows.length; i++) if (value >= (c.lows[i] as number)) idx = i
  return idx
}

export function colorFor(value: number | null | undefined, c: Classes | null): string {
  if (value === null || value === undefined || !c) return NO_DATA
  return c.colors[classIndex(value, c)]
}

/** True when `year` is more than OLD_AFTER_YEARS before `newest` (the newest year on the map). */
export function isOld(year: number | null | undefined, newest: number | null | undefined): boolean {
  return year != null && newest != null && newest - year > OLD_AFTER_YEARS
}
