// World map, review of 5 Nov 2026 ("the export colours make no sense"):
// - quantile classes put China (175,521 t), India (120,074 t) and Hungary (15,802 t) in the same
//   darkest colour while the light classes split fractions of a tonne: classes are now FIXED tonnages;
// - every country was coloured with its latest year whatever it was (exports mixed 2025, 2024, 2023
//   and 2013-2022): a figure more than 2 years older than the newest one is hatched, never coloured
//   as current, and its tooltip states the year;
// - the legend now says which years and which sources the colours stand for.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  BREAKS, classIndex, colorFor, fixedClasses, isOld, NO_DATA, OLD_FILL, RAMP,
} from '@/components/countries/choropleth'
import { fillFor, MapBasis, MapLegend, summarize } from '@/components/countries/MapLegend'
import type { CountryListItem, MapMetric } from '@/components/countries/types'
import { render, text } from './helpers'

const src = (key: string, name: string) => ({ key, name, name_en: name, publisher: `${name} publisher`, reliability: 'official', homepage: null })
const COMTRADE = src('un_comtrade', 'UN Comtrade — commercio internazionale di miele (HS 0409)')
const FAO = src('faostat', 'FAOSTAT — produzione, alveari, prezzi alla produzione e commercio di miele')
const INDEC = src('ar_official_exports', 'Argentina – INDEC: esportazioni di miele per destinazione (NCM 04090000)')

function country(iso3: string, exportsT: number | null, year: number, source = COMTRADE, status = 'published'): CountryListItem {
  return {
    iso3, iso2: null, m49: null, name_it: iso3, name_en: iso3, region: 'Asia', lat: null, lon: null, priority: false,
    available: { production: false, exports: exportsT !== null, imports: false, exports_mirror: false, imports_mirror: false, prices: false, news: false, regulations: false, context: false },
    metrics: {
      exports: exportsT === null ? null : {
        net_weight_kg: exportsT * 1000, usd_value: null, unit_value_usd_per_kg: null, year, summed_from_partners: false,
        summed_from_months: false, partners_count: null, months_count: null, yoy_volume_pct: null, source, data_status: status,
        is_demo: false, period_label: String(year), frequency: 'A',
      },
      imports: null, production: null, news_30d: null, prices_count: 0, regulations_count: 0,
    },
  } as CountryListItem
}

/** OKLab lightness of a #RRGGBB colour. */
function lightness(hex: string): number {
  const lin = (c: number) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
  const [r, g, b] = [1, 3, 5].map((i) => lin(parseInt(hex.slice(i, i + 2), 16)))
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
}

test('fixed, round class breaks: the big players stand apart from mid-sized ones', () => {
  assert.deepEqual(BREAKS.exports, [100, 1000, 5000, 20000, 50000])
  assert.deepEqual(BREAKS.imports, [100, 1000, 5000, 20000, 50000])
  assert.deepEqual(BREAKS.production, [1000, 5000, 20000, 50000, 100000])
  const c = fixedClasses('exports')
  assert.equal(c.colors.length, 6)
  // China / India in the top class, Hungary two classes below (quantiles had all three together)
  assert.equal(classIndex(175_521, c), 5)
  assert.equal(classIndex(120_074, c), 5)
  assert.equal(classIndex(15_802, c), 3)
  assert.notEqual(colorFor(175_521, c), colorFor(15_802, c))
  // bounds: a break belongs to the class above it
  assert.equal(classIndex(99.9, c), 0)
  assert.equal(classIndex(100, c), 1)
  assert.equal(classIndex(0.02, c), 0)
  assert.equal(colorFor(null, c), NO_DATA)
})

test('the colour ramp gets darker class by class (accessible order)', () => {
  const ls = RAMP.map(lightness)
  for (let i = 1; i < ls.length; i++) assert.ok(ls[i] < ls[i - 1] - 0.08, `class ${i} is clearly darker than class ${i - 1}`)
  assert.ok(ls[ls.length - 1] < 0.4 && ls[0] > 0.88)
})

