// "Vista: Semplice | Completa" (owner's choice, 6 Nov 2026): a simple view by default, one click to
// the full view (the pages as they were). Same data and provenance, answer first, in plain words.
// Fixtures: overview-simple.json and country-ARG-simple.json are real answers of the application on
// the 5 Nov 2026 database (lists shortened), meta-simple.json its labels.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Route, Routes } from 'react-router-dom'
import { Shell } from '@/components/layout/Shell'
import type { OverviewData } from '@/components/overview/types'
import type { LatestResponse, LatestRow } from '@/components/prices/types'
import { MAIN_ORIGINS, pickPriceRows } from '@/components/simple/pickPrices'
import { pickChanges, SimpleOverview, tilesByOrigin } from '@/components/simple/SimpleOverview'
import { EuropeTable, preferEurostat, SimplePrices } from '@/components/simple/SimplePrices'
import { SourceChip } from '@/components/simple/SourceChip'
import { ViewSwitch } from '@/components/simple/ViewSwitch'
import { I18nProvider } from '@/i18n'
import { setMirrorMode } from '@/lib/mirror'
import { inPeriod, ofPct, packaging, plainPriceLabel, plainText, plainVariety, plainWhere, shortSource, vsPeriod } from '@/lib/plain'
import { DEFAULT_VIEW, readStoredView, storeView, VIEW_STORAGE_KEY, ViewProvider, type View } from '@/lib/view'
import CountryDetail from '@/pages/CountryDetail'
import Overview from '@/pages/Overview'
import country from './fixtures/country-ARG-simple.json'
import meta from './fixtures/meta-simple.json'
import overview from './fixtures/overview-simple.json'
import { hrefs, newQueryClient, render, text } from './helpers'

const OV = overview as unknown as OverviewData
const names: Record<string, string> = { USA: 'Stati Uniti', ITA: 'Italia', ESP: 'Spagna', EU27: 'Unione Europea', ARG: 'Argentina' }
const cn = (iso3: string) => names[iso3] ?? iso3

function withMeta() {
  const qc = newQueryClient()
  qc.setQueryData(['meta'], meta)
  return qc
}

function show(node: ReactNode, { view = 'simple', lang = 'it', url = '/', qc = withMeta() }: { view?: View; lang?: 'it' | 'en'; url?: string; qc?: ReturnType<typeof newQueryClient> } = {}) {
  return render(<ViewProvider initial={view}>{node}</ViewProvider>, { lang, url, qc })
}

/** Run `fn` with a browser storage that holds `stored` (or throws on every access). */
function withStorage<T>(stored: Record<string, string> | 'throws', fn: () => T): T {
  const g = globalThis as { localStorage?: unknown }
  const saved = g.localStorage
  g.localStorage = stored === 'throws'
    ? { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } }
    : { getItem: (k: string) => stored[k] ?? null, setItem: (k: string, v: string) => { stored[k] = v } }
  try {
    return fn()
  } finally {
    g.localStorage = saved
  }
}

// ---------------------------------------------------------------------------------------------
// the switch
// ---------------------------------------------------------------------------------------------
test('the view is simple by default, remembered per browser, and survives blocked storage', () => {
  assert.equal(DEFAULT_VIEW, 'simple')
  assert.equal(withStorage({}, readStoredView), 'simple')
  assert.equal(withStorage({ [VIEW_STORAGE_KEY]: 'full' }, readStoredView), 'full')
  assert.equal(withStorage({ [VIEW_STORAGE_KEY]: 'nonsense' }, readStoredView), 'simple')
  assert.equal(withStorage('throws', readStoredView), 'simple')
  const box: Record<string, string> = {}
  withStorage(box, () => storeView('full'))
  assert.equal(box[VIEW_STORAGE_KEY], 'full')
  assert.doesNotThrow(() => withStorage('throws', () => storeView('simple')))
})

