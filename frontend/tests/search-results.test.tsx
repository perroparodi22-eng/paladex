// FE-3: "Serie di prezzi disponibili" links must name a price type the series really has, or the
// price page opens on wholesale and shows "Nessun dato" for an origin that only has, e.g., unit values.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ResultGroup, priceHitTarget } from '@/components/search/SearchResults'
import type { PriceHit, SearchGroup } from '@/components/search/types'
import { hrefs, render } from './helpers'

const hit = (o: Partial<PriceHit>): PriceHit => ({
  origin_iso3: 'MEX', origin_name_it: 'Messico', origin_name_en: 'Mexico', variety: 'unspecified', variety_it: 'Non specificata',
  variety_en: 'Unspecified', price_types: ['import_unit_value'], observations: 12, sources: 1, latest_period_end: '2026-08-31',
  latest_period_label: '2026-08', is_demo: false, target: '/prezzi?origin=MEX&variety=unspecified', external: false, ...o,
})

test('a series with only unit values opens the unit-value type', () => {
  const group = { key: 'prices', items: [hit({})], total: 1, see_all: null } as SearchGroup
  const links = hrefs(render(<ResultGroup group={group} query="messico" />, { url: '/cerca?q=messico' }))
  const link = links.find((h) => h.startsWith('/prezzi'))
  assert.ok(link, 'price result link rendered')
  assert.equal(new URLSearchParams(link.split('?')[1]).get('price_type'), 'import_unit_value')
})

test('the type picked is the first one a bulk buyer cares about', () => {
  const to = priceHitTarget(hit({ price_types: ['producer', 'import_unit_value', 'wholesale_bulk'] }))
  assert.equal(new URLSearchParams(to.split('?')[1]).get('price_type'), 'wholesale_bulk')
  assert.equal(new URLSearchParams(to.split('?')[1]).get('origin'), 'MEX')
})

test('a link that already names a type, or a hit without types, is left alone', () => {
  assert.equal(priceHitTarget(hit({ target: '/prezzi?origin=MEX&price_type=producer' })), '/prezzi?origin=MEX&price_type=producer')
  assert.equal(priceHitTarget(hit({ target: '/prezzi?tipo=producer' })), '/prezzi?tipo=producer')
  assert.equal(priceHitTarget(hit({ price_types: [] })), '/prezzi?origin=MEX&variety=unspecified')
  assert.equal(priceHitTarget(hit({ target: '/prezzi', price_types: ['retail'] })), '/prezzi?price_type=retail')
})
