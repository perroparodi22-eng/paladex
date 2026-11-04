// /raccolti (Milestone 5): weather by honey region with rule-based signals (automatic assessments,
// labelled as such and never mixed with data), production by country, reports, the empty / collecting
// states, URL-kept view state, and both languages.
// tests/fixtures/harvest-weather.json is the real /api/harvest/weather answer of 4 Nov 2026 (database
// copy after the live NASA POWER run), trimmed to 4 regions: Buenos Aires, Hungary, Sicily, Extremadura.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fmtAnomaly, fmtFlagValues, fmtMonthRun, fmtPctOfNormal, monthSpan } from '@/components/harvest/format'
import { MapPanel } from '@/components/harvest/MapPanel'
import { ReadingGuide, WeatherAttribution, WeatherStatusNote } from '@/components/harvest/parts'
import { ProductionTable } from '@/components/harvest/ProductionPanel'
import { RegionBody } from '@/components/harvest/RegionDetail'
import { readable, ReportsBody } from '@/components/harvest/ReportsPanel'
import { RulesPanel } from '@/components/harvest/RulesPanel'
import { SignalsSummary } from '@/components/harvest/SignalsSummary'
import type { ProductionResponse, RegionMonth, ReportsResponse, WeatherResponse } from '@/components/harvest/types'
import { patchHarvestParams, readHarvestParams } from '@/components/harvest/useHarvestParams'
import { WeatherTable } from '@/components/harvest/WeatherTable'
import realWeather from './fixtures/harvest-weather.json'
import { hrefs, render, text } from './helpers'

const W = realWeather as unknown as WeatherResponse
const noop = () => {}

