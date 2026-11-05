// /aziende: honey exporters and importers by company, official sources only. Figures exactly as
// published (Uruguay XXI: exact FOB US$ per year, the running year marked year-to-date), lists without
// figures in alphabetical order and never ranked (HMRC), a plain reason where a country publishes
// nothing (Brazil), both languages, the country-profile block and the online copy's capture list.
// tests/fixtures/companies-*.json are the real /api/companies answers of 5 Nov 2026 (database snapshot
// after the live runs of uy_sie_honey_exporters and uk_hmrc_honey_traders). companies-GBR.json keeps
// the first 30 companies of each HMRC list plus NELSON HONEY UK LIMITED and HONEY NEW ZEALAND EUROPE
// LTD (company_count still says 93 exporters / 469 importers); the others are unmodified.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { CountryCompaniesBody } from '@/components/companies/CountryCompanies'
import { RegisterTable } from '@/components/companies/parts'
import type { CompaniesCountry, CompaniesOverview, RegisterList } from '@/components/companies/types'
import { CompaniesLayout, CountryBody } from '@/pages/Companies'
import overviewJson from './fixtures/companies-overview.json'
import uryJson from './fixtures/companies-URY.json'
import gbrJson from './fixtures/companies-GBR.json'
import braJson from './fixtures/companies-BRA.json'
import { hrefs, render, text } from './helpers'

const OV = overviewJson as unknown as CompaniesOverview
const URY = uryJson as unknown as CompaniesCountry
const GBR = gbrJson as unknown as CompaniesCountry
const BRA = braJson as unknown as CompaniesCountry
const noop = () => {}

type ExporterKey = { capturable: (k: string) => boolean; mirrorKey: (u: string) => string }
const nativeImport = new Function('u', 'return import(u)') as (u: string) => Promise<ExporterKey>
const exporter = () => nativeImport(new URL('../../scripts/mirror/key.mjs', import.meta.url).href)

