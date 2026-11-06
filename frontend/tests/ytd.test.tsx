// "2026 finora" first (owner's choice, 5 Nov 2026): monthly official customs data run to Aug-Oct 2026
// while the country pages and the overview led with the last FULL year. The year so far now leads,
// against THE SAME months of 2025 from the same source; the full years follow.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ProfileYtd } from '@/components/countries/ProfileYtd'
import type { CountryProfile } from '@/components/countries/types'
import { TradeHighlights } from '@/components/overview/TradeHighlights'
import type { TradeBlock, TradeSide } from '@/components/overview/types'
import { fmtMonthSpan, type YtdFigure, type YtdSection } from '@/components/trade/ytd'
import { KpiRow } from '@/pages/CountryDetail'
import { newQueryClient, render, text } from './helpers'

const META = {
  countries: [], varieties: [], price_types: [], reliability: [], flags: {}, show_demo: false, language: 'it',
  data_status: [
    { key: 'published', it: 'Dato pubblicato', en: 'Published' },
    { key: 'provisional', it: 'Provvisorio', en: 'Provisional' },
  ],
}

const src = (key: string, name: string, publisher: string) => ({ key, name, name_en: name, publisher, reliability: 'official', homepage: null })
const INDEC = src('ar_official_exports', 'Argentina – INDEC: esportazioni di miele per destinazione', 'INDEC')
const EUROSTAT = src('eurostat_comext', 'Eurostat Comext: commercio UE di miele', 'Eurostat')
const CENSUS = src('us_census_trade', 'US Census Bureau – Importazioni USA di miele', 'U.S. Census Bureau')

function fig(over: Partial<YtdFigure>): YtdFigure {
  return {
    iso3: 'ARG', name_it: 'Argentina', name_en: 'Argentina', year: 2026, prev_year: 2025, month_from: 1, month_to: 9,
    months_count: 9, is_current_year: true, net_weight_kg: 93_810_962.5, usd_value: 247_068_584, unit_value_usd_per_kg: 2.6337,
    fx_missing: false, comparable: true,
    previous: { year: 2025, period_label: '2025-01/2025-09', net_weight_kg: 69_924_500, usd_value: 163_258_000, unit_value_usd_per_kg: 2.3348, fx_missing: false, data_status: 'provisional', published_at: '2025-10-16', is_demo: false },
    prev_months_available: null, change_volume_pct: 34.16, change_value_pct: 51.33, change_unit_value_pct: 12.8,
    summed_from_partners: false, partners_count: null, excluded_months: [],
    source: INDEC, source_url: null, published_at: '2026-10-16', collected_at: '2026-11-05T18:47:23', period_label: '2026-01/2026-09',
    period_start: '2026-01-01', period_end: '2026-09-30', frequency: 'M', data_status: 'provisional', reliability: 'official', is_demo: false,
    freshness: { status: 'current', age_days: 20, reference_date: '2026-10-16' },
    ...over,
  }
}

function show(node: React.ReactNode, lang: 'it' | 'en' = 'it') {
  const qc = newQueryClient()
  qc.setQueryData(['meta'], META)
  return text(render(node, { qc, lang }))
}

test('month spans read like the owner writes them', () => {
  assert.equal(fmtMonthSpan(1, 9, 'it'), 'gen–set')
  assert.equal(fmtMonthSpan(1, 9, 'en'), 'Jan–Sep')
  assert.equal(fmtMonthSpan(1, 1, 'it'), 'gen')
})

test('profile: the country\'s own year so far, against the same months of 2025, with its source', () => {
  const s: YtdSection = { own: fig({}), status: 'ok', last_month: '2026-09', mirror: null }
  const it = show(<ProfileYtd s={s} flow="export" name="Argentina" today="2026-11-05" />)
  assert.match(it, /2026 finora \(gen–set\)/)
  assert.match(it, /93\.811 t/)
  assert.match(it, /▲ \+34,2% vs gen–set 2025 \(69\.925 t\)/)
  assert.match(it, /Fonte: INDEC/)
  assert.match(it, /Provvisorio/)
  assert.match(it, /Confronto sugli stessi mesi \(gen–set\) del 2026 e del 2025, dalla stessa fonte/)
  const en = show(<ProfileYtd s={s} flow="export" name="Argentina" today="2026-11-05" />, 'en')
  assert.match(en, /2026 so far \(Jan–Sep\)/)
  assert.match(en, /▲ \+34\.2% vs Jan–Sep 2025 \(69,925 t\)/)
  assert.match(en, /Compared on the same months \(Jan–Sep\) of 2026 and 2025, from the same source/)
})