test('a figure more than 2 years older than the newest one is drawn hatched, never in a class colour', () => {
  assert.equal(isOld(2023, 2025), false)
  assert.equal(isOld(2022, 2025), true)
  assert.equal(isOld(null, 2025), false)
  const items = [country('CHN', 175_521, 2025), country('VNM', 45_359, 2024), country('GMB', 0.01, 2013), country('XXX', null, 2025)]
  const s = summarize(items, 'exports', 'it')
  assert.equal(s.newest, 2025)
  assert.equal(fillFor(items[0], 'exports', s.newest), RAMP[5])
  assert.equal(fillFor(items[1], 'exports', s.newest), RAMP[4])
  assert.equal(fillFor(items[2], 'exports', s.newest), OLD_FILL)
  assert.equal(fillFor(items[3], 'exports', s.newest), NO_DATA)
  // old figures are not counted in any class
  assert.deepEqual(s.classCounts, [0, 0, 0, 0, 1, 1])
  assert.deepEqual(s.old, { n: 1, from: 2013, to: 2013 })
})

test('summary: years and sources behind the colours', () => {
  const items = [
    country('CHN', 175_521, 2025), country('IND', 120_074, 2025), country('ARG', 90_614, 2025, INDEC),
    country('VNM', 45_359, 2024, FAO), country('BOL', 3, 2019), country('PAN', 1, 2020),
  ]
  const s = summarize(items, 'exports', 'it')
  assert.equal(s.count, 6)
  assert.deepEqual(s.years, [{ year: 2025, n: 3 }, { year: 2024, n: 1 }])
  assert.deepEqual(s.old, { n: 2, from: 2019, to: 2020 })
  assert.deepEqual(s.sources, [{ name: 'UN Comtrade', n: 4 }, { name: 'Argentina – INDEC', n: 1 }, { name: 'FAOSTAT', n: 1 }])
})

test('legend: contiguous ranges with counts, the old-data entry and "no data", in both languages', () => {
  const items = [country('CHN', 175_521, 2025), country('HUN', 15_802, 2025), country('TON', 0.2, 2013)]
  const sum = summarize(items, 'exports', 'it')
  const it = text(render(<MapLegend metric={'exports' as MapMetric} summary={sum} />, { lang: 'it' }))
  assert.match(it, /≥ 50\.000 t \(1\)/)
  assert.match(it, /20\.000 – 50\.000 t \(0\)/)
  assert.match(it, /5\.000 – 20\.000 t \(1\)/)
  assert.match(it, /< 100 t \(0\)/)
  assert.match(it, /Dato vecchio \(prima del 2023\) \(1\)/)
  assert.match(it, /Nessun dato/)
  const en = text(render(<MapLegend metric={'exports' as MapMetric} summary={summarize(items, 'exports', 'en')} />, { lang: 'en' }))
  assert.match(en, /≥ 50,000 t \(1\)/)
  assert.match(en, /Old figure \(before 2023\) \(1\)/)
  assert.match(en, /No data/)
  // read left to right from the lowest class
  assert.ok(it.indexOf('< 100 t') < it.indexOf('≥ 50.000 t'))
})

test('under the map: the year basis and the mix of sources', () => {
  const items = [
    country('CHN', 175_521, 2025), country('IND', 120_074, 2025), country('VNM', 45_359, 2024, FAO), country('TON', 0.2, 2013),
  ]
  const it = text(render(<MapBasis summary={summarize(items, 'exports', 'it')} />, { lang: 'it' }))
  assert.match(it, /Anno del dato: 2025 \(2 paesi\) · 2024 \(1 paese\) · tratteggiato 1 paese con dati 2013/)
  assert.match(it, /Fonti: UN Comtrade \(3\) · FAOSTAT \(1\)/)
  const en = text(render(<MapBasis summary={summarize(items, 'exports', 'en')} />, { lang: 'en' }))
  assert.match(en, /Year of the figure: 2025 \(2 countries\) · 2024 \(1 country\) · hatched: 1 country with 2013 data/)
  assert.match(en, /Sources: UN Comtrade \(3\) · FAOSTAT \(1\)/)
})
