// FE-9: the publication rhythm of a source is shown in the UI language: the Italian page no longer
// reads "Monthly (issue dated near the end of the month)", the English one no longer
// "Settimanale (listino del mercoledì)".
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { TradeNotes } from '@/components/trade/TradeNotes'
import type { FacetsResponse } from '@/components/trade/types'
import { expectedUpdate } from '@/i18n'
import { render, text } from './helpers'

const source = (key: string, publisher: string, it: string, en: string | null) => ({
  key, name: publisher, publisher, reliability: 'official', homepage: null, frequencies: ['M'], rows: 10, first_period: '2024-01',
  last_period: '2026-08', latest_period_label: '2026-08', latest_published_at: '2026-10-10', collected_at: '2026-10-11', is_demo: false,
  expected_update: it, expected_update_en: en, freshness: { status: 'current', age_days: 20, reference_date: '2026-10-10' },
})
const FACETS = {
  total_rows: 10, reporters: [], partners: [], years: [], months: [], default_year: { import: 2025, export: 2025 }, providers: [],
  sources: [
    source('usda_fas_gats', 'USDA FAS', 'Mensile, circa 5-6 settimane dopo il mese (pubblicazione Census FT-900)', 'Monthly, about 5-6 weeks after the month (Census FT-900 release)'),
    source('un_comtrade', 'UN Comtrade', "Continuo, per paese: annuali 6–12+ mesi dopo la fine dell'anno", null),
  ],
} as unknown as FacetsResponse

test('Italian page shows the Italian rhythm, English page the English one', () => {
  const it = text(render(<TradeNotes facets={FACETS} />, { lang: 'it' }))
  assert.match(it, /USDA FAS ?: Mensile, circa 5-6 settimane/)
  assert.doesNotMatch(it, /Monthly/)
  const en = text(render(<TradeNotes facets={FACETS} />, { lang: 'en' }))
  assert.match(en, /USDA FAS ?: Monthly, about 5-6 weeks/)
  assert.doesNotMatch(en, /Mensile/)
})

test('a source without an English text falls back to the Italian one instead of showing nothing', () => {
  assert.equal(expectedUpdate({ expected_update: 'Settimanale', expected_update_en: null }, 'en'), 'Settimanale')
  assert.equal(expectedUpdate({ expected_update: 'Settimanale', expected_update_en: 'Weekly' }, 'en'), 'Weekly')
  assert.equal(expectedUpdate({ expected_update: 'Settimanale', expected_update_en: 'Weekly' }, 'it'), 'Settimanale')
  assert.equal(expectedUpdate({ expected_update: null }, 'it'), null)
})
