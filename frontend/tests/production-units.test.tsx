// Production statistics, review of 5 Nov 2026 (and the new IBGE Brazil source): units were shown as
// stored ("ALVEARI · NUMBER", "21,8 kg/colony", "1000 BRL"), the harvest metric selector showed raw
// keys ("stocks", "production_value"), and the harvest chart was titled "produzione annua" whatever
// figure was selected (hives, yield, value in reais).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fmtProduction } from '@/components/archive/ProductionArchive'
import { ProfileProduction } from '@/components/countries/ProfileProduction'
import type { CountryProfile, ProductionMetric } from '@/components/countries/types'
import { ProductionChart } from '@/components/harvest/ProductionPanel'
import type { ProductionCountryResponse } from '@/components/harvest/types'
import { fmtProdUnit } from '@/lib/format'
import { newQueryClient, render, text } from './helpers'

test('production units are written in words, in both languages', () => {
  assert.equal(fmtProdUnit('t', 'it'), 't')
  assert.equal(fmtProdUnit('kg/colony', 'it'), 'kg per alveare')
  assert.equal(fmtProdUnit('kg/colony', 'en'), 'kg per hive')
  assert.equal(fmtProdUnit('number', 'it'), 'alveari')
  assert.equal(fmtProdUnit('1000 BRL', 'it'), 'migliaia di BRL')
  assert.equal(fmtProdUnit('1000 BRL', 'en'), 'thousand BRL')
  assert.equal(fmtProduction(1_234_567, '1000 BRL', 'it'), '1.234.567 migliaia di BRL')
  assert.equal(fmtProduction(21.8, 'kg/colony', 'it'), '21,8 kg per alveare')
})

const src = { key: 'ibge_pam', name: 'IBGE – Pesquisa da Pecuária Municipal', publisher: 'IBGE', reliability: 'official', homepage: null }
const point = (year: string, value: number, unit: string) => ({
  source: src, source_url: null, published_at: '2026-09-30', collected_at: null, period_label: year, period_start: null, period_end: null,
  frequency: 'A', data_status: 'published', reliability: 'official', is_demo: false, value, unit, flag_raw: null, notes: null,
})
const metric = (key: string, unit: string, value: number): ProductionMetric => {
  const latest = point('2024', value, unit)
  return { metric: key, series: [{ source: src, unit, frequency: 'A', points: [point('2023', value * 0.9, unit), latest], latest, is_demo: false, freshness: null }] } as unknown as ProductionMetric
}
const METRICS = [metric('production', 't', 64_000), metric('colonies', 'number', 1_100_000), metric('stocks', 't', 900), metric('production_value', '1000 BRL', 1_234_567)]

test('harvest chart: every metric has a name and the title follows the selected one', () => {
  const qc = newQueryClient()
  const data: ProductionCountryResponse = { iso3: 'BRA', name_it: 'Brasile', name_en: 'Brazil', regions: [], available: true, metrics: METRICS, providers: [], sources: [], is_demo: false }
  qc.setQueryData(['harvest', 'production', 'country', 'BRA'], data)
  const view = (m: string, lang: 'it' | 'en' = 'it') =>
    text(render(<ProductionChart iso3="BRA" metric={m} years="20" onMetric={() => {}} onYears={() => {}} />, { qc, lang }))
  const value = view('production_value')
  assert.match(value, /Brasile: valore della produzione/)
  assert.match(value, /Produzione Alveari Scorte Valore della produzione/)
  assert.match(value, /IBGE · migliaia di BRL/)
  assert.doesNotMatch(value, /produzione annua|production_value|stocks|1000 BRL/)
  assert.match(view('production'), /Brasile: produzione annua/)
  assert.match(view('colonies'), /Brasile: alveari/)
  assert.match(view('stocks'), /Brasile: scorte/)
  assert.match(view('production_value', 'en'), /Brazil: production value .*IBGE · thousand BRL/)
})

test('country profile: units in words, the new metric named', () => {
  const p = { available: true, metrics: [metric('production', 't', 64_000), metric('colonies', 'number', 1_100_000), metric('yield_per_colony', 'kg/colony', 21.8), metric('production_value', '1000 BRL', 1_234_567)], providers: [] } as unknown as CountryProfile['production']
  const out = text(render(<ProfileProduction data={p} />))
  assert.match(out, /Valore della produzione/)
  assert.doesNotMatch(out, /production_value/)
})