test('the weather table shows the last 3 months and explains each automatic signal in plain words', () => {
  const html = render(<WeatherTable data={W} country="" signal="" selected="" onSignal={noop} onSelect={noop} />)
  const s = text(html)
  // grouped by country, the three recent months as columns
  for (const c of ['Argentina', 'Ungheria', 'Italia', 'Spagna']) assert.match(s, new RegExp(c))
  assert.match(s, /ago 2026.*set 2026.*ott 2026/)
  // Hungary, August 2026: +4,7 °C and 13% of normal rainfall (real NASA POWER values)
  assert.match(s, /\+4,7 °C/)
  assert.match(s, /13%/)
  // the explanation of the signal, with its months and values
  assert.match(s, /Siccità da monitorare \(negli ultimi 3 mesi\) Pioggia al 12%, 50%, 49%, 30% e 13% della normale in apr–ago 2026, mesi di fioritura\./)
  assert.match(s, /Stress da caldo \(prima, negli ultimi 12 mesi\) Temperatura \+4,2 °C e \+2,1 °C rispetto alla normale in giu–lug 2026/)
  // October is provisional (quick-look daily data), flagged as such
  assert.match(html, /title="Provvisorio: calcolato dai dati giornalieri rapidi/)
  // Sicily, February 2026: the exceptional value is kept but marked "to verify"
  assert.match(s, /Valore eccezionale in feb 2026 \(oltre 5 volte la normale e oltre 300 mm\): da verificare/)
  // curated flowering months are labelled as context
  assert.match(s, /ott–mar contesto/)
})

test('the signal and country filters narrow the table', () => {
  const heat = text(render(<WeatherTable data={W} country="" signal="heat_stress" selected="" onSignal={noop} onSelect={noop} />))
  assert.match(heat, /Ungheria/)
  assert.match(heat, /Estremadura/)
  assert.doesNotMatch(heat, /Buenos Aires/)
  const esp = text(render(<WeatherTable data={W} country="ESP" signal="" selected="" onSignal={noop} onSelect={noop} />))
  assert.match(esp, /Estremadura/)
  assert.doesNotMatch(esp, /Ungheria/)
  const none = text(render(<WeatherTable data={W} country="ARG" signal="wet_season" selected="" onSignal={noop} onSelect={noop} />))
  assert.match(none, /Nessuna regione corrisponde ai filtri scelti/)
})

test('the table scrolls inside its card on a phone (no page overflow)', () => {
  const html = render(<WeatherTable data={W} country="" signal="" selected="" onSignal={noop} onSelect={noop} />)
  assert.match(html, /<div class="overflow-x-auto"><table class="w-full min-w-\[820px\]/)
  assert.match(html, /sticky left-0/)            // the region column stays visible while scrolling
})

test('automatic signals are always labelled as assessments, with their rules shown', () => {
  const rules = text(render(<RulesPanel meta={W} />))
  assert.match(rules, /Valutazione automatica \(regole\), non dati confermati/i)
  assert.match(rules, /Soglia < 60% · Mesi consecutivi ≥ 2/)
  assert.match(rules, /Soglia ≥ 2,0 °C/)
  assert.match(rules, /Soglia > 160%/)
  assert.match(rules, /oltre 5 volte la sua pioggia normale e oltre 300 mm/)
  const summary = text(render(<SignalsSummary data={W} onSelect={noop} onSignal={noop} />))
  assert.match(summary, /non dati confermati/i)
  assert.match(summary, /Siccità da monitorare 3 regioni · 1 negli ultimi 3 mesi/)
  // it follows the page's country filter
  const spain = text(render(<SignalsSummary data={W} country="ESP" onSelect={noop} onSignal={noop} />))
  assert.match(spain, /Segnali automatici in sintesi · Spagna/)
  assert.match(spain, /Siccità da monitorare 1 regione/)
  assert.match(spain, /Nessun segnale negli ultimi 3 mesi/)
  // the map panel (Leaflet needs a browser) still renders its legend and the assessment label on the server
  const map = text(render(<MapPanel data={W} visible={new Set()} selected="" onSelect={noop} />))
  assert.match(map, /Valutazione automatica/)
  assert.match(map, /Pieno: segnale negli ultimi 3 mesi/)
})

test('before the first weather collection the page says so plainly; production stays available', () => {
  const empty = { ...W, available: false, regions: W.regions.map((r) => ({ ...r, has_data: false, recent: [], flags: [], condition: 'no_data' as const })) }
  const never = text(render(<WeatherStatusNote meta={{ ...empty, collection: { state: 'never', last_run_at: null, last_run_status: null, enabled: true } }} regionsWithData={0} regionsTotal={64} />))
  assert.match(never, /Dati meteo in fase di raccolta/)
  assert.match(never, /non sono ancora stati raccolti/)
  assert.match(never, /I dati di produzione qui sotto sono già disponibili/)
  const running = text(render(<WeatherStatusNote meta={{ ...empty, collection: { state: 'running', last_run_at: null, last_run_status: null, enabled: true } }} regionsWithData={0} regionsTotal={64} />))
  assert.match(running, /in corso: le regioni compaiono man mano/)
  const partial = text(render(<WeatherStatusNote meta={{ ...W, collection: { state: 'running', last_run_at: null, last_run_status: null, enabled: true } }} regionsWithData={20} regionsTotal={64} />))
  assert.match(partial, /20 regioni su 64 hanno già i dati meteo/)
  const en = text(render(<WeatherStatusNote meta={{ ...empty, collection: { state: 'offline', last_run_at: '2026-11-04T08:00:00', last_run_status: 'offline', enabled: true } }} regionsWithData={0} regionsTotal={64} />, { lang: 'en' }))
  assert.match(en, /Weather data being collected/)
  assert.match(en, /this computer was offline/)
  assert.match(en, /The production data below are already available/)
})

test('the NASA POWER citation and access date are shown with the weather data', () => {
  const s = text(render(<WeatherAttribution meta={W} />))
  assert.match(s, /NASA Langley Research Center/)
  assert.match(s, /v2\.10\.0, v2\.10\.2/)
  assert.match(s, /consultato il 04 nov 2026/)
  assert.match(s, /Prediction Of Worldwide Energy Resources \(POWER\) project funded through the NASA Earth Science Division/)
})

test('region detail: 12 months, every value one click from its exact NASA query, context labelled', () => {
  const hun = W.regions.find((r) => r.key === 'HUN')!
  const months: RegionMonth[] = hun.recent.map((m) => ({
    ...m,
    points: hun.points.map((p) => ({
      exceptional: false, point: p.key, name: p.name, temp_mean_c: 27.8, temp_anomaly_c: m.temp_anomaly_c, precip_mm: 7,
      precip_anomaly_pct: m.precip_pct, normal_temp_c: 22.9, normal_precip_mm: 56, basis: m.data_status === 'provisional' ? 'daily' : 'monthly',
      nasa_sources: ['MERRA2'], data_status: m.data_status ?? 'published', collected_at: null, last_seen_at: null, revision: 1,
      source_url: `https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=T2M%2CPRECTOTCORR&community=AG&longitude=${p.lon}&latitude=${p.lat}&start=1991&end=2026&format=JSON`,
    })),
  }))
  const html = render(<RegionBody r={{ ...hun, months }} />)
  const s = text(html)
  const nasa = hrefs(html).filter((h) => h.startsWith('https://power.larc.nasa.gov/api/temporal/'))
  assert.equal(nasa.length, 3 * hun.points.length)
  assert.match(s, /1 Kecskemét \(46,91, 19,69\)/)
  assert.match(s, /Contesto \(non dati raccolti\)/)
  assert.match(s, /Provvisorio/)
  assert.match(s, /Definitivo/)
})

test('production table: latest year, change on the year before, the status the source gives', () => {
  const v = (year: number, value: number, status: string, flag: string) => ({
    period_label: String(year), year, value, unit: 't', flag_raw: flag, notes: `FAOSTAT QCL: Natural honey production; flag ${flag}`,
    source_url: 'https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip',
    published_at: '2025-12-31', collected_at: '2026-11-04T20:55:17', data_status: status, is_demo: false,
  })
  const fao = { key: 'faostat', name: 'FAOSTAT', publisher: 'FAO', reliability: 'official', homepage: null }
  const data = {
    available: true, scope: 'monitored', monitored: ['ARG', 'HUN'], countries_with_data: 137, monitored_with_data: 24, years: [2020, 2024],
    sources: [], providers: [], data_status: 'estimate', generated_at: '2026-11-04T23:30:00',
    countries: [
      { iso3: 'ARG', name_it: 'Argentina', name_en: 'Argentina', monitored: true, regions: ['ARG-BA'], primary_t: 69297.6, primary_year: 2024, is_demo: false,
        series: [{ source: fao, unit: 't', reliability: 'official', frequency: 'A', latest: v(2024, 69297.65, 'estimate', 'E'), previous: v(2023, 69701.22, 'estimate', 'E'),
          change_pct: -0.6, forecast: null, latest_t: 69297.6, years: 34 }] },
      { iso3: 'HUN', name_it: 'Ungheria', name_en: 'Hungary', monitored: true, regions: ['HUN'], primary_t: 14000, primary_year: 2020, is_demo: false,
        series: [{ source: fao, unit: 't', reliability: 'official', frequency: 'A', latest: v(2020, 14000, 'published', 'A'), previous: v(2019, 18000, 'published', 'A'),
          change_pct: -22.2, forecast: { ...v(2025, 15000, 'forecast', ''), flag_raw: null }, latest_t: 14000, years: 30 }] },
    ],
  } as unknown as ProductionResponse
  const html = render(<ProductionTable data={data} selected="ARG" onSelect={noop} scope="monitored" onScope={noop} />)
  const s = text(html)
  assert.match(s, /Argentina 2024 69\.298 t/)
  assert.match(s, /−0,6%/)
  assert.match(s, /Stima · E/)
  assert.match(s, /Ungheria 2020 14\.000 t/)        // an old year is shown as such, never as current
  assert.match(s, /Dato ufficiale · A/)
  assert.match(s, /Previsione ufficiale 2025: 15\.000 t/)
  assert.match(s, /Paesi monitorati \(24\)/)
  assert.match(s, /Tutti i paesi \(137\)/)
  assert.match(s, /l'ultimo anno pubblicato qui è il 2024/)
  assert.ok(hrefs(html).some((h) => h.startsWith('https://bulks-faostat.fao.org/')))
  assert.match(html, /overflow-x-auto/)
})

test('reports and news: AI output labelled, unreadable PDF table text not shown as an excerpt', () => {
  const src = (key: string, name: string, reliability: string) => ({ key, name, publisher: name, reliability, homepage: null })
  const data = {
    reports: [
      { id: 1, report_key: '2026-09', title: 'Settembre 2026 – Rilevazione mensile', period_label: '2026-09', published_at: '2026-10-20', collected_at: null,
        source: src('onm_informamiele', 'Osservatorio Nazionale Miele', 'industry'), source_url: 'https://www.informamiele.it/settembre-2026-rilevazione-mensile/',
        reliability: 'industry', data_status: 'published', is_demo: false, summary_it: null, summary_en: null, summary_is_ai: false, has_narrative: true,
        narrative_excerpt: "Le transazioni rilevate nel mese di settembre sul mercato del miele all'ingrosso riguardano principalmente scambi di piccole partite" },
      { id: 2, report_key: '2026-01', title: 'Honey market overview (January 2026)', period_label: '2026-01', published_at: '2026-01-29', collected_at: null,
        source: src('ec_honey_market', 'European Commission', 'official'), source_url: 'https://agriculture.ec.europa.eu/x.pdf', reliability: 'official',
        data_status: 'published', is_demo: false, summary_it: null, summary_en: null, summary_is_ai: false, has_narrative: true,
        narrative_excerpt: 'Honey Market Presentation Number (in thousand) and share of beehives per MS 2 S o E S P L R O E L IT F R H U D E B G P T C Z A T H R S K' },
    ],
    news: [
      { id: 7, title: 'Brazil, More Beehives to Mitigate El Niño Effects', title_it: 'Brasile, più alveari contro gli effetti di El Niño', title_en: null,
        language: 'en', publisher: 'Apimondia', url: 'https://www.apimondia.org/x', published_at: '2026-10-29T21:17:11', collected_at: null, snippet: null,
        summary_it: null, summary_en: null, ai_model: 'model-x', countries: ['BRA'], topics: ['production', 'weather'], harvest_topics: ['production', 'weather'],
        relevance_score: 68, source: src('news_feeds_apimondia', 'Apimondia', 'trade_press'), is_demo: false },
    ],
    report_providers: [], news_providers: [], news_link: '/notizie?topic=production,weather', news_min_relevance: 35, is_demo: false,
  } as unknown as ReportsResponse
  const html = render(<ReportsBody data={data} />)
  const s = text(html)
  assert.match(s, /Le transazioni rilevate nel mese di settembre/)
  assert.doesNotMatch(s, /S o E S P L R O/)
  assert.match(s, /Brasile, più alveari contro gli effetti di El Niño/)
  assert.match(s, /Titolo tradotto con IA/)
  assert.match(s, /Titolo originale: Brazil, More Beehives/)
  assert.match(s, /Produzione/)
  assert.ok(hrefs(html).includes('/notizie?topic=production,weather'))
  assert.equal(readable('A plain sentence with enough words to judge it properly here.'), true)
})

test('the view is kept in the address: country, region, signal, list and chart options', () => {
  const p = readHarvestParams(new URLSearchParams('paese=arg&regione=arg-ba&segnale=drought_watch&elenco=tutti&misura=colonies&anni=tutti'))
  assert.deepEqual(p, { country: 'ARG', region: 'ARG-BA', signal: 'drought_watch', scope: 'all', metric: 'colonies', years: 'all' })
  // invalid values fall back to the defaults
  assert.deepEqual(readHarvestParams(new URLSearchParams('paese=Argentina&segnale=boh&regione=<x>')),
    { country: '', region: '', signal: '', scope: 'monitored', metric: 'production', years: '20' })
  const next = patchHarvestParams(new URLSearchParams('paese=ARG&foo=1'), { region: 'ARG-BA', scope: 'all', metric: 'production', years: '20' })
  assert.equal(next.toString(), 'paese=ARG&foo=1&regione=ARG-BA&elenco=tutti')
  assert.equal(patchHarvestParams(next, { country: '', region: '' }).toString(), 'foo=1&elenco=tutti')
})

test('reading guide and numbers in both languages', () => {
  const it = text(render(<ReadingGuide />))
  for (const k of ['Produzione confermata', 'Stime e previsioni ufficiali', 'Meteo misurato', 'Valutazione automatica', 'Contesto']) assert.match(it, new RegExp(k))
  const en = text(render(<ReadingGuide />, { lang: 'en' }))
  for (const k of ['Confirmed production', 'Official estimates and forecasts', 'Measured weather', 'Automatic assessment', 'Context']) assert.match(en, new RegExp(k))
  assert.equal(fmtAnomaly(4.65, 'it'), '+4,7 °C')
  assert.equal(fmtAnomaly(-0.43, 'en'), '−0.4 °C')
  assert.equal(fmtAnomaly(0.02, 'it'), '±0,0 °C')
  assert.equal(fmtPctOfNormal(13.4, 'it'), '13%')
  assert.equal(monthSpan([10, 11, 12, 1, 2, 3], 'it'), 'ott–mar')
  assert.equal(fmtMonthRun(['2025-12', '2026-01'], 'en'), 'Dec 2025 – Jan 2026')
  const hun = W.regions.find((r) => r.key === 'HUN')!
  assert.equal(fmtFlagValues(hun.flags[1], 'en'), '+4.1 °C, +2.1 °C and +4.7 °C')
  const tableEn = text(render(<WeatherTable data={W} country="HUN" signal="" selected="" onSignal={noop} onSelect={noop} />, { lang: 'en' }))
  assert.match(tableEn, /Drought watch \(in the last 3 months\) Rainfall at 12%, 50%, 49%, 30% and 13% of normal in Apr–Aug 2026, flowering months\./)
})
