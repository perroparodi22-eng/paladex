// FE-10: at the 1024 px tablet width the price tables were ~990 px wide in a 648 px panel, so
// source, freshness, status and document (provenance every number must carry) sat behind a
// horizontal scroll. Below xl the tables use a compact layout: provenance is one cell pinned to the
// right edge of every row and only ~6 columns remain. (Widths were measured in a browser at
// 1024x768 on the demo preview: 648/648 px for both tables after the change.)
// Status labels come from /api/meta, not loaded here, so badges show the raw status key.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { LatestTable } from '@/components/prices/LatestTable'
import { RecordsTable } from '@/components/prices/RecordsTable'
import type { LatestRow, ObservationsResponse, SeriesIdentity } from '@/components/prices/types'
import { disambiguateLabels } from '@/components/prices/utils'
import { newQueryClient, render, text } from './helpers'

const SOURCE = { key: 'usda_honey', name: 'USDA National Honey Report', publisher: 'USDA AMS', reliability: 'official' }
const DOC = 'https://example.org/honey-report.pdf'

const latestRow = (id: string, stale = false) => ({
  series_id: id, source: SOURCE, price_type: 'wholesale_bulk', origin_iso3: 'ARG', origin_label: null, market_iso3: 'USA',
  market_location: null, variety: 'clover', variety_raw: ['Clover'], color_grade: 'white', terms: null, organic: false,
  currency: 'USD', unit: 'kg', native_frequency: 'M', freq: 'M', reliability: 'official', is_demo: false,
  latest: { period_label: '2026-09', period_start: '2026-09-01', period_end: '2026-09-30', value: 3.58, low: 3.43, high: 3.72, original: null,
    n_points: 1, expected_points: 1, periods: ['2026-09'], fx_missing: 0, published_at: '2026-10-28', collected_at: '2026-10-29', source_url: DOC },
  period_label: '2026-09', published_at: '2026-10-28', collected_at: '2026-10-29', source_url: DOC, data_status: 'provisional',
  previous: { period_label: '2026-08', value: 3.5, n_points: 1, published_at: null }, year_ago: { period_label: '2025-09', value: 3.2, n_points: 1, published_at: null },
  change_prev_pct: 2.3, change_yoy_pct: 11.9,
  freshness: { status: stale ? 'stale' : 'current', age_days: 7, reference_date: '2026-10-28', expected_max_age_days: 45, basis: 'source' }, is_stale: stale,
}) as unknown as LatestRow

type Cell = { cls: string[]; html: string }
function bodyRows(html: string): Cell[][] {
  const tbody = html.slice(html.indexOf('<tbody>'), html.indexOf('</tbody>'))
  return tbody.split('<tr').slice(1).map((tr) => tr.split('<td').slice(1).map((td) => ({
    cls: (/^\s*class="([^"]*)"/.exec(td)?.[1] ?? '').split(/\s+/), html: td,
  })))
}
const shownBelowXl = (c: Cell) => !c.cls.includes('hidden')
const pinned = (c: Cell) => c.cls.includes('xl:hidden') && c.cls.includes('sticky') && c.cls.includes('right-0')

function assertProvenancePinned(rows: Cell[][], maxCols: number, expect: RegExp[]) {
  assert.ok(rows.length > 0)
  for (const cells of rows) {
    const visible = cells.filter(shownBelowXl)
    assert.ok(visible.length <= maxCols, `at most ${maxCols} columns below xl, got ${visible.length}`)
    const prov = visible.filter(pinned)
    assert.equal(prov.length, 1, 'one provenance cell pinned to the right edge')
    assert.equal(visible[visible.length - 1], prov[0], 'it is the last cell of the row')
    for (const re of expect) assert.match(text(prov[0].html), re)
    assert.ok(prov[0].html.includes(`href="${DOC}"`), 'original document link')
  }
}