test('the provider reads the remembered view; the header switch says which one is on, in both languages', () => {
  const html = withStorage({ [VIEW_STORAGE_KEY]: 'full', 'paladex.lang': 'it' }, () =>
    renderToStaticMarkup(<I18nProvider><ViewProvider><ViewSwitch /></ViewProvider></I18nProvider>))
  assert.match(html, /data-view-switch="full"/)
  const it = show(<ViewSwitch />)
  assert.match(text(it), /Vista: Semplice Completa/)
  assert.match(it, /aria-pressed="true"[^>]*>Semplice</)
  assert.match(it, /aria-pressed="false"[^>]*>Completa</)
  assert.match(text(show(<ViewSwitch />, { lang: 'en', view: 'full' })), /View: Simple Full/)
})

// ---------------------------------------------------------------------------------------------
// plain words
// ---------------------------------------------------------------------------------------------
test('plain words: price types, places, varieties and packaging, never another figure', () => {
  assert.equal(plainPriceLabel({ price_type: 'import_unit_value', market_iso3: 'USA' }, 'it', cn), 'prezzo medio pagato in dogana (import) negli USA')
  assert.equal(plainPriceLabel({ price_type: 'import_unit_value', market_iso3: 'EU27' }, 'en', cn), 'average price paid at customs (imports) in the EU')
  assert.equal(plainPriceLabel({ price_type: 'export_unit_value', market_iso3: 'ESP' }, 'it', cn), "prezzo medio all'esportazione con destinazione Spagna")
  assert.equal(plainPriceLabel({ price_type: 'producer', market_iso3: 'ITA', origin_iso3: 'ITA' }, 'it', cn), "prezzo pagato all'apicoltore")
  const usda = 'bulk honey, paid to importers, duty paid, containers included, ex-dock or point of entry, per lb as published'
  assert.equal(plainPriceLabel({ price_type: 'wholesale_bulk', market_iso3: 'USA', terms: usda }, 'it', cn), "prezzo all'ingrosso (fusti) negli USA")
  assert.equal(plainPriceLabel({ price_type: 'wholesale_bulk', market_iso3: 'ITA', terms: 'secchio da 25 kg; franco partenza dal magazzino' }, 'it', cn),
    "prezzo all'ingrosso (secchi da 25 kg) in Italia")
  // a list that does not name the packaging gets none
  assert.equal(packaging('prezzi all\'ingrosso; confezione non indicata; IVA esclusa', 'it'), null)
  assert.equal(plainWhere({ price_type: 'wholesale_bulk', market_iso3: 'USA', terms: usda }, 'it', cn), 'venduto negli USA (fusti)')
  assert.equal(plainWhere({ price_type: 'import_unit_value', market_iso3: 'EU27' }, 'it', cn), "importato nell'UE")
  assert.equal(plainVariety('unspecified', 'it', (k) => k), 'tutto il miele')
  assert.equal(plainVariety('unspecified', 'en', (k) => k), 'all honey')
  assert.equal(plainVariety('linden', 'it', () => 'Tiglio'), 'Tiglio')
  // sentences written by the backend (stored or AI summaries): the same replacements
  assert.equal(plainText('Turchia · Non specificata (HS 0409 total) — valore unitario import (dogana): in rialzo', 'it'),
    'Turchia, tutto il miele — prezzo medio pagato in dogana (import): in rialzo')
  assert.equal(plainText('Spain · Not specified (HS 0409 total) — import unit value (customs): up', 'en'),
    'Spain, all honey — average price paid at customs (imports): up')
  assert.equal(ofPct('84,5%', 'it'), "dell'")
  assert.equal(ofPct('3,6%', 'it'), 'del ')
  assert.equal(vsPeriod('2023', 'it'), 'rispetto al 2023')
  assert.equal(vsPeriod('2025-08', 'it'), 'rispetto ad ago 2025')
  assert.equal(inPeriod('2024', 'it'), 'nel 2024')
})

