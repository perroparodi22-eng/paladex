// Country pages, review of 5 Nov 2026:
// - the headline tiles showed an estimate (FAOSTAT flag E, Comtrade estimate) as a plain figure, and
//   the production tile picked the first source even when another had published a newer year;
// - the curated harvest season was English in the Italian page ("Apr–Sep");
// - the map legend read "0 – 0" for the smallest class and "2,4K" (not Italian) for thousands;
// - USDA colour grades were shown as raw English keys ("light amber") in the price table.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fmtBound } from '@/components/countries/metrics'
import { harvestSeason } from '@/components/countries/ProfileSections'
import type { CountryProfile } from '@/components/countries/types'
import { KpiRow } from '@/pages/CountryDetail'
import { newQueryClient, render, text } from './helpers'

const META = {
  countries: [], varieties: [], price_types: [], reliability: [], flags: {}, show_demo: false, language: 'it',
  data_status: [
    { key: 'published', it: 'Dato pubblicato', en: 'Published' },
    { key: 'estimate', it: 'Stima', en: 'Estimate' },
    { key: 'provisional', it: 'Provvisorio', en: 'Provisional' },
  ],
}

const src = (key: string, publisher: string) => ({ key, name: publisher, publisher, reliability: 'official', homepage: null })
const prov = { source_url: null, published_at: '2026-07-24', collected_at: null, period_start: null, period_end: null, frequency: 'A', reliability: 'official', is_demo: false }
const point = (source: ReturnType<typeof src>, year: string, value: number, status: string) => ({
  ...prov, source, period_label: year, value, unit: 't', flag_raw: null, notes: null, data_status: status,
})
const series = (source: ReturnType<typeof src>, year: string, value: number, status: string) => {
  const latest = point(source, year, value, status)
  return { source, unit: 't', frequency: 'A', points: [latest], latest, is_demo: false, freshness: null }
}
const total = (year: number, kg: number, status: string) => ({
  ...prov, source: src('un_comtrade', 'UN Comtrade'), period_label: String(year), data_status: status, iso3: 'BRA', year,
  name_it: 'Brasile', name_en: 'Brazil', net_weight_kg: kg, usd_value: null, value: null, currency: null, value_basis: null,
  unit_value_usd_per_kg: null, fx_missing: false, summed_from_partners: false, summed_from_months: false, partners_count: null,
  months_count: null, complete: true, prev: null, yoy_volume_pct: null, yoy_value_pct: null,
})
const flow = (latest: ReturnType<typeof total> | null) => ({ available: Boolean(latest), latest, series: [], excluded_partial: [], discrepancies: [], partners: null, mirror: null })

function profile(prodSeries: ReturnType<typeof series>[], exportTotal: ReturnType<typeof total> | null): CountryProfile {
  return {
    production: { available: true, metrics: [{ metric: 'production', series: prodSeries }], providers: [] },
    trade: { export: flow(exportTotal), import: flow(null), providers: [] },
    news: { available: false, items: [], count_30d: 0, days: 30, link: '/notizie', providers: [] },
  } as unknown as CountryProfile
}

function renderKpis(p: CountryProfile, lang: 'it' | 'en' = 'it') {
  const qc = newQueryClient()
  qc.setQueryData(['meta'], META)
  return text(render(<KpiRow p={p} />, { qc, lang }))
}

test('an estimated headline figure carries its "Stima" badge; a published one does not', () => {
  const fao = src('faostat', 'FAOSTAT')
  const estimated = renderKpis(profile([series(fao, '2024', 69297.65, 'estimate')], total(2025, 37_931_000, 'estimate')))
  assert.match(estimated, /69\.298 t anno 2024 Stima/)
  assert.match(estimated, /37\.931 t anno 2025 Stima/)
  const published = renderKpis(profile([series(fao, '2024', 21857, 'published')], total(2025, 5_495_737, 'published')))
  assert.doesNotMatch(published, /Stima|Dato pubblicato/)
})

test('the production tile shows the most recent year any source published', () => {
  const p = profile([series(src('faostat', 'FAOSTAT'), '2024', 60960, 'published'), series(src('nass', 'USDA NASS'), '2025', 52487.9, 'published')], null)
  const out = renderKpis(p)
  assert.match(out, /52\.488 t anno 2025/)
  assert.match(out, /Fonte: USDA NASS/)
  assert.doesNotMatch(out, /60\.960/)
})

test('the harvest season is written in Italian on the Italian page', () => {
  assert.equal(harvestSeason('Apr–Sep', 'it'), 'apr–set')
  assert.equal(harvestSeason('year-round, peaks Sep–Mar', 'it'), 'tutto l’anno, picco set–mar')
  assert.equal(harvestSeason('Mar–Jun (Yucatán)', 'it'), 'mar–giu (Yucatán)')
  assert.equal(harvestSeason('Apr–Sep', 'en'), 'Apr–Sep')
})

test('map legend bounds: small volumes keep decimals, Italian thousands read "mila"', () => {
  assert.equal(fmtBound(0.09, 'exports', 'it'), '0,09')
  assert.equal(fmtBound(2.37, 'exports', 'it'), '2,4')
  assert.equal(fmtBound(60.5, 'exports', 'it'), '61')
  assert.equal(fmtBound(2364.84, 'exports', 'it'), '2,4 mila')
  assert.equal(fmtBound(175521.3, 'exports', 'it'), '175,5 mila')
  assert.doesNotMatch(fmtBound(2364.84, 'exports', 'it'), /K/)
  assert.equal(fmtBound(12, 'news', 'it'), '12')
})

test('one news article is singular in the headline tile', () => {
  const p = profile([], null)
  const one = { ...p, news: { ...p.news, available: true, count_30d: 1 } } as CountryProfile
  assert.match(renderKpis(one), /1 articolo che cita il paese/)
  const many = { ...p, news: { ...p.news, available: true, count_30d: 4 } } as CountryProfile
  assert.match(renderKpis(many), /4 articoli che citano il paese/)
})
