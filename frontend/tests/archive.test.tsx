// Historical archive (/archivio): the month overlay never fills a missing month, a part year says so
// and is compared on the same months only, the revision viewer shows superseded values with their
// dates (or says honestly that nothing was revised), the page opens on a series with data.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { OverlayChart, YearsTable } from '@/components/archive/PriceArchive'
import { QuotesTables } from '@/components/archive/QuotesArchive'
import { RevisionsView } from '@/components/archive/RevisionsArchive'
import { resolvePriceSelection } from '@/components/archive/state'
import { YtdBlock } from '@/components/archive/TradeArchive'
import type { Overlay, OverlayPoint, PriceOptionsResponse, QuotesHistoryResponse, RevisionsResponse, TradeHistoryResponse, YearRow } from '@/components/archive/types'
import { overlayRows } from '@/components/archive/utils'
import archive from '@/i18n/pages/archive'
import { render, text } from './helpers'

function pt(label: string, value: number): OverlayPoint {
  return { period_label: label, value, low: null, high: null, n_points: 1, expected_points: null, volume_kg: 1e6,
    published_at: '2026-10-16', collected_at: '2026-11-04T08:00:00', source_url: null, data_status: 'published',
    is_demo: false, original: null }
}

const OVERLAY: Overlay = {
  latest_year: 2026,
  years: [
    { year: 2026, months: 2, points: [pt('2026-01', 2.2), null, pt('2026-03', 2.4), ...Array(9).fill(null)] },
    { year: 2025, months: 12, points: Array.from({ length: 12 }, (_, i) => pt(`2025-${String(i + 1).padStart(2, '0')}`, 2 + i / 100)) },
    { year: 2024, months: 0, points: Array(12).fill(null) },
  ],
}

test('month overlay: a missing month stays empty, never interpolated', () => {
  const rows = overlayRows(OVERLAY, 'kg', 'it')
  assert.equal(rows.length, 12)
  assert.equal(rows[0].label, 'gen')
  assert.equal(rows[0].y2026, 2.2)
  assert.equal(rows[1].y2026, null, 'February 2026 is missing: null, not a value between January and March')
  assert.equal(rows[2].y2026, 2.4)
  assert.equal(rows[5].y2024, null)
  const lb = overlayRows(OVERLAY, 'lb', 'en')
  assert.equal(lb[0].label, 'Jan')
  assert.ok(Math.abs((lb[0].y2026 as number) - 2.2 * 0.45359237) < 1e-9)
  const legend = text(render(<OverlayChart ov={OVERLAY} unit="kg" unitText="EUR/kg" />))
  assert.match(legend, /2026 2 mesi con dati/)
  assert.match(legend, /2024 0 mesi con dati/)
})

function year(o: Partial<YearRow>): YearRow {
  return {
    year: 2026, average: 2.2178, weighting: 'volume', volume_kg: 20_772_875, periods: 8, expected_periods: 12, complete: false,
    first_period: '2026-01', last_period: '2026-08', min: { period_label: '2026-01', value: 2.0228 },
    max: { period_label: '2026-08', value: 2.4981 }, change_pct: 8.44, change_periods: 8, change_same_periods_only: true,
    data_status: 'provisional', published_at: '2026-10-16', collected_at: '2026-11-04T08:00:00',
    source_url: 'https://ec.europa.eu/eurostat', is_demo: false, ...o,
  }
}

test('year table: part years are marked and compared on the same months only', () => {
  const years = [year({ year: 2025, average: 2.033, periods: 12, complete: true, change_pct: -0.18, change_periods: 12,
    change_same_periods_only: false, data_status: 'published' }), year({})]
  const it = text(render(<YearsTable years={years} unitText="EUR/kg" unit="kg" />))
  assert.match(it, /2026 2,22 8 su 12 anno parziale · gen 2026–ago 2026/)
  assert.match(it, /\+8,4% stessi 8 mesi/)
  assert.match(it, /2025 2,03 12 su 12/)
  assert.match(it, /−0,2%/)
  assert.doesNotMatch(it.split('2025 2,03')[1], /stessi 12 mesi/, 'a full-year comparison needs no note')
  const en = text(render(<YearsTable years={years} unitText="EUR/kg" unit="kg" />, { lang: 'en' }))
  assert.match(en, /8 of 12 part year/)
  assert.match(en, /same 8 months/)
  const first = text(render(<YearsTable years={[year({ year: 2021, change_pct: null, change_periods: 0, change_same_periods_only: false })]} unitText="EUR/kg" unit="kg" />))
  assert.match(first, /2021 2,22 8 su 12 anno parziale · gen 2026–ago 2026 2,02 gen 2026 2,50 ago 2026 —/)
})