test('short source names, with the full name kept for the details', () => {
  const src = (key: string, publisher: string | null, name = 'x') => ({ key, name, publisher })
  assert.equal(shortSource(src('usda_honey_report', 'USDA Agricultural Marketing Service (AMS), Specialty Crops Market News'), 'it'), 'USDA')
  assert.equal(shortSource(src('ar_official_exports', 'INDEC – Instituto Nacional de Estadística y Censos (Argentina)'), 'it'), 'INDEC (Argentina)')
  assert.equal(shortSource(src('faostat', 'Food and Agriculture Organization of the United Nations (FAO), FAOSTAT'), 'en'), 'FAO')
  assert.equal(shortSource(src('cciaa_cuneo_miele', 'Camera di Commercio di Cuneo'), 'en'), 'Cuneo Chamber of Commerce')
  // an unknown source: its publisher up to the first bracket
  assert.equal(shortSource(src('news_apimondia_x', "Apimondia (International Federation of Beekeepers' Associations)"), 'it'), 'Apimondia')
  assert.equal(shortSource(src('new_source', null, 'Brasile – IBGE PPM: produzione'), 'it'), 'Brasile')
})

// ---------------------------------------------------------------------------------------------
// source chip
// ---------------------------------------------------------------------------------------------
const CHIP = {
  source: { key: 'usda_honey_report', name: 'USDA AMS – National Honey Report (prezzi miele USA)', name_en: 'USDA AMS – National Honey Report (US honey prices)',
    publisher: 'USDA Agricultural Marketing Service (AMS), Specialty Crops Market News', reliability: 'official', homepage: null },
  period_label: '2026-09', published_at: '2026-10-30', collected_at: '2026-11-05T18:00:00', source_url: 'https://example.org/report.pdf',
  data_status: 'provisional', is_demo: false, technical: "Prezzo all'ingrosso (sfuso) · Millefiori · Bianco · 1,77 USD/lb",
}