test('a partial newest month is left out and said so; no comparison when 2025 lacks those months', () => {
  const f = fig({
    iso3: 'ITA', source: EUROSTAT, month_to: 7, comparable: false, previous: null, change_volume_pct: null, change_value_pct: null,
    change_unit_value_pct: null, prev_months_available: [11, 12], excluded_months: [{ month: '2026-08', reason: 'no_total' }],
  })
  const it = show(<ProfileYtd s={{ own: f, status: 'ok', last_month: '2026-07', mirror: null }} flow="import" name="Italia" today="2026-11-05" />)
  assert.match(it, /2026 finora \(gen–lug\)/)
  assert.match(it, /Nessun confronto con gen–lug 2025: la stessa fonte non ha tutti quei mesi/)
  assert.match(it, /Escluso agosto 2026: pubblicato senza il totale del paese \(dato parziale\)/)
  assert.doesNotMatch(it, /▲|▼/)
  const en = show(<ProfileYtd s={{ own: f, status: 'ok', last_month: '2026-07', mirror: null }} flow="import" name="Italy" today="2026-11-05" />, 'en')
  assert.match(en, /Left out August 2026: published without the country total/)
})

test('without its own monthly data: what the partners declare, one row each, never added up', () => {
  const rows = [
    fig({ iso3: 'USA', name_it: 'Stati Uniti', name_en: 'United States', source: CENSUS, link: '/paesi/USA', net_weight_kg: 70_280_000, change_volume_pct: -8.04 }),
    fig({ iso3: 'NLD', name_it: 'Paesi Bassi', name_en: 'Netherlands', source: EUROSTAT, link: '/paesi/NLD', month_to: 7, net_weight_kg: 564_200, comparable: false, previous: null, change_volume_pct: null }),
  ]
  const s: YtdSection = { own: null, status: 'no_monthly', last_month: null, mirror: { declared_flow: 'import', rows, count: 4 } }
  const it = show(<ProfileYtd s={s} flow="export" name="India" today="2026-11-05" />)
  assert.match(it, /Il paese non ha dati mensili propri per il 2026/)
  assert.match(it, /2026 finora secondo i paesi partner/)
  assert.match(it, /Stati Uniti gen–set 2026 70\.280 ▼ −8,0% U\.S\. Census Bureau/)
  assert.match(it, /Paesi Bassi gen–lug 2026 564 senza confronto Eurostat/)
  assert.match(it, /le righe non vengono sommate/)
  assert.match(it, /Altri 2 paesi nei dati/)
})

test('no monthly data: said plainly, the full year follows', () => {
  const none = show(<ProfileYtd s={{ own: null, status: 'no_monthly', last_month: null, mirror: null }} flow="import" name="Cina" today="2026-11-05" />)
  assert.match(none, /Nessun dato doganale mensile per il 2026: sotto, l’ultimo anno completo/)
  const stale = show(<ProfileYtd s={{ own: null, status: 'stale', last_month: '2025-09', mirror: null }} flow="import" name="Francia" today="2026-11-05" />, 'en')
  assert.match(stale, /Latest monthly figure: September 2025, too old for 2026: below, the latest full year/)
})

const prov = { source_url: null, published_at: '2026-07-24', collected_at: null, period_start: '2024-01-01', period_end: null, frequency: 'A', reliability: 'official', is_demo: false }
const FAO = src('faostat', 'FAOSTAT', 'FAOSTAT')
const NASS = src('usda_nass_honey', 'USDA NASS', 'USDA NASS')
const prodSeries = (source: typeof FAO, year: string, value: number, next: { year: number; expected: string; overdue: boolean } | null) => {
  const latest = { ...prov, source, period_label: year, value, unit: 't', flag_raw: null, notes: null, data_status: 'published' }
  return { source, unit: 't', frequency: 'A', points: [latest], latest, is_demo: false, freshness: null, next_release: next }
}
const annual = { ...prov, source: INDEC, period_label: '2025', data_status: 'published', iso3: 'ARG', year: 2025, name_it: 'Argentina', name_en: 'Argentina',
  net_weight_kg: 90_614_000, usd_value: null, value: null, currency: null, value_basis: null, unit_value_usd_per_kg: null, fx_missing: false,
  summed_from_partners: false, summed_from_months: true, partners_count: null, months_count: 12, complete: true, prev: null, yoy_volume_pct: null, yoy_value_pct: null }