const NO_REVISIONS: RevisionsResponse = {
  kind: 'price', periods: [], counts: { periods: 57, stored_values: 57, revised: 0, withdrawn: 0 },
  first_period: '2021-12-01', last_period: '2026-08-01', last_collected_at: '2026-11-04T08:00:00',
}

test('revisions: an honest empty state when the source never revised the series', () => {
  const body = text(render(<RevisionsView d={NO_REVISIONS} />))
  assert.match(body, /57 valori della fonte, 57 versioni salvate in tutto/)
  assert.match(body, /Nessuna revisione per questa serie: tutti i 57 valori sono quelli della prima pubblicazione/)
  const none = text(render(<RevisionsView d={{ ...NO_REVISIONS, counts: { periods: 0, stored_values: 0, revised: 0, withdrawn: 0 } }} />, { lang: 'en' }))
  assert.match(none, /No data stored for this series/)
})

test('revisions: superseded and current values with their publication and collection dates', () => {
  const entry = { revision: 1, supersedes_id: null, last_seen_at: null, data_status: 'published', source_url: 'https://example.org/a.pdf',
    is_demo: false, currency: 'USD', unit: 'lb', volume_kg: null }
  const d: RevisionsResponse = {
    ...NO_REVISIONS, counts: { periods: 24, stored_values: 26, revised: 1, withdrawn: 1 },
    periods: [
      { source: null, period_label: '2025-06', period_start: '2025-06-01', frequency: 'M', status: 'revised', label: 'Mixed Flower',
        revisions: [
          { ...entry, id: 1, is_current: false, value: 1.575, low: 1.39, high: 1.76, published_at: '2025-06-30', collected_at: '2026-11-04T20:35:16', change_pct: null },
          { ...entry, id: 2, is_current: true, value: 1.49, low: 1.43, high: 1.55, published_at: '2025-07-31', collected_at: '2026-11-04T20:35:23', change_pct: -5.4 },
        ] },
      { source: null, period_label: '2025-05', period_start: '2025-05-01', frequency: 'M', status: 'withdrawn', label: null,
        revisions: [{ ...entry, id: 3, is_current: false, value: 1.6, published_at: '2025-06-30', collected_at: '2026-11-04T20:35:16', change_pct: null }] },
    ],
  }
  const body = text(render(<RevisionsView d={d} />))
  assert.match(body, /rivisti: 1 · ritirati dalla fonte: 1/)
  assert.match(body, /giu 2025 Rivisto Mixed Flower/)
  assert.match(body, /1ª 1,575 USD\/lb \(1,390–1,760\) — 30 giu 2025/)
  assert.match(body, /sostituito/)
  assert.match(body, /2ª 1,490 USD\/lb \(1,430–1,550\) ▼ −5,4% 31 lug 2025/)
  assert.match(body, /in vigore/)
  assert.match(body, /mag 2025 Ritirato dalla fonte/)
  assert.match(body, /non più pubblicato/)
})

const OPTIONS: PriceOptionsResponse = {
  price_types: [{ key: 'import_unit_value', count: 100 }], price_type: 'import_unit_value',
  default: { price_type: 'import_unit_value', origin: 'ARG', variety: 'unspecified', market: 'EU27', color_grade: null },
  combos: [
    { origin: 'ARG', variety: 'unspecified', market: 'DEU', color_grade: null, rows: 50, frequencies: ['M', 'W'], first_period: '2021-12', last_period: '2026-08' },
    { origin: 'ARG', variety: 'unspecified', market: 'EU27', color_grade: null, rows: 57, frequencies: ['M'], first_period: '2021-12', last_period: '2026-08' },
    { origin: 'UKR', variety: 'unspecified', market: 'EU27', color_grade: null, rows: 57, frequencies: ['M'], first_period: '2021-12', last_period: '2026-08' },
  ],
}