test('the source chip is short when closed and opens to the full provenance', () => {
  const closed = show(<SourceChip p={CHIP} />)
  assert.match(text(closed), /^Fonte: USDA · set 2026 Provvisorio$/)
  assert.match(closed, /aria-expanded="false"/)
  assert.doesNotMatch(text(closed), /Agricultural Marketing Service|Pubblicato|1,77 USD\/lb/)
  const open = text(show(<SourceChip p={CHIP} defaultOpen actions={<button type="button">Segnala o correggi</button>} />))
  assert.match(open, /Fonte USDA Agricultural Marketing Service \(AMS\), Specialty Crops Market News USDA AMS – National Honey Report \(prezzi miele USA\)/)
  assert.match(open, /Periodo set 2026/)
  assert.match(open, /Pubblicato 30 ott 2026/)
  assert.match(open, /Raccolto .* \(05 nov 2026\)/)
  assert.match(open, /Dato tecnico Prezzo all'ingrosso \(sfuso\) · Millefiori · Bianco · 1,77 USD\/lb/)
  assert.match(open, /Documento originale/)
  assert.match(open, /Segnala o correggi/)         // room for actions on the figure
  assert.match(show(<SourceChip p={CHIP} defaultOpen />), /aria-expanded="true"/)
  assert.match(text(show(<SourceChip p={CHIP} />, { lang: 'en' })), /^Source: USDA · Sept? 2026/)
})

// ---------------------------------------------------------------------------------------------
// Panoramica
// ---------------------------------------------------------------------------------------------
test('simple Panoramica: four cards in plain words, each figure with its source chip', () => {
  const out = text(show(<SimpleOverview d={OV} />))
  // 1. prices: one per origin, euro per kilo, the price type in plain words
  assert.match(out, /Prezzi del miele/)
  assert.match(out, /Argentina prezzo all'ingrosso \(fusti\) negli USA · millefiori, bianco 3,40 €\/kg/)
  assert.equal((out.match(/Argentina prezzo all'ingrosso/g) ?? []).length, 1)   // three ARG tiles -> one row
  assert.match(out, /Fonte: USDA · set 2026/)
  // old figures are named with their date, never shown as current
  assert.match(out, /Ultimi prezzi disponibili, ma non recenti Ucraina .* Dato di gen 2025: non recente/)
  // 2. the year so far
  assert.match(out, /2026 finora/)
  assert.match(out, /Chi esporta di più Argentina ?: 93\.811 tonnellate esportate da gennaio a settembre ▲ \+34,2% rispetto agli stessi mesi del 2025/)
  assert.match(out, /Fonte: INDEC \(Argentina\) · gen–set 2026 Provvisorio/)
  assert.match(out, /Chi importa di più Stati Uniti ?: 205\.842 tonnellate importate da gennaio a settembre .*Regno Unito ?: 45\.022 tonnellate importate da gennaio ad agosto/)
  // 3. the changes, rewritten from the figures of each sentence
  assert.match(out, /1 Italia, tiglio: il prezzo all'ingrosso \(secchi da 25 kg\) in Italia è sceso del 3,6% in un mese, a 5,30 €\/kg \(set 2026\)\./)
  assert.match(out, /2 Stati Uniti, tutto il miele importato nel 2024: 254\.926 tonnellate \(\+27,9% rispetto al 2023\)\./)
  assert.match(out, /3 Nuovo report ufficiale: «Report annuale ONM - stagione 2025»\./)
  assert.doesNotMatch(out, /HS 0409 total|valore unitario|Non specificata/)
  // 4. headlines
  assert.match(out, /Notizie .*Brazil, More Beehives to Mitigate El Niño Effects .*Apimondia · 29 ottobre 2026/)
  // data status: one line, because a source is late
  assert.match(out, /Attenzione: 1 fonte è in ritardo, 1 controllo di qualità grave da verificare\. .* Vedi Fonti/)
  assert.doesNotMatch(out, /aggiornate|segnalazioni aperte|Stato dei dati/)
})

test('simple Panoramica: no status line when every source is fine; English sentences', () => {
  const ok: OverviewData = { ...OV, status: { ...OV.status, counts: { ...OV.status.counts, stale: 0, aging: 0, failed: 0 } }, quality: { ...OV.quality, by_severity: {} } }
  assert.doesNotMatch(text(show(<SimpleOverview d={ok} />)), /Attenzione|Vedi Fonti/)
  const en = text(show(<SimpleOverview d={OV} />, { lang: 'en' }))
  assert.match(en, /United States, all honey imported in 2024: 254,926 tonnes \(\+27\.9% compared with 2023\)\./)
  assert.match(en, /Who exports most Argentina ?: 93,811 tonnes exported from January to September ▲ \+34\.2% vs the same months of 2025/)
})

test('the three changes mix prices, trade and reports; one series per origin on the price card', () => {
  const kinds = pickChanges(OV.briefing.bullets).map((b) => b.kind)
  assert.deepEqual(kinds, ['price', 'trade', 'report'])
  assert.deepEqual(pickChanges(OV.briefing.bullets.filter((b) => b.kind === 'price')).map((b) => b.kind), ['price', 'price', 'price'])
  assert.deepEqual(tilesByOrigin(OV.prices.items).map((x) => x.origin_iso3), ['ARG', 'UKR', 'BRA', 'VNM', 'IND', 'ITA'])
})

test('the Panoramica page shows the simple cards in the simple view and today\'s page in the full view', () => {
  const qc = withMeta()
  qc.setQueryData(['overview', 'it'], OV)
  const simple = text(show(<Overview />, { qc }))
  assert.match(simple, /Prezzi del miele .* 2026 finora .* Cosa è cambiato .* Notizie/)
  assert.doesNotMatch(simple, /Stato dei dati/)
  const full = text(show(<Overview />, { qc, view: 'full' }))
  assert.match(full, /Stato dei dati/)
  assert.match(full, /42 aggiornate/)
})

// ---------------------------------------------------------------------------------------------
// Prezzi
// ---------------------------------------------------------------------------------------------
function row(over: Partial<LatestRow> & { value?: number; period?: string; end?: string }): LatestRow {
  const { value = 2.5, period = '2026-08', end = '2026-08-31', ...rest } = over
  const point = { period_label: period, period_start: `${period}-01`, period_end: end, value, low: null, high: null, original: { value: value * 1.15, low: null, high: null, currency: 'USD', unit: 'kg' },
    n_points: 1, expected_points: null, periods: [period], fx_missing: 0, published_at: '2026-10-16', collected_at: '2026-11-05T10:00:00', source_url: null, fx_date: null, data_status: 'published', is_demo: false }
  return {
    series_id: `${rest.origin_iso3}-${rest.market_iso3}-${period}-${rest.color_grade ?? ''}`, source: { key: 'eurostat_comext', name: 'Eurostat Comext', publisher: 'Eurostat (European Commission)', reliability: 'official', homepage: null },
    price_type: 'import_unit_value', origin_iso3: 'ARG', origin_label: null, market_iso3: 'EU27', market_location: null, variety: 'unspecified', variety_raw: [],
    color_grade: null, terms: 'CIF', organic: false, currency: 'EUR', unit: 'kg', native_frequency: 'M', freq: 'M', reliability: 'official', is_demo: false,
    latest: point, period_label: period, published_at: '2026-10-16', collected_at: '2026-11-05T10:00:00', source_url: null, data_status: 'published',
    previous: { period_label: '2026-07', value: 2.31, n_points: 1, published_at: null }, year_ago: { period_label: '2025-08', value: 1.99, n_points: 1, published_at: null },
    change_prev_pct: 8.28, change_yoy_pct: 25.75, freshness: { status: 'current', age_days: 20, reference_date: '2026-10-16', expected_max_age_days: 60, basis: 'source' }, is_stale: false,
    ...rest,
  } as LatestRow
}

test('one series per main origin: current and monthly first, with comparisons, in the market that matters', () => {
  const rows = [
    row({ origin_iso3: 'ARG', market_iso3: 'DEU' }),
    row({ origin_iso3: 'ARG', market_iso3: 'EU27' }),
    row({ origin_iso3: 'ARG', market_iso3: 'USA', previous: null, year_ago: null, change_prev_pct: null, change_yoy_pct: null }),
    row({ origin_iso3: 'ARG', market_iso3: 'ITA', freq: 'A', period: '2025', end: '2025-12-31' }),
    row({ origin_iso3: 'UKR', market_iso3: 'EU27', period: '2025-01', end: '2025-01-31', freshness: { status: 'stale', age_days: 600, reference_date: null, expected_max_age_days: 60, basis: 'source' } }),
    row({ origin_iso3: 'CHN', market_iso3: 'USA' }),
    row({ origin_iso3: 'XXX', market_iso3: 'EU27' }),           // not a main origin
  ]
  const p = pickPriceRows(rows, '2026-11-06')
  assert.deepEqual(p.rows.map((r) => `${r.origin_iso3}>${r.market_iso3}`), ['ARG>EU27', 'CHN>USA'])
  assert.deepEqual(p.old.map((r) => r.origin_iso3), ['UKR'])
  // an annual FAOSTAT price of 2014 is old whatever its source's freshness says
  const fao = row({ origin_iso3: 'BRA', price_type: 'producer', market_iso3: 'BRA', freq: 'A', period: '2014', end: '2014-12-31' })
  assert.deepEqual(pickPriceRows([fao], '2026-11-06').old.map((r) => r.period_label), ['2014'])
  assert.ok(MAIN_ORIGINS.includes('ARG') && MAIN_ORIGINS.length <= 12)
})

test('simple Prezzi: a short table per price type, euro by default, every row with its source chip', () => {
  const qc = withMeta()
  qc.setQueryData(['prices', 'facets', 'all'], { price_types: [{ key: 'import_unit_value', count: 10 }, { key: 'retail', count: 0 }] })
  const latest: LatestResponse = { price_type: 'import_unit_value', currency: 'EUR', freq: 'M', today: '2026-11-06', rows: [
    row({ origin_iso3: 'ARG', market_iso3: 'EU27' }),
    row({ origin_iso3: 'UKR', market_iso3: 'EU27', period: '2025-01', end: '2025-01-31', freshness: { status: 'stale', age_days: 600, reference_date: null, expected_max_age_days: 60, basis: 'source' } }),
  ] }
  qc.setQueryData(['prices', 'simple-latest', 'import_unit_value', 'EUR'], latest)
  const html = show(<SimplePrices details={<p>DETAILS</p>} />, { qc, url: '/prezzi?valuta=EUR' })
  const out = text(html)
  assert.match(out, /Prezzi in €\/kg \$\/kg/)
  assert.match(out, /Prezzi medi pagati in dogana \(import\)/)
  assert.match(out, /Origine Ultimo prezzo Un mese prima Un anno prima Andamento/)
  assert.match(out, /Argentina importato nell'UE · tutto il miele Ultimo prezzo: 2,50 €\/kg ago 2026 ▲ \+8,3% in un mese Un mese prima: 2,31 €\/kg lug 2026 Un anno prima: 1,99 €\/kg ago 2025/)
  assert.match(out, /Fonte: Eurostat · ago 2026/)
  assert.match(out, /Ultimo dato non recente per: Ucraina \(gen 2025\)/)
  assert.doesNotMatch(out, /Al dettaglio|Prezzi al consumatore/)     // a type without data has no table
  assert.match(out, /DETAILS/)
  assert.match(text(show(<SimplePrices details={null} />, { qc, url: '/prezzi?valuta=EUR', lang: 'en' })), /A month before: 2\.31 €\/kg/)
})

// ---------------------------------------------------------------------------------------------
// country page
// ---------------------------------------------------------------------------------------------
function countryPage(view: View) {
  const qc = withMeta()
  qc.setQueryData(['countries', 'ARG'], country)
  return text(show(<Routes><Route path="/paesi/:iso3" element={<CountryDetail />} /></Routes>, { qc, url: '/paesi/ARG', view }))
}

test('simple country page: everything about the country on one page, with an index to jump to a section', () => {
  // owner, 15 Nov 2026: "when I click on Italy or Vietnam I want to see EVERYTHING related to that
  // country, also the business": nothing is behind "Mostra dettagli" any more
  const out = countryPage('simple')
  assert.match(out, /Argentina/)
  assert.match(out, /Produzione 69\.298 t anno 2024/)
  assert.match(out, /Vai a: Prezzi Aziende Commercio Produzione Notizie Normative e dazi/)
  assert.match(out, /Commercio dell’anno in corso 2026 finora Esportazioni 2026 finora \(gen–set\)/)
  assert.match(out, /93\.811 t/)
  assert.match(out, /Altre fonti \(non ufficiali\)/)
  assert.doesNotMatch(out, /Mostra dettagli/)
  // the sections that used to be hidden are on the page, in this order
  const at = (re: RegExp) => { const i = out.search(re); assert.ok(i >= 0, String(re)); return i }
  const order = [at(/Vai a:/), at(/Prezzi del miele/), at(/Commercio dell’anno in corso/), at(/Statistiche di produzione/),
    at(/Altre fonti \(non ufficiali\)/), out.lastIndexOf('Normative')]      // the panel, not the index entry
  assert.deepEqual(order, [...order].sort((a, b) => a - b))
  const full = countryPage('full')
  assert.match(full, /Dati non disponibili/)
  assert.doesNotMatch(full, /Mostra dettagli|Vai a:/)
})

// ---------------------------------------------------------------------------------------------
// menu and phone copy
// ---------------------------------------------------------------------------------------------
test('simple menu: the five main entries, then "Altro" (open when the page is one of its entries)', () => {
  const html = show(<Shell><p>page</p></Shell>, { url: '/' })
  const links = hrefs(html).filter((h) => h.startsWith('/') && !h.startsWith('/cerca'))
  assert.deepEqual(links.slice(0, 5), ['/', '/prezzi', '/paesi', '/notizie', '/offerte'])
  assert.match(text(html), /Altro/)
  assert.match(html, /aria-expanded="false" aria-controls="menu-more"/)
  for (const r of ['/commercio', '/aziende', '/normative', '/fonti']) assert.ok(!hrefs(html).includes(r), r)
  const inside = show(<Shell><p>page</p></Shell>, { url: '/commercio' })
  assert.match(inside, /aria-expanded="true" aria-controls="menu-more"/)
  for (const r of ['/commercio', '/aziende', '/raccolti', '/normative', '/avvisi', '/archivio', '/assistente', '/fonti']) assert.ok(hrefs(inside).includes(r), r)
  // the full view keeps today's menu, with its sections
  const full = text(show(<Shell><p>page</p></Shell>, { url: '/', view: 'full' }))
  assert.match(full, /Mercato .* Azienda .* Sistema/)
  assert.doesNotMatch(full, /Altro/)
  // the switch is in the header (and in a row under it on a computer's narrow window)
  assert.equal((html.match(/data-view-switch="simple"/g) ?? []).length, 2)
})

test('phone copy: the switch is in its header, the menu groups only what the copy contains', () => {
  setMirrorMode(true)
  try {
    const html = show(<Shell><p>page</p></Shell>, { url: '/commercio' })
    assert.equal((html.match(/data-view-switch="simple"/g) ?? []).length, 1)
    assert.match(text(html), /Semplice Completa/)
    const links = hrefs(html)
    assert.deepEqual(links.filter((h) => ['/', '/prezzi', '/paesi', '/notizie'].includes(h)), ['/', '/prezzi', '/paesi', '/notizie'])
    for (const r of ['/offerte', '/avvisi', '/archivio', '/assistente']) assert.ok(!links.includes(r), r)
    for (const r of ['/commercio', '/aziende', '/raccolti', '/normative', '/fonti']) assert.ok(links.includes(r), r)
  } finally {
    setMirrorMode(null)
  }
})

// ---------------------------------------------------------------------------------------------
// comparisons over a gap in the source (coordinator's review, 6 Nov 2026): USDA published no report
// between Sep 2025 and Aug 2026, so the Sep 2026 prices have neither the month nor the year before.
// ---------------------------------------------------------------------------------------------
test('simple Prezzi: a missing month says why, and the latest earlier figure keeps its own date', () => {
  const qc = withMeta()
  qc.setQueryData(['prices', 'facets', 'all'], { price_types: [{ key: 'wholesale_bulk', count: 10 }] })
  const usda = row({
    origin_iso3: 'ARG', market_iso3: 'USA', price_type: 'wholesale_bulk', variety: 'polyflora', color_grade: 'white',
    terms: 'bulk honey, paid to importers, duty paid, containers included', period: '2026-09', end: '2026-09-30', value: 3.42,
    previous: null, year_ago: null, change_prev_pct: null, change_yoy_pct: null,
    earlier: { period_label: '2025-08', value: 2.82, n_points: 1, published_at: '2025-09-30' }, change_earlier_pct: 21.44,
    missing: { previous: { period_label: '2026-08', source_has_period: false }, year_ago: { period_label: '2025-09', source_has_period: false } },
  })
  const cuneo = row({
    origin_iso3: 'ITA', market_iso3: 'ITA', price_type: 'wholesale_bulk', variety: 'polyflora', terms: 'fusto da 3 q.li',
    period: '2026-09', end: '2026-09-30', value: 5.0, previous: { period_label: '2026-08', value: 5.15, n_points: 1, published_at: null },
    year_ago: { period_label: '2025-09', value: 5.8, n_points: 1, published_at: null }, change_prev_pct: -2.91, change_yoy_pct: -13.79,
    earlier: { period_label: '2026-08', value: 5.15, n_points: 1, published_at: null }, change_earlier_pct: -2.91,
    missing: { previous: null, year_ago: null },
  })
  qc.setQueryData(['prices', 'simple-latest', 'wholesale_bulk', 'EUR'], { price_type: 'wholesale_bulk', currency: 'EUR', freq: 'M', today: '2026-11-06', rows: [usda, cuneo] })
  const out = text(show(<SimplePrices details={null} />, { qc, url: '/prezzi?valuta=EUR' }))
  assert.match(out, /Argentina venduto negli USA \(fusti\) · millefiori, bianco Ultimo prezzo: 3,42 €\/kg set 2026 ▲ \+21,4% rispetto ad ago 2025 Un mese prima: 2,82 €\/kg dato di ago 2025 \(il più recente prima\) nessun dato della fonte per ago 2026 Un anno prima: — nessun dato della fonte per set 2025/)
  // exact comparisons are unchanged
  assert.match(out, /Italia venduto in Italia \(fusti\) · millefiori Ultimo prezzo: 5,00 €\/kg set 2026 ▼ −2,9% in un mese Un mese prima: 5,15 €\/kg ago 2026 Un anno prima: 5,80 €\/kg set 2025/)
  assert.doesNotMatch(out, /nessun confronto/)
  const en = text(show(<SimplePrices details={null} />, { qc, url: '/prezzi?valuta=EUR', lang: 'en' }))
  assert.match(en, /figure for Aug 2025 \(the latest before\) no data from the source for Aug 2026/)
})

test('Panoramica prices: a gap in the source is named, the change against the latest earlier figure carries its date', () => {
  const tiles = OV.prices.items.map((x) => (x.origin_iso3 === 'ARG' && x.color_grade === 'white' ? {
    ...x, earlier_pct: 19.53, earlier_period_label: '2025-08',
    mom_missing: { period_label: '2026-08', source_has_period: false }, yoy_missing: { period_label: '2025-09', source_has_period: false },
  } : x))
  const out = text(show(<SimpleOverview d={{ ...OV, prices: { ...OV.prices, items: tiles } }} />))
  assert.match(out, /Argentina .* 3,40 €\/kg ▲ \+19,5% rispetto ad ago 2025 \(prezzo in USD\) · nessun dato della fonte per ago 2026 e set 2025/)
})

// --- 11 Nov 2026: every European country with its price (owner: "all European countries should have their prices listed")
test('Europe, country by country: one yearly producer price per country, Eurostat before FAO, and who publishes none', () => {
  const EUROSTAT = { key: 'eurostat_honey_prices', name: 'Eurostat: prezzo di vendita del miele', publisher: 'Eurostat (European Commission)', reliability: 'official', homepage: null }
  const FAO = { key: 'faostat', name: 'FAOSTAT', publisher: 'Food and Agriculture Organization of the United Nations (FAO)', reliability: 'official', homepage: null }
  const yearly = (iso3: string, period: string, value: number, source: typeof FAO, more: Partial<LatestRow> = {}) => row({
    origin_iso3: iso3, market_iso3: iso3, price_type: 'producer', freq: 'A', native_frequency: 'A', period, end: `${period}-12-31`, value, source, terms: null,
    previous: null, change_prev_pct: null, year_ago: { period_label: String(Number(period) - 1), value: 13.73, n_points: 1, published_at: null }, change_yoy_pct: 10.2, ...more })
  const rows = [
    yearly('DEU', '2024', 15.13, FAO), yearly('DEU', '2024', 15.1341, EUROSTAT),     // the same figure twice: Eurostat's is shown
    yearly('ESP', '2023', 4.2, EUROSTAT), yearly('ESP', '2024', 4.4, FAO),          // FAO newer: FAO's is shown
    yearly('HUN', '2008', 2.58, EUROSTAT),                                          // stopped reporting: named as old
  ]
  assert.deepEqual(preferEurostat(rows).map((r) => `${r.origin_iso3} ${r.period_label} ${r.source?.key}`),
    ['DEU 2024 eurostat_honey_prices', 'ESP 2023 eurostat_honey_prices', 'ESP 2024 faostat', 'HUN 2008 eurostat_honey_prices'])
  const qc = withMeta()
  qc.setQueryData(['prices', 'simple-europe', 'EUR', 7], { price_type: 'producer', currency: 'EUR', freq: 'A', today: '2026-11-11', rows })
  const html = show(<EuropeTable ccy="EUR" />, { qc })
  const out = text(html)
  assert.match(out, /^Europa, paese per paese Il prezzo a cui gli apicoltori di ogni paese hanno venduto il miele: media dell’anno, dalle statistiche ufficiali\. Non è un prezzo all’ingrosso in fusti/)
  assert.match(out, /Paese Ultimo prezzo Un anno prima Andamento Germania tutto il miele Ultimo prezzo: 15,13 €\/kg .*2024 ▲ \+10,2% in un anno/)
  assert.match(out, /Fonte: Eurostat · 2024/)
  assert.ok(out.indexOf('Germania') < out.indexOf('Spagna'))                       // by name
  assert.match(out, /Spagna tutto il miele Ultimo prezzo: 4,40 €\/kg/)
  assert.match(out, /Ultimo dato non recente per: Ungheria \(2008\)\./)
  assert.match(out, /Nessun prezzo pubblicato dalle fonti che Paladex legge per: Francia, Italia, Regno Unito, Ucraina\./)
  assert.equal((html.match(/data-simple-price=/g) ?? []).length, 2)
  assert.match(text(show(<EuropeTable ccy="EUR" />, { qc, lang: 'en' })), /^Europe, country by country .* No price published by the sources Paladex reads for: France, Italy, Ukraine, United Kingdom\./)
})