function profile(ytd: YtdSection | undefined, series = [prodSeries(FAO, '2024', 69297.65, { year: 2025, expected: '2026-12', overdue: false })]): CountryProfile {
  const flow = (latest: unknown, y?: YtdSection) => ({ available: Boolean(latest), latest, series: [], excluded_partial: [], discrepancies: [], partners: null, mirror: null, ytd: y })
  return {
    production: { available: true, metrics: [{ metric: 'production', series }], providers: [] },
    trade: { export: flow(annual, ytd), import: flow(null), providers: [] },
    news: { available: false, items: [], count_30d: 0, days: 30, link: '/notizie', providers: [] },
  } as unknown as CountryProfile
}

test('headline tiles lead with the year so far; the full year stays below it', () => {
  const it = show(<KpiRow p={profile({ own: fig({}), status: 'ok', last_month: '2026-09', mirror: null })} />)
  assert.match(it, /Esportazioni 93\.811 t 2026 finora \(gen–set\) Provvisorio ▲ 34,2% vs gen–set 2025 Fonte: INDEC Anno 2025: 90\.614 t/)
  const en = show(<KpiRow p={profile({ own: fig({}), status: 'ok', last_month: '2026-09', mirror: null })} />, 'en')
  assert.match(en, /Exports 93,811 t 2026 so far \(Jan–Sep\) Provisional ▲ 34\.2% vs Jan–Sep 2025 Source: INDEC Year 2025: 90,614 t/)
  // no monthly figure: the full year, as before
  const plain = show(<KpiRow p={profile({ own: null, status: 'no_monthly', last_month: null, mirror: null })} />)
  assert.match(plain, /Esportazioni 90\.614 t anno 2025/)
})

test('FAOSTAT 2024 is labelled as the latest FAO year while it is the newest figure', () => {
  const it = show(<KpiRow p={profile(undefined)} />)
  assert.match(it, /69\.298 t anno 2024 ultimo anno FAO \(il 2025 è previsto a dicembre 2026\)/)
  const en = show(<KpiRow p={profile(undefined)} />, 'en')
  assert.match(en, /latest FAO year \(2025 expected in December 2026\)/)
  // a national 2025 figure is newer: shown first, without the FAO note
  const usa = show(<KpiRow p={profile(undefined, [prodSeries(FAO, '2024', 60960, { year: 2025, expected: '2026-12', overdue: false }), prodSeries(NASS, '2025', 52487.9, null)])} />)
  assert.match(usa, /52\.488 t anno 2025/)
  assert.doesNotMatch(usa, /ultimo anno FAO/)
})

test('overview: the year so far comes before the latest full year', () => {
  const side = (flow: 'import' | 'export', rows: YtdFigure[]) => ({ year: 2026, prev_year: 2025, flow, rows, count: rows.length + 3, is_demo: false })
  const annualSide: TradeSide = {
    basis: 'world_rows', items: [{ iso3: 'USA', name: 'Stati Uniti', net_weight_kg: 254_926_000, usd_value: null, unit_value_usd_per_kg: null, prev_net_weight_kg: null, yoy_pct: 27.9, partners_count: null, is_demo: false, data_status: 'published', link: '/paesi/USA' }],
    count: 1, published_at: null, updated_at: null, is_demo: false, data_status: 'published', source_url: null, source: FAO, period_label: '2024',
    prev_period_label: '2023', partial_latest: false, flow: 'import', freshness: { status: 'current', age_days: 10, reference_date: null },
  }
  const block: TradeBlock = {
    available: true, frequency: 'A', importers: annualSide, exporters: null, updated_at: null, sources: [], providers: [], link: '/commercio',
    ytd: {
      importers: side('import', [fig({ iso3: 'USA', name: 'Stati Uniti', link: '/paesi/USA', source: CENSUS, net_weight_kg: 205_841_715, change_volume_pct: 5.99, data_status: 'published' })]),
      exporters: side('export', [fig({ name: 'Argentina', link: '/paesi/ARG' })]),
    },
  }
  const it = show(<TradeHighlights block={block} />)
  assert.match(it, /2026 finora dati doganali mensili · variazione sugli stessi mesi del 2025/)
  assert.match(it, /Stati Uniti gen–set 2026 · US Census Bureau 205\.842 t ▲ \+6,0%/)
  assert.match(it, /Argentina gen–set 2026 · Argentina – INDEC Provvisorio 93\.811 t ▲ \+34,2%/)
  assert.match(it, /non è una classifica tra periodi o fonti diversi/)
  assert.ok(it.indexOf('2026 finora') < it.indexOf('Ultimo anno completo: 2024'), 'year so far first')
  const en = show(<TradeHighlights block={block} />, 'en')
  assert.match(en, /2026 so far monthly customs data · change on the same months of 2025/)
  assert.match(en, /Latest full year: 2024/)
})