test('the archive opens on a series with data (EU import unit value of Argentina)', () => {
  const sp = (q: string) => new URLSearchParams(q)
  assert.deepEqual(resolvePriceSelection(OPTIONS, sp('')),
    { price_type: 'import_unit_value', origin: 'ARG', variety: 'unspecified', market: 'EU27', color_grade: null })
  assert.equal(resolvePriceSelection(OPTIONS, sp('mercato=tutti'))?.market, null, '"every market" is an explicit choice')
  assert.equal(resolvePriceSelection(OPTIONS, sp('mercato=DEU'))?.market, 'DEU')
  assert.equal(resolvePriceSelection(OPTIONS, sp('origine=ZZZ'))?.origin, 'ARG', 'an origin without data falls back')
  assert.equal(resolvePriceSelection(OPTIONS, sp('origine=UKR'))?.market, null, 'the default market is only for the default origin')
  assert.equal(resolvePriceSelection({ ...OPTIONS, combos: [] }, sp('')), null)
})

test('trade: a year with missing months is never totalled', () => {
  const d = {
    ytd: [{ source: { key: 'eurostat_comext', name: 'Eurostat', publisher: 'Eurostat', reliability: 'official', homepage: null },
      freshness: { status: 'current', age_days: 19, reference_date: '2026-10-16' }, is_demo: false, through_month: 8, latest_label: '2026-08',
      years: [
        { year: 2026, months: 8, complete: true, net_weight_kg: 20_772_875, usd_value: null, data_status: 'provisional', published_at: '2026-10-16', source_url: null, is_demo: false, change_pct: 60.29 },
        { year: 2025, months: 8, complete: true, net_weight_kg: 12_959_598, usd_value: null, data_status: 'published', published_at: '2026-10-16', source_url: null, is_demo: false, change_pct: null },
        { year: 2024, months: 6, complete: false, net_weight_kg: null, usd_value: null, data_status: 'published', published_at: '2026-10-16', source_url: null, is_demo: false, change_pct: null },
      ] }],
  } as unknown as TradeHistoryResponse
  const body = text(render(<YtdBlock d={d} />))
  assert.match(body, /gen–ago 2026 20\.773 t ▲ \+60,3%/)
  assert.match(body, /gen–ago 2024 — mesi mancanti \(6 su 8\)/)
})

test('supplier quotes: archived ones are listed, a per-lb quote keeps its figure', () => {
  const d: QuotesHistoryResponse = {
    available: true, total: 2, origin: null, variety: null, total_all: 2, origins: [], varieties: [],
    summary: [{ year: 2026, currency: 'USD', incoterm: 'FOB', quotes: 2, suppliers: 2, min: 3.1, max: 3.6, average: 3.35, is_demo: false }],
    items: [
      { id: 2, supplier_name: 'Miel del Plata', origin_iso3: 'ARG', variety: 'polyflora', variety_note: null, price_per_kg: 3.6,
        currency: 'USD', price_quoted: 1.633, price_unit: 'lb', quantity_kg: 20_000, packaging: null, incoterm: 'FOB',
        incoterm_place: 'Buenos Aires', destination: 'ITA', date_received: '2026-03-01', valid_until: '2026-03-31', expired: true,
        archived: false, notes: null, is_demo: false, data_status: 'user_entered' },
      { id: 1, supplier_name: 'Apicola Sur', origin_iso3: 'ARG', variety: 'polyflora', variety_note: null, price_per_kg: 3.1,
        currency: 'USD', price_quoted: null, price_unit: 'kg', quantity_kg: null, packaging: null, incoterm: 'FOB',
        incoterm_place: null, destination: null, date_received: '2026-02-01', valid_until: null, expired: false,
        archived: true, notes: null, is_demo: false, data_status: 'user_entered' },
    ],
  }
  const body = text(render(<QuotesTables d={d} />))
  assert.match(body, /quotata 1,63 USD\/lb/)
  assert.match(body, /Archiviata/)
  assert.match(body, /Scaduta/)
  assert.match(body, /FOB Buenos Aires/)
  assert.match(body, /non mescolano valute né Incoterm/)
})

test('every archive string exists in both languages', () => {
  assert.deepEqual(Object.keys(archive.it).sort(), Object.keys(archive.en).sort())
})
