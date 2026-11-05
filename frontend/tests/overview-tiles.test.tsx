// Overview, review of 5 Nov 2026: the "Ultimo dato pubblicato" tiles showed USDA colour grades as raw
// English keys ("Millefiori · light amber") in the Italian interface; the Prices page names them.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PriceTiles } from '@/components/overview/PriceTiles'
import type { PricesBlock, PriceTile } from '@/components/overview/types'
import { render, text } from './helpers'

const tile = (id: string, color: string | null): PriceTile => ({
  id, label: '', origin_iso3: 'ARG', origin_label: null, variety: 'polyflora', variety_raw: null, price_type: 'wholesale_bulk',
  market_iso3: 'USA', market_location: null, color_grade: color, organic: false, terms: null, usd_per_kg: 3.91, eur_per_kg: 3.4,
  price_per_kg: 3.91, currency: 'USD', price_value: 1.77, price_low: null, price_high: null, unit: 'lb', fx_date: null,
  mom_pct: null, mom_period_label: null, yoy_pct: null, yoy_period_label: null, spark: [],
  freshness: { status: 'current', age_days: 6, reference_date: '2026-10-30' } as PriceTile['freshness'],
  source: null, source_url: null, published_at: null, collected_at: null, period_label: '2026-09', period_start: '2026-09-01',
  period_end: '2026-09-30', frequency: 'M', data_status: 'published', reliability: 'official', is_demo: false, link: '/prezzi',
})

const block = (items: PriceTile[]): PricesBlock => ({
  items, price_types: ['wholesale_bulk'], mixed_price_types: false, series_available: items.length, updated_at: null,
  latest_published_at: null, sources: [], providers: [], link: '/prezzi',
})

test('colour grades on the overview tiles are named in the interface language', () => {
  const b = block([tile('a', 'white'), tile('b', 'extra light amber'), tile('c', 'light amber'), tile('d', null)])
  const it = text(render(<PriceTiles block={b} />, { lang: 'it' }))
  assert.match(it, /· Bianco/)
  assert.match(it, /· Ambra extra chiaro/)
  assert.match(it, /· Ambra chiaro/)
  assert.doesNotMatch(it, /light amber|white/)
  const en = text(render(<PriceTiles block={b} />, { lang: 'en' }))
  assert.match(en, /· Extra light amber/)
})