test('latest prices: provenance and freshness are pinned in view below xl', () => {
  const html = render(<LatestTable rows={[latestRow('a'), latestRow('b', true)]} unit="kg" colorOf={() => undefined} toggle={() => {}} />)
  // toggle, origin, variety (+colour), price (+period), change (m/m + y/y), source and status
  assertProvenancePinned(bodyRows(html), 6, [/USDA AMS/, /28 ott 2026/, /aggiornato/i, /provisional/])
  // Both changes are still shown in the compact layout, with their labels.
  const change = bodyRows(html)[0].filter(shownBelowXl).find((c) => /m\/m/.test(text(c.html)))
  assert.ok(change && /a\/a/.test(text(change.html)) && /\+2,3%/.test(text(change.html)) && /\+11,9%/.test(text(change.html)))
  // A stale row keeps its highlight on the pinned cell too.
  assert.ok(bodyRows(html)[1].find(pinned)!.cls.includes('bg-[#FBF7EC]'))
})

test('history of observations: status, source, date and document pinned in view below xl', () => {
  const qc = newQueryClient()
  const obs: ObservationsResponse = { total: 1, page: 1, page_size: 20, pages: 1, rows: [{
    id: 1, source: SOURCE, price_type: 'wholesale_bulk', origin_iso3: 'ARG', origin_label: null, market_iso3: 'USA', market_location: null,
    variety: 'clover', variety_raw: 'Clover', color_grade: 'white', organic: false, terms: null, price_low: 3.43, price_value: 3.58, price_high: 3.72,
    currency: 'USD', unit: 'kg', price_per_kg: 3.58, usd_per_kg: 3.58, eur_per_kg: 3.3, fx_date: null, volume_kg: null, period_label: '2026-09',
    period_start: '2026-09-01', period_end: '2026-09-30', frequency: 'M', published_at: '2026-10-28', collected_at: '2026-10-29',
    source_url: DOC, data_status: 'provisional', reliability: 'official', revision: 2, is_demo: false, notes: null,
  }] }
  const filters = { price_type: 'wholesale_bulk' }
  qc.setQueryData(['prices', 'observations', { ...filters, from: undefined }, 1], obs)
  const html = render(<RecordsTable filters={filters} from={null} ccy="USD" unit="kg" />, { qc })
  // period, origin, variety (+colour), as published, converted, provenance
  assertProvenancePinned(bodyRows(html), 6, [/USDA AMS/, /28 ott 2026/, /provisional/, /revisione 2/])
})

// Review of 5 Nov 2026: Cuneo publishes acacia monthly and as an annual average; both series read
// "Italia · Acacia · Camera di Commercio di Cuneo" in the chart legend.
test('two series that would share a legend name get the terms that tell them apart', () => {
  const id = (sid: string, terms: string) => ({
    id: sid, source: { key: 'cciaa_cuneo_miele', name: 'CCIAA Cuneo', publisher: 'Camera di Commercio di Cuneo', reliability: 'industry' },
    price_type: 'wholesale_bulk', origin_iso3: 'ITA', origin_label: null, market_iso3: 'ITA', market_location: 'Cuneo', variety: 'acacia',
    variety_raw: ['Acacia'], color_grade: null, terms, organic: false,
  }) as unknown as SeriesIdentity & { id: string }
  const series = [
    id('a', 'fusto da 3 q.li; media annua; franco partenza dal magazzino; IVA compresa'),
    id('b', 'fusto da 3 q.li; franco partenza dal magazzino; IVA compresa'),
    id('c', 'secchio da 25 kg; IVA compresa'),
  ]
  const same = 'Italia · Acacia · Camera di Commercio di Cuneo'
  const out = disambiguateLabels(series, { a: same, b: same, c: 'Italia · Castagno' })
  assert.equal(out.a, `${same} · media annua`)
  assert.equal(out.b, same)
  assert.equal(out.c, 'Italia · Castagno')
  assert.equal(new Set([out.a, out.b]).size, 2)
})
