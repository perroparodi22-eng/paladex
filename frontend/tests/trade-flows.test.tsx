// FE-2: data-quality issues link to /commercio?reporter=…&partner=…&flow=…; the "Flussi" panel
// must open on that market, flow and partner (and never pair a linked partner with another market).
// FE-7: the partner rows that drive the chart must be reachable and selectable from the keyboard.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { FlowsPanel, linkedSelection, rowKeys } from '@/components/trade/FlowsPanel'
import type { FacetsResponse, FlowsResponse } from '@/components/trade/types'
import { newQueryClient, render, text } from './helpers'

const flowsOf = (...f: ('import' | 'export')[]) => Object.fromEntries(f.map((x) => [x, { frequencies: ['A'], years: [2024], rows: 5 }]))
const reporter = (iso3: string, name: string, flows: ('import' | 'export')[]) => ({
  iso3, name_it: name, name_en: name, is_aggregate: false, flows: flowsOf(...flows), sources: ['comtrade'], rows: 5,
  first_period: '2024', last_period: '2024',
})
const FACETS = {
  total_rows: 15, partners: [], years: [], months: [], default_year: { import: 2024, export: 2024 }, sources: [], providers: [],
  reporters: [reporter('ITA', 'Italia', ['import']), reporter('USA', 'Stati Uniti', ['import']), reporter('ARG', 'Argentina', ['export'])],
} as unknown as FacetsResponse

const selectedMarket = (html: string) => /<option value="([A-Z0-9]+)" selected="">/.exec(html)?.[1]
const selectedFlow = (html: string) => /<button role="tab" aria-selected="true"[^>]*>([^<]+)</.exec(html)?.[1]

test('a quality-issue link opens the linked market, flow and partner', () => {
  const html = render(<FlowsPanel facets={FACETS} year={null} metric="volume" />, { url: '/commercio?reporter=USA&partner=ARG&flow=import' })
  assert.equal(selectedMarket(html), 'USA')
  assert.equal(selectedFlow(html), 'Importazioni')
  // The chart is on the linked partner (title names it, and the "back to total" control is offered).
  assert.match(text(html), /Stati Uniti.*ARG/)
  assert.match(text(html), /totale/i)
})

test('an export link opens the export flow', () => {
  const html = render(<FlowsPanel facets={FACETS} year={null} metric="volume" />, { url: '/commercio?reporter=ARG&partner=USA&flow=export' })
  assert.equal(selectedMarket(html), 'ARG')
  assert.equal(selectedFlow(html), 'Esportazioni')
})

test('without a link the panel opens on Italy, imports, total', () => {
  const html = render(<FlowsPanel facets={FACETS} year={null} metric="volume" />, { url: '/commercio' })
  assert.equal(selectedMarket(html), 'ITA')
  assert.equal(selectedFlow(html), 'Importazioni')
})

test('a stale link keeps no partner when its market does not resolve for the flow', () => {
  const sp = (q: string) => new URLSearchParams(q)
  assert.deepEqual(linkedSelection(sp('reporter=usa&partner=arg&flow=import'), FACETS), { reporter: 'USA', partner: 'ARG', flow: 'import' })
  // Unknown market, or a market without that flow: fallback market on its total.
  assert.equal(linkedSelection(sp('reporter=XXX&partner=ARG&flow=import'), FACETS).partner, 'WLD')
  assert.equal(linkedSelection(sp('reporter=USA&partner=ARG&flow=export'), FACETS).partner, 'WLD')
  const html = render(<FlowsPanel facets={FACETS} year={null} metric="volume" />, { url: '/commercio?reporter=XXX&partner=ARG&flow=import' })
  assert.equal(selectedMarket(html), 'ITA')
  assert.doesNotMatch(text(html), /Italia.*ARG/)
})

const prov = { source: { key: 'comtrade', name: 'UN Comtrade', publisher: 'UN', reliability: 'official' }, source_url: null, published_at: null, collected_at: null, period_label: '2024', period_start: null, period_end: null, frequency: 'A', data_status: 'published', reliability: 'official', is_demo: false }
const figures = { net_weight_kg: 1_000_000, usd_value: 4_000_000, value: null, currency: null, value_basis: 'CIF', unit_value_usd_per_kg: 4, fx_missing: false }
const row = (iso3: string, rank: number) => ({ ...prov, ...figures, iso3, rank, name_it: iso3, name_en: iso3, known: true, share_volume_pct: 50, share_value_pct: 50, prev_net_weight_kg: null, yoy_volume_pct: null, months_count: null, link: `/paesi/${iso3}` })
const FLOWS = {
  ...prov, reporter: 'USA', flow: 'import', year: 2024, metric: 'volume', default_year: 2024, available_years: [2024], complete_years: [2024],
  available: true, rows: [row('ARG', 1), row('UKR', 2)], others: null, unallocated: null, name_it: 'Stati Uniti', name_en: 'United States',
  total: { ...prov, ...figures, iso3: 'USA', year: 2024, name_it: 'Stati Uniti', name_en: 'United States', summed_from_partners: false, summed_from_months: false, partners_count: 2, months_count: null, complete: true, prev: null, yoy_volume_pct: null, yoy_value_pct: null },
  share_basis: 'world_total', alternatives: [], providers: [],
} as unknown as FlowsResponse

test('partner rows and the total row are keyboard focusable, the selected one is marked', () => {
  const qc = newQueryClient()
  qc.setQueryData(['trade', 'flows', 'USA', 'import', undefined, 'volume'], FLOWS)
  const html = render(<FlowsPanel facets={FACETS} year={null} metric="volume" />, { url: '/commercio?reporter=USA&partner=ARG&flow=import', qc })
  const rows = [...html.matchAll(/<tr ([^>]*)>/g)].map((m) => m[1]).filter((a) => a.includes('cursor-pointer'))
  assert.equal(rows.length, 3, 'ARG, UKR and the total row')
  for (const r of rows) assert.match(r, /tabindex="0"/)
  assert.equal(rows.filter((r) => r.includes('aria-current="true"')).length, 1)
  assert.match(rows[0], /aria-current="true"/)
})

test('Enter and Space select a row; keys on the country link inside it do not', () => {
  let picked = 0
  const keys = rowKeys(() => { picked += 1 }, false)
  const row = {}
  let prevented = 0
  const ev = (key: string, target: object) => ({ key, target, currentTarget: row, preventDefault: () => { prevented += 1 } }) as never
  keys.onKeyDown(ev('Enter', row))
  keys.onKeyDown(ev(' ', row))
  keys.onKeyDown(ev('a', row))
  keys.onKeyDown(ev('Enter', {}))          // Enter on the nested <a>: the link handles it
  assert.equal(picked, 2)
  assert.equal(prevented, 2)
  assert.equal(keys.tabIndex, 0)
  assert.equal(rowKeys(() => {}, true)['aria-current'], 'true')
})