test('Uruguay: exact FOB values per company and year, the running year marked, position only for the last complete year', () => {
  const html = render(<CountryBody d={URY} />)
  const s = text(html)
  assert.match(s, /Cifre ufficiali per azienda/)
  assert.match(s, /Uruguay XXI, l'agenzia governativa per le esportazioni/)
  assert.match(s, /17 aziende · HS 0409 Esportatori/)
  // what the figure is, in words
  assert.match(s, /Valore esatto pubblicato dalla fonte: FOB in USD, per anno\./)
  assert.match(s, /Posizione e quota nel 2025, l'ultimo anno completo/)
  assert.match(s, /2026: da gennaio a ottobre, provvisorio\./)
  // year columns, the running year with its months
  assert.match(s, /Pos\. · Azienda 2026 \(gen–ott\) 2025 Quota 2025 2024 2023 2022/)
  // NECTARBEE S.A. first: 2025 = 15,571,168.32 USD (55.8% of 27,928,748.53), 2026 Jan-Oct 18,061,978.55
  assert.match(s, /1 NECTARBEE S\.A\. 18\.061\.979 15\.571\.168 55,8% 13\.117\.615 9\.763\.468 17\.236\.140/)
  assert.match(html, /title="15\.571\.168,32 USD"/)
  assert.match(s, /2 BUZARAM COMPANY S\.A\. 5\.750\.903 3\.074\.002 11,0% 1\.736\.713 73\.692 —/)
  // the published totals
  assert.match(s, /Totale pubblicato 33\.100\.409 27\.928\.749 100% 27\.135\.495 18\.478\.487 35\.580\.437/)
  // a company without 2025 exports is listed without a position
  assert.match(s, /CUANIA SOCIEDAD ANONIMA — — 987\.119 710\.577 3\.514\.918/)
  // provenance: source, original document, rhythm, privacy note
  assert.match(s, /Fonte: Uruguay XXI – Instituto de Promoción de Inversiones/)
  assert.ok(hrefs(html).some((h) => h.startsWith('https://herramientas.uruguayxxi.gub.uy/sistema_de_estadistica/filtros.php?') && h.includes('t=empresa')))
  assert.match(s, /Aggiornamento: Controllo settimanale/)
  assert.match(s, /mai codici fiscali o identificativi personali/)
  // the table scrolls inside its card on a phone, the company column stays visible
  assert.match(html, /<div class="overflow-x-auto"><table class="table-clean w-full min-w-\[680px\]">/)
  assert.match(html, /sticky left-0/)
})

test('United Kingdom: names only, alphabetical, no position, no figure', () => {
  const html = render(<CountryBody d={GBR} />)
  const s = text(html)
  assert.match(s, /Elenco ufficiale, solo nomi/)
  assert.match(s, /Solo nomi: la fonte non pubblica quantità né valori\. Ordine alfabetico, non una classifica\./)
  assert.match(s, /93 aziende · HS 04090000 Esportatori/)
  assert.match(s, /469 aziende · HS 04090000 Importatori/)
  assert.match(s, /Periodo: nov 2024 – ago 2026/)
  assert.doesNotMatch(s, /Pos\./)
  assert.doesNotMatch(s, /Quota/)
  // the search box finds a company beyond the first 25 (HMRC: imports in Jan and Jul 2025, Jan, May, Jul 2026)
  const found = text(render(<RegisterTable list={GBR.lists[1] as RegisterList} initialQuery="nelson" />))
  assert.match(found, /NELSON HONEY UK LIMITED GLOUCESTERSHIRE, GL17 5 mesi lug 2026/)
  assert.doesNotMatch(found, /HONEY NEW ZEALAND/)
  assert.match(text(render(<RegisterTable list={GBR.lists[1] as RegisterList} initialQuery="hinckley" />)), /HONEY NEW ZEALAND EUROPE LTD HINCKLEY, LE10 22 mesi ago 2026/)
  // 32 importers in the fixture: the first 25 shown, then a button
  assert.match(s, /Mostra tutte \(32\)/)
  assert.match(s, /Fonte: HM Revenue & Customs \(HMRC\), UK Trade Info/)
  assert.ok(hrefs(html).includes('https://www.uktradeinfo.com/find-uk-traders/'))
  // alphabetical in each list, leading punctuation ignored, as the backend sorts
  for (const l of GBR.lists) {
    const key = (n: string) => n.replace(/^[^0-9A-Za-z]+/, '').toLocaleLowerCase()
    const names = l.companies.slice(0, 30).map((c) => c.name)
    for (let i = 1; i < names.length; i++) assert.ok(key(names[i - 1]) <= key(names[i]), `${names[i - 1]} / ${names[i]}`)
  }
})

test('Brazil: a plain explanation, the authority and the law, no list', () => {
  const html = render(<CountryBody d={BRA} />)
  const s = text(html)
  assert.match(s, /Non pubblicato/)
  assert.match(s, /non pubblica né fornisce elenchi di aziende esportatrici o importatrici/)
  assert.match(s, /decreto 11\.544\/2023, art\. 13/)
  assert.match(s, /Autorità: MDIC \/ SECEX/)
  assert.ok(hrefs(html).includes('https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/perguntas-frequentes-faq'))
  assert.doesNotMatch(html, /<table/)
  const en = text(render(<CountryBody d={BRA} />, { lang: 'en' }))
  assert.match(en, /Not published/)
  assert.match(en, /Decree 11,544\/2023, art\. 13/)
})

test('the country list groups countries by what they publish, and links each one', () => {
  const ury = OV.countries.find((c) => c.iso3 === 'URY')
  const html = render(<CompaniesLayout d={OV} selected={ury} onPick={noop} />)
  const s = text(html)
  assert.match(s, /1 con cifre, 1 solo nomi, 33 non pubblicati o non consultabili, 12 da verificare/)
  for (const iso of ['URY', 'GBR', 'BRA', 'ARG', 'CHL', 'ITA', 'CHN']) assert.ok(hrefs(html).includes(`/aziende?paese=${iso}`), iso)
  assert.match(html, /aria-current="page"[^>]*>(<span>Uruguay<\/span>)/)
  assert.match(s, /Uruguay 17 esp\./)
  assert.match(s, /Regno Unito 469 imp\. · 93 esp\./)       // per role, never added up
  // phones: a select with the same groups
  assert.match(html, /<select id="companies-country"/)
  assert.match(html, /<optgroup label="Non ancora verificato">/)
  // order: figures, register, not accessible, not published, not checked
  const pos = (re: RegExp) => s.search(re)
  assert.ok(pos(/Cifre ufficiali per azienda/) < pos(/Elenco ufficiale, solo nomi/))
  assert.ok(pos(/Elenco ufficiale, solo nomi/) < pos(/Esiste, ma non consultabile/))
  assert.ok(pos(/Non pubblicato/) < pos(/Non ancora verificato/))
})

test('English: the same page in English', () => {
  const s = text(render(<CountryBody d={URY} />, { lang: 'en' }))
  assert.match(s, /Official company figures/)
  assert.match(s, /2026 \(Jan–Oct\)/)
  assert.match(s, /Exact value published by the source: FOB in USD, per year\./)
  assert.match(s, /1 NECTARBEE S\.A\. 18,061,979 15,571,168 55\.8% 13,117,615 9,763,468 17,236,140/)
  assert.match(s, /Published total/)
  const g = text(render(<CountryBody d={GBR} />, { lang: 'en' }))
  assert.match(g, /Names only: the source publishes no quantities or values\. Alphabetical order, not a ranking\./)
  assert.match(g, /469 companies · HS 04090000 Importers/)
})

test('country profile block: top exporters with their share, or the size of a names-only list, or the reason', () => {
  const u = render(<CountryCompaniesBody d={URY} />)
  const us = text(u)
  assert.match(us, /Principali esportatori 2025/)
  assert.match(us, /1 NECTARBEE S\.A\. 15\.571\.168 USD 55,8%/)
  assert.match(us, /5 NIMELOR S A 1\.583\.781 USD 5,7%/)
  assert.doesNotMatch(us, /PUEBLANUEVA/)             // 6th: only the first five
  assert.ok(hrefs(u).includes('/aziende?paese=URY'))
  const g = text(render(<CountryCompaniesBody d={GBR} />))
  assert.match(g, /469 importatori e 93 esportatori in elenco \(nov 2024 – ago 2026\)/)
  assert.match(g, /Ordine alfabetico, non una classifica/)
  const b = text(render(<CountryCompaniesBody d={BRA} />))
  assert.match(b, /Non pubblicato/)
  assert.match(b, /segreto fiscale/)
})

test('the online copy records the company lists (public official data only)', async () => {
  const { capturable, mirrorKey } = await exporter()
  assert.ok(capturable(mirrorKey('/api/companies')))
  assert.ok(capturable(mirrorKey('/api/companies/URY')))
  assert.ok(!capturable(mirrorKey('/api/companies/URY/raw')))
})
