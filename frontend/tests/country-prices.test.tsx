// 11 Nov 2026 (owner): "when I choose the country I also get the prices there, and I can change
// them"; "on Prezzi, Italy: they appear but when I click them they do not". The country page lists
// its prices in the simple view, each fixed by tapping it; the price chart shows a ninth series in
// place of the one shown longest instead of refusing the click.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { CountryPricesSimple, pickCountryPrices, priceFigure } from '@/components/countries/CountryPrices'
import type { CountryProfile, PriceRow } from '@/components/countries/types'
import { setMirrorMode } from '@/lib/mirror'
import meta from './fixtures/meta-simple.json'
import { newQueryClient, render, text } from './helpers'

const EUROSTAT = { key: 'eurostat_honey_prices', name: 'Eurostat: prezzo di vendita del miele', publisher: 'Eurostat (European Commission)', reliability: 'official', homepage: null }
const FAO = { key: 'faostat', name: 'FAOSTAT', publisher: 'Food and Agriculture Organization of the United Nations (FAO)', reliability: 'official', homepage: null }
const COMEXT = { key: 'eurostat_comext', name: 'Eurostat Comext', publisher: 'Eurostat (European Commission)', reliability: 'official', homepage: null }

function price(over: Partial<PriceRow>): PriceRow {
  return {
    price_type: 'producer', variety: 'unspecified', variety_raw: null, market_iso3: 'DEU', market_location: null, color_grade: null,
    organic: false, terms: null, price_value: 1513.41, price_low: null, price_high: null, currency: 'EUR', unit: '100kg',
    price_per_kg: 15.1341, usd_per_kg: 16.4, eur_per_kg: 15.1341, observations: 11, row_id: 67235,
    source: EUROSTAT, source_url: null, published_at: '2025-05-15', collected_at: '2026-11-11T08:00:00', period_label: '2024',
    period_start: '2024-01-01', period_end: '2024-12-31', frequency: 'A', data_status: 'published', reliability: 'official', is_demo: false,
    correction: null, ...over,
  } as PriceRow
}

function profile(groups: CountryProfile['prices']['groups']): CountryProfile {
  return {
    country: { iso3: 'DEU', name_it: 'Germania', name_en: 'Germany' }, today: '2026-11-11',
    prices: { available: groups.length > 0, groups, providers: [] },
  } as unknown as CountryProfile
}

function show(p: CountryProfile, lang: 'it' | 'en' = 'it') {
  const qc = newQueryClient()
  qc.setQueryData(['meta'], meta)
  return render(<CountryPricesSimple p={p} />, { qc, lang })
}

const PRODUCER = [price({}), price({ source: FAO, row_id: 20594, price_value: 16372.4, currency: 'USD', unit: 't', eur_per_kg: 15.1302 })]
const EXPORTS = [
  price({ price_type: 'export_unit_value', market_iso3: 'SYR', row_id: 1, source: COMEXT, price_value: 12.65, unit: 'kg', eur_per_kg: 12.65, period_label: '2026-08', period_end: '2026-08-31', frequency: 'M', data_status: 'provisional' }),
  price({ price_type: 'export_unit_value', market_iso3: 'USA', row_id: 2, source: COMEXT, price_value: 5.91, unit: 'kg', eur_per_kg: 5.91, period_label: '2026-08', period_end: '2026-08-31', frequency: 'M' }),
  price({ price_type: 'export_unit_value', market_iso3: 'USA', row_id: 3, source: COMEXT, price_value: 5.5, unit: 'kg', eur_per_kg: 5.5, period_label: '2026-07', period_end: '2026-07-31', frequency: 'M' }),
  price({ price_type: 'export_unit_value', market_iso3: 'ITA', row_id: 4, source: COMEXT, price_value: 4.1, unit: 'kg', eur_per_kg: 4.1, period_label: '2025-01', period_end: '2025-01-31', frequency: 'M' }),
]

test('the short list: one line per market, Eurostat without FAO\'s copy, current before old, the main markets first', () => {
  assert.deepEqual(pickCountryPrices(PRODUCER, '2026-11-11').map((r) => r.source?.key), ['eurostat_honey_prices'])
  // FAO alone, or FAO newer than Eurostat, stays
  assert.equal(pickCountryPrices([PRODUCER[1]], '2026-11-11').length, 1)
  assert.equal(pickCountryPrices([price({ period_label: '2023' }), PRODUCER[1]], '2026-11-11').length, 1 + 0)   // same market: the newest listed first
  assert.deepEqual(pickCountryPrices(EXPORTS, '2026-11-11').map((r) => `${r.market_iso3} ${r.period_label}`), ['USA 2026-08', 'SYR 2026-08', 'ITA 2025-01'])
})

test('country page, simple view: the prices by kind in euro per kilo, each number a button to fix it', () => {
  const p = profile([
    { price_type: 'producer', rows: PRODUCER, count: 2, latest_period_label: '2024', link: '/prezzi?tipo=producer&origini=DEU' },
    { price_type: 'export_unit_value', rows: EXPORTS, count: 9, latest_period_label: '2026-08', link: '/prezzi?tipo=export_unit_value&origini=DEU' },
  ])
  const html = show(p)
  const s = text(html)
  assert.match(s, /^Prezzi del miele L’ultimo prezzo per ogni tipo, in euro al chilo\. Se un numero è sbagliato, toccalo e scrivi quello giusto\./)
  assert.match(s, /Prezzi pagati all'apicoltore .* tutto il miele 15,13 €\/kg Tocca per correggere questo numero 2024 Fonte: Eurostat · 2024/)
  assert.equal(s.split('15,13 €/kg').length - 1, 1)                            // not twice (FAO repeats Eurostat)
  assert.match(html, /data-fix-value="67235"/)
  assert.match(s, /con destinazione Stati Uniti/)
  assert.match(s, /4,10 €\/kg .*gen 2025 Dato di gen 2025: non recente/)          // an old figure says so
  assert.match(s, /Altri 5 prezzi/)
  assert.doesNotMatch(s, /Un altro prezzo/)                                    // FAO's copy is not "one more price"
  assert.match(html, /href="\/prezzi\?tipo=export_unit_value&amp;origini=DEU"/)
  // what the person types is read in the unit on screen; the stored row keeps its own
  const f = priceFigure(PRODUCER[0], 'Germania', 'DEU', { value: 15.1341, unit: 'kg', currency: 'EUR' })
  assert.deepEqual([f?.value, f?.unit, f?.currency, f?.shown?.unit], [1513.41, '100kg', 'EUR', 'kg'])
  assert.equal(priceFigure(price({ row_id: null }), 'x', 'DEU'), null)
  // the read-only phone copy shows the prices, never the button
  setMirrorMode(true)
  try {
    const copy = show(p)
    assert.match(text(copy), /15,13 €\/kg/)
    assert.doesNotMatch(copy, /data-fix-value=/)
  } finally {
    setMirrorMode(null)
  }
  assert.match(text(show(p, 'en')), /^Honey prices The latest price of each kind, in euro per kilo\./)
})

test('a country with no price says so in words instead of an empty space', () => {
  const s = text(show(profile([])))
  assert.equal(s, 'Prezzi del miele Nessuna delle fonti che Paladex legge pubblica un prezzo per il miele di questo paese.')
})
