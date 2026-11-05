// /offerte — supplier quotes and landed cost.
// Q1: the first visit (no quote yet) explains the page and invites the first offer.
// Q2: with a tariff quota the list shows both duty alternatives as a range, never one chosen silently.
// Q3: freight / insurance not given are "non indicato" and the total is flagged incomplete, never assumed.
// Q4: US anti-dumping and Chapter 99 layers are explicit warnings with official links, never a rate.
// Q5: an exhausted quota is shown as unusable; the market reference keeps price types apart.
// Q6: numbers typed the Italian way are read correctly; the form validates before saving.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { CompareView } from '@/components/quotes/CompareView'
import { Breakdown } from '@/components/quotes/Breakdown'
import { DutyDetails } from '@/components/quotes/DutyDetails'
import { LandedSummary } from '@/components/quotes/LandedSummary'
import { MarketReference } from '@/components/quotes/MarketReference'
import { IncotermExplainer } from '@/components/quotes/QuoteForm'
import { QuoteCards, QuoteTable } from '@/components/quotes/QuoteTable'
import type {
  CompareResponse, Landed, LandedCompact, MarketReference as MR, Quote, QuoteListItem, QuotesList, RefRow, Scenario,
} from '@/components/quotes/types'
import { emptyForm, fmtTons, parseNum, validateForm } from '@/components/quotes/utils'
import type { DutyRow, Quota } from '@/components/regulations/types'
import type { Meta } from '@/lib/types'
import Quotes from '@/pages/Quotes'
import { hrefs, newQueryClient, render, text } from './helpers'

const META: Meta = {
  flags: { llm_enabled: false, llm_provider: null, comtrade_key: false, usda_mmn_key: false, usda_nass_key: false, scheduler_enabled: false },
  show_demo: false, language: 'it',
  countries: [
    { iso3: 'ARG', iso2: 'AR', name_it: 'Argentina', name_en: 'Argentina', priority: true, region: null, lat: null, lon: null },
    { iso3: 'UKR', iso2: 'UA', name_it: 'Ucraina', name_en: 'Ukraine', priority: true, region: null, lat: null, lon: null },
  ],
  varieties: [{ key: 'polyflora', it: 'Millefiori', en: 'Multifloral', core: true }, { key: 'sunflower', it: 'Girasole', en: 'Sunflower', core: true }],
  price_types: [], data_status: [], reliability: [],
}

const QUOTA: Quota = {
  order_number: '090881', volume_kg: 1_722_960, balance_kg: 1_304_730, status: 'open', fill_pct: 24.27,
  period_start: '2026-10-01', period_end: '2026-12-31', last_allocation_date: '2026-10-26', critical: null, shared_by_group: true, note: null,
}

let nextId = 1
function measure(o: Partial<DutyRow>): DutyRow {
  return {
    id: nextId++, series_key: 'k', jurisdiction: 'EU', origin_iso3: 'ERGA_OMNES', scope: 'general', hs_code: '0409000000',
    measure_type: 'mfn', measure_code: '103', description: null, duty_text: '17.30 %', ad_valorem_pct: 17.3,
    specific_amount: null, specific_unit: null, specific_currency: null, quota: null, valid_from: '2005-01-01', valid_to: null,
    legal_reference: 'R2204/99', legal_url: 'https://eur-lex.europa.eu/x', consult_url: null, source_url: null, published_at: null,
    as_of: '2026-11-04', collected_at: '2026-11-04', last_seen_at: '2026-11-04', revision: 1, is_current: true,
    supersedes_id: null, needs_review: false, review_reason: null, extra: null, source: null,
    reliability: 'official', data_status: 'published', is_demo: false, ...o,
  }
}

const amt = (eur: number | null, usd: number | null) => ({ eur, usd })
const totals = (eur: number, usd: number) => ({
  per_kg: amt(eur, usd), per_drum: amt(eur * 300, usd * 300), per_container: amt(eur * 20000, usd * 20000), quantity: amt(eur * 20000, usd * 20000),
})

const MFN = measure({})
const TRQ = measure({ origin_iso3: 'ARG', scope: 'origin', measure_type: 'trq_in', measure_code: '143', duty_text: '0.00 %', ad_valorem_pct: 0,
  quota: QUOTA, legal_reference: 'R1988/20', extra: { geo_area: { description: 'Mercosur', group: true } } })

function scenario(o: Partial<Scenario>): Scenario {
  return { key: 'k', kind: 'mfn', role: 'applicable', available: true, unavailable_reason: null, rate: { ad_valorem_pct: 17.3, specific_amount: null, specific_unit: null, specific_currency: null, duty_text: '17.30 %' },
    measure: MFN, stack: [], duty: amt(0.4627, 0.519), notes: [], total: totals(3.1375, 3.519), ...o }
}

// Argentina, polyflora, FOB Buenos Aires USD 3.00/kg into Italy, ECB 1.1216 (2 Nov 2026): freight and insurance not given.
function argLanded(o: Partial<Landed> = {}): Landed {
  return {
    destination: 'ITA', jurisdiction: 'EU', incoterm: 'FOB', incoterm_rule: { origin_costs: true, freight: false, insurance: false, duty: false },
    calc_date: '2026-11-04',
    fx: { mode: 'received', date: '2026-11-02', rates: [{ currency: 'USD', per_eur: 1.1216, rate_date: '2026-11-02' }], missing: [], source: null, source_url: null },
    assumptions: { drum_kg: 300, container_kg: 20000, quantity_kg: 20000, containers: 1 },
    lines: [
      { key: 'goods', status: 'ok', per_kg: amt(2.67475, 3), input: { amount: 3, currency: 'USD', unit: 'kg', per_kg_original: 3, incoterm: 'FOB', place: 'Buenos Aires' },
        source: { kind: 'quote', date: '2026-11-02' }, fx: { currency: 'USD', per_eur: 1.1216, rate_date: '2026-11-02', missing: false } },
      { key: 'freight', status: 'missing', per_kg: null, input: null, source: null, fx: null },
      { key: 'insurance', status: 'missing', per_kg: null, input: null, source: null, fx: null },
      { key: 'customs_value', status: 'subtotal', per_kg: amt(2.67475, 3), input: { basis: 'cif', jurisdiction: 'EU' }, source: null, fx: null },
    ],
    after_duty: [],
    scenarios: [
      scenario({ key: 'trq_in:1', kind: 'trq_in', role: 'in_quota', rate: { ad_valorem_pct: 0, specific_amount: null, specific_unit: null, specific_currency: null, duty_text: '0.00 %' },
        measure: TRQ, duty: amt(0, 0), total: totals(2.67475, 3) }),
      scenario({ key: 'mfn:2', kind: 'mfn', role: 'out_of_quota' }),
    ],
    headline: { eur_per_kg_min: 2.67475, eur_per_kg_max: 3.137482, usd_per_kg_min: 3, usd_per_kg_max: 3.519, alternatives: true, complete: false,
      missing: ['freight_missing', 'insurance_missing'], warnings: [] },
    flags: [{ code: 'freight_missing', kind: 'missing', params: {} }, { code: 'insurance_missing', kind: 'missing', params: {} },
      { code: 'quota_alternatives', kind: 'info', params: {} }],
    duty: { jurisdiction: 'EU', on: '2026-11-04', has_data: true, as_of: '2026-11-04', as_of_latest: '2026-11-04', applied: [TRQ, MFN], review: [],
      review_other_origins: 0, not_applied: [], origin_covered: true, source: null,
      links: { taric: 'https://ec.europa.eu/taxation_customs/dds2/taric/measures.jsp?Area=AR' }, ad_case: null, us: null },
    ...o,
  }
}

function compact(l: Landed): LandedCompact {
  return {
    destination: l.destination, headline: l.headline, fx: { date: l.fx.date, rates: l.fx.rates, missing: l.fx.missing },
    flags: l.flags.map((f) => ({ code: f.code, kind: f.kind })),
    scenarios: l.scenarios.map((s) => ({ key: s.key, kind: s.kind, role: s.role, available: s.available, unavailable_reason: s.unavailable_reason,
      rate: s.rate, quota: s.measure?.quota ?? null, total_per_kg: s.total?.per_kg ?? null })),
  }
}

function quote(o: Partial<Quote> = {}): Quote {
  return {
    id: 1, supplier_name: 'Esportatore Pampa', origin_iso3: 'ARG', variety: 'polyflora', variety_note: null, price: 3, price_unit: 'kg',
    price_per_kg: 3, currency: 'USD', quantity_kg: 20000, packaging: null, incoterm: 'FOB', incoterm_place: 'Buenos Aires',
    shipping_cost: null, shipping_cost_currency: null, shipping_cost_basis: null, insurance_pct: null, duty_pct: null, other_costs: null,
    other_costs_currency: null, cost_items: [], destination: 'ITA', date_received: '2026-11-02', valid_until: '2026-11-10', days_to_expiry: 6,
    notes: null, archived: false, status: 'expiring', created_at: '2026-11-02T09:00:00', updated_at: '2026-11-02T09:00:00', is_demo: false,
    data_status: 'user_entered', reliability: 'user', ...o,
  }
}

const item = (o: Partial<Quote> = {}, l: Landed = argLanded()): QuoteListItem => ({ ...quote(o), landed: compact(l) })

function list(items: QuoteListItem[], o: Partial<QuotesList> = {}): QuotesList {
  return {
    items, total: items.length, counts: { active: 0, expiring: items.length, expired: 0, archived: 0 }, total_all: items.length,
    facets: { origins: [], varieties: [], suppliers: [] }, today: '2026-11-04', expiring_days: 7, fx_mode: 'received', ...o,
  }
}

function page(data: QuotesList, lang: 'it' | 'en' = 'it') {
  const qc = newQueryClient()
  qc.setQueryData(['meta'], META)
  qc.setQueryData(['quotes', 'list', { fx: 'received' }], data)
  qc.setQueryData(['quotes', 'meta'], { currencies: ['EUR', 'USD'], fx_newest: '2026-11-04' })
  return render(<Quotes />, { url: '/offerte', lang, qc })
}

test('Q1 first visit: a friendly empty state explains the page and invites the first quote', () => {
  const it = text(page(list([])))
  assert.match(it, /Nessuna offerta registrata/)
  assert.match(it, /Aggiungi la prima offerta/)
  assert.match(it, /costo sbarcato/i)
  assert.match(it, /restano su questo computer\. Unica eccezione: se attivi l'assistente IA/)
  assert.match(it, /Ultimo cambio BCE disponibile: 04 nov 2026/)
  assert.doesNotMatch(it, /Esporta CSV/, 'nothing to export yet')
  const en = text(page(list([]), 'en'))
  assert.match(en, /No quotes recorded yet/)
  assert.match(en, /Add the first quote/)
})

test('Q2 a tariff quota gives a range of both alternatives, never one chosen silently', () => {
  const html = page(list([item()]))
  const body = text(html)
  assert.match(body, /2,675\s€\s–\s3,137\s€/)
  assert.match(body, /contingente 0\s% \/ pieno 17,3\s%/)
  assert.match(body, /calcolo incompleto/)
  assert.match(body, /Esporta CSV/)
  assert.ok(hrefs(html).some((h) => h.startsWith('/api/quotes/export?') && h.includes('lang=it')), 'CSV export link')

  const summary = text(render(<LandedSummary landed={argLanded()} />))
  assert.match(summary, /Ipotesi entro il contingente/)
  assert.match(summary, /Entro il contingente 090881 · Mercosur/)
  assert.match(summary, /Fuori contingente: dazio pieno/)
  assert.match(summary, /non ne sceglie una/)
  // per drum and per container figures of both alternatives
  assert.match(summary, /802,43\s€/)
  assert.match(summary, /941,25\s€/)
  assert.match(summary, /62\.750\s€/)
})

test('Q3 freight and insurance not given are "non indicato", flagged, never assumed', () => {
  const body = text(render(<Breakdown landed={argLanded()} />))
  assert.match(body, /Nolo non indicato: escluso dal totale/)
  assert.match(body, /Assicurazione non indicata: esclusa dal totale/)
  assert.match(body, /BCE: 1 EUR = 1,1216 USD/)
  assert.match(body, /Somma senza le voci non indicate/)
  const summary = text(render(<LandedSummary landed={argLanded()} />))
  assert.match(summary, /Calcolo incompleto/)
  assert.match(summary, /Assicurazione non indicata \(nessuna percentuale viene ipotizzata\)/)
  // a complete calculation says so
  const complete = argLanded({ flags: [], headline: { ...argLanded().headline, complete: true, missing: [] } })
  assert.match(text(render(<LandedSummary landed={complete} />)), /Tutte le voci che il prezzo non comprende sono indicate/)
})

test('Q4 US anti-dumping and Chapter 99 layers are warnings with official links, never a rate', () => {
  const general = measure({ jurisdiction: 'US', origin_iso3: 'ALL', hs_code: '0409.00.00', measure_code: 'general', duty_text: '1.9¢/kg',
    ad_valorem_pct: null, specific_amount: 0.019, specific_unit: 'kg', specific_currency: 'USD', legal_reference: 'HTSUS 0409.00.00, column 1 general' })
  const ch99 = measure({ jurisdiction: 'US', origin_iso3: 'ALL', measure_type: 'other', measure_code: '9903.01.25', ad_valorem_pct: 10,
    duty_text: 'The duty provided in the applicable subheading + 10%', needs_review: true, consult_url: 'https://hts.usitc.gov/search?query=9903.01.25',
    description: 'Articles the product of any country' })
  const us = argLanded({
    destination: 'USA', jurisdiction: 'US',
    scenarios: [scenario({ key: 'mfn:9', kind: 'mfn', rate: { ad_valorem_pct: null, specific_amount: 0.019, specific_unit: 'kg', specific_currency: 'USD', duty_text: '1.9¢/kg' },
      measure: general, duty: amt(0.0169, 0.019), total: totals(2.6917, 3.019) })],
    headline: { eur_per_kg_min: 2.6917, eur_per_kg_max: 2.6917, usd_per_kg_min: 3.019, usd_per_kg_max: 3.019, alternatives: false, complete: true,
      missing: [], warnings: ['us_antidumping', 'us_additional_duty_review'] },
    flags: [{ code: 'us_antidumping', kind: 'warning', params: { case_number: 'A-357-823' } }, { code: 'us_additional_duty_review', kind: 'warning', params: { count: 1 } }],
    duty: { ...argLanded().duty, jurisdiction: 'US', applied: [general], review: [ch99], review_other_origins: 5, links: { hts: 'https://hts.usitc.gov/search?query=0409.00.00' },
      ad_case: { origin_iso3: 'ARG', case_number: 'A-357-823', product: 'Raw Honey from Argentina',
        fr_search_url: 'https://www.federalregister.gov/documents/search?conditions%5Bterm%5D=%22raw+honey+from+argentina%22', documents_total: 1,
        documents: [{ id: 84, reference: '2026-18701', title: 'Raw Honey From Argentina: Preliminary Results of Antidumping Duty Administrative Review; 2024-2025',
          doc_type: 'antidumping', published_at: '2026-09-14', url: 'https://www.federalregister.gov/d/2026-18701', is_demo: false }] } },
  })
  const html = render(<DutyDetails landed={us} origin="ARG" />)
  const body = text(html)
  assert.match(body, /Possibile dazio aggiuntivo: verificare/)
  assert.match(body, /A-357-823/)
  assert.match(body, /non la calcola e non la inventa/)
  assert.match(body, /9903\.01\.25/)
  assert.match(body, /Altre 5 voci del capitolo 99 riguardano solo altri paesi/)
  const links = hrefs(html)
  assert.ok(links.some((h) => h.startsWith('https://www.federalregister.gov/documents/search')), 'Federal Register search')
  assert.ok(links.includes('https://www.federalregister.gov/d/2026-18701'), 'the AD document')
  assert.ok(links.includes('https://hts.usitc.gov/search?query=9903.01.25'), 'the Chapter 99 heading')
  // the landed cost holds the general rate only: the warning is not turned into a number
  const summary = text(render(<LandedSummary landed={us} />))
  assert.match(summary, /2,692\s€/)
  assert.match(summary, /1,9\s¢\/kg/)
  const row = text(page(list([item({ destination: 'USA' }, us)])))
  assert.match(row, /possibile dazio aggiuntivo: verificare/)
})

test('Q5 an exhausted quota is shown unusable and only the full duty is priced', () => {
  const exhausted = argLanded({
    scenarios: [
      scenario({ key: 'trq_in:3', kind: 'trq_in', role: 'in_quota', available: false, unavailable_reason: 'exhausted',
        measure: measure({ origin_iso3: 'UKR', scope: 'origin', measure_type: 'trq_in', ad_valorem_pct: 0, duty_text: '0.00 %',
          quota: { ...QUOTA, order_number: '096701', balance_kg: 0, status: 'exhausted', fill_pct: 100 } }),
        duty: amt(0, 0), total: totals(2.35, 2.63) }),
      scenario({ key: 'mfn:2', kind: 'mfn', role: 'out_of_quota', total: totals(2.7566, 3.0855) }),
    ],
    headline: { eur_per_kg_min: 2.7566, eur_per_kg_max: 2.7566, usd_per_kg_min: 3.0855, usd_per_kg_max: 3.0855, alternatives: false, complete: true,
      missing: [], warnings: ['quota_unavailable'] },
    flags: [{ code: 'quota_unavailable', kind: 'warning', params: { reason: 'exhausted', order: '096701' } }],
  })
  const body = text(render(<LandedSummary landed={exhausted} />))
  assert.match(body, /Contingente esaurito/)
  assert.match(body, /Non utilizzabile oggi/)
  assert.match(body, /Contingente esaurito \(096701\): si applica il dazio fuori contingente/)
  assert.doesNotMatch(body, /2,350\s€/, 'the unusable in-quota cost is not shown as a price')
  assert.match(body, /2,757\s€/)
  const row = text(page(list([item({ origin_iso3: 'UKR', variety: 'sunflower' }, exhausted)])))
  assert.match(row, /contingente esaurito/)
  assert.doesNotMatch(row, /possibile dazio aggiuntivo/, 'an exhausted quota is not an additional duty')
})

function ref(o: Partial<RefRow>): RefRow {
  return {
    id: nextId++, source: { key: 'eurostat_comext', name: 'Eurostat Comext', publisher: 'Eurostat (European Commission)', reliability: 'official', homepage: null },
    price_type: 'import_unit_value', origin_iso3: 'ARG', market_iso3: 'ITA', market_location: null, variety: 'unspecified', variety_raw: null,
    color_grade: null, organic: false, terms: 'CIF', price_low: null, price_high: null, price_value: 2.3923, currency: 'EUR', unit: 'kg',
    price_per_kg: 2.3923, eur_per_kg: 2.3923, usd_per_kg: 2.7314, fx_basis: 'period_avg', fx_date: '2026-07-31', volume_kg: 208_493,
    period_label: '2026-07', period_start: '2026-07-01', period_end: '2026-07-31', frequency: 'M', published_at: '2026-10-16',
    collected_at: '2026-11-04T20:49:51', source_url: 'https://ec.europa.eu/eurostat/x', data_status: 'published', reliability: 'official',
    is_demo: false, age_days: 96, freshness: null, ...o,
  }
}

test('Q5 the market reference keeps the three price types apart, each with its period and date', () => {
  const market: MR = {
    origin_iso3: 'ARG', variety: 'polyflora',
    blocks: [
      { key: 'eu_import', price_type: 'import_unit_value', rows: [ref({})], not_applicable: false, min_volume_kg: 10000 },
      { key: 'us_importer', price_type: 'wholesale_bulk', variety_match: true, not_applicable: false, rows: [ref({
        source: { key: 'usda_honey_report', name: 'USDA', publisher: 'USDA AMS', reliability: 'official', homepage: null },
        price_type: 'wholesale_bulk', market_iso3: 'USA', variety: 'polyflora', variety_raw: 'Mixed', color_grade: 'light amber',
        price_low: 1.44, price_high: 2.1, price_value: 1.77, currency: 'USD', unit: 'lb', eur_per_kg: 3.3896, usd_per_kg: 3.9022,
        volume_kg: null, period_label: '2026-09', period_end: '2026-09-30', published_at: '2026-10-30', variety_match: true })] },
      { key: 'it_wholesale', price_type: 'wholesale_bulk', not_applicable: false, variety_generic: false, rows: [ref({
        source: { key: 'cciaa_cuneo_miele', name: 'CCIAA Cuneo', publisher: 'Camera di Commercio di Cuneo', reliability: 'industry', homepage: null },
        price_type: 'wholesale_bulk', origin_iso3: 'ITA', variety: 'polyflora', variety_raw: 'Millefiori', price_low: 4.5, price_high: 5.5,
        price_value: 5, terms: 'fusto da 3 q.li; franco partenza dal magazzino; IVA compresa', period_label: '2026-09', age_days: 35 })] },
    ],
  }
  const body = text(render(<MarketReference market={market} />))
  assert.match(body, /Valore all'import UE/)
  assert.match(body, /Prezzo agli importatori USA/)
  assert.match(body, /Ingrosso Italia, miele italiano/)
  assert.match(body, /non vanno sommati/)
  assert.match(body, /lug 2026/)
  assert.match(body, /set 2026/)
  assert.match(body, /2,392\s€/)
  assert.match(body, /1,44–2,10/, 'USD/lb range with two decimals')
  assert.match(body, /Ambra chiaro/, 'USDA colour grades in Italian')
  assert.match(body, /IVA compresa/)
  assert.match(body, /Pubblicato 16 ott 2026/)
  // a generic variety is never matched to a price-list line
  const generic: MR = { ...market, variety: 'other', blocks: [{ key: 'it_wholesale', price_type: 'wholesale_bulk', rows: [], not_applicable: false, variety_generic: true }] }
  assert.match(text(render(<MarketReference market={generic} />)), /Varietà generica/)
})

test('Q6 numbers typed the Italian way are read correctly', () => {
  assert.equal(parseNum('3,05', 'it'), 3.05)
  assert.equal(parseNum('3.05', 'it'), 3.05)
  assert.equal(parseNum('20.000', 'it'), 20000)
  assert.equal(parseNum('1.234,5', 'it'), 1234.5)
  assert.equal(parseNum('1,234.5', 'en'), 1234.5)
  assert.equal(parseNum('20,000', 'en'), 20000)
  assert.equal(parseNum('', 'it'), null)
  assert.ok(Number.isNaN(parseNum('3,1x', 'it') as number))
  assert.equal(fmtTons(19_200, 'it'), '19,2 t')
  assert.equal(fmtTons(20_000, 'en'), '20 t')
})

test('Q6 the form validates before saving and converts units', () => {
  const today = '2026-11-04'
  const empty = validateForm(emptyForm(today), 'it', today)
  assert.equal(empty.body, null)
  assert.deepEqual(Object.keys(empty.errors).sort(), ['origin_iso3', 'price', 'supplier_name', 'variety'])
  const f = { ...emptyForm(today), supplier_name: '  Pampa  ', origin_iso3: 'ARG', variety: 'polyflora', price: '1,36', price_unit: 'lb' as const,
    quantity: '64', quantity_unit: 'drums' as const, incoterm: 'CFR' as const, insurance_pct: '0,3' }
  const ok = validateForm(f, 'it', today)
  assert.ok(ok.body)
  assert.equal(ok.body.supplier_name, 'Pampa')
  assert.equal(ok.body.price, 1.36)
  assert.equal(ok.body.price_unit, 'lb')
  assert.equal(ok.body.quantity_kg, 19_200)
  assert.equal(ok.body.insurance_pct, 0.3)
  assert.equal(ok.body.duty_pct, null, 'the duty is automatic unless the user enters one')
  assert.equal(validateForm({ ...f, date_received: '2026-11-05' }, 'it', today).errors.date_received, 'form.err.future')
  assert.equal(validateForm({ ...f, valid_until: '2026-11-01', date_received: '2026-11-02' }, 'it', today).errors.valid_until, 'form.err.validBefore')
  assert.equal(validateForm({ ...f, insurance_pct: '40' }, 'it', today).errors.insurance_pct, 'form.err.range')
  const pct = validateForm({ ...f, cost_items: [{ kind: 'bank', amount: '150', basis: 'pct_goods', currency: 'EUR', note: '' }] }, 'it', today)
  assert.equal(pct.errors.cost_0, 'form.err.pct')
  const cost = validateForm({ ...f, cost_items: [{ kind: 'port', amount: '350', basis: 'per_container', currency: 'EUR', note: ' THC ' }] }, 'it', today)
  assert.deepEqual(cost.body?.cost_items, [{ kind: 'port', amount: 350, basis: 'per_container', currency: 'EUR', note: 'THC' }])
})

test('Q6 Incoterms are explained in plain words with what the price includes', () => {
  const fob = text(render(<IncotermExplainer incoterm="FOB" />))
  assert.match(fob, /carica sulla nave nel porto di partenza/)
  assert.match(fob, /Nolo marittimo, assicurazione e dazi sono a carico tuo/)
  const cif = text(render(<IncotermExplainer incoterm="CIF" />, { lang: 'en' }))
  assert.match(cif, /freight and insurance \(minimum cover\)/)
  assert.match(text(render(<IncotermExplainer incoterm="" />)), /aggiunge solo ciò che il prezzo non comprende/)
})

test('demo quotes carry the DEMO badge in the table and on the phone cards', () => {
  const demo = [item({ id: 7, supplier_name: 'DEMO Exporter A', is_demo: true, data_status: 'demo', reliability: 'demo' })]
  const props = { items: demo, selected: [], onToggle: () => {}, onOpen: () => {} }
  const qc = newQueryClient()
  qc.setQueryData(['meta'], META)
  assert.match(text(render(<QuoteTable {...props} />, { qc })), /DEMO Exporter A DEMO/)
  assert.match(text(render(<QuoteCards {...props} />, { qc })), /DEMO Exporter A .*DEMO/)
})

test('the comparison ranks by landed €/kg and names incomplete quotes', () => {
  const a = { quote: quote({ id: 1, supplier_name: 'China Bee', origin_iso3: 'CHN' }), landed: compact(argLanded()), value_eur_per_kg: 1.778, value_usd_per_kg: 1.994,
    scenario: { kind: 'mfn', rate: { ad_valorem_pct: 17.3, specific_amount: null, specific_unit: null, specific_currency: null, duty_text: '17.30 %' }, quota: null },
    rank: 1, diff_eur_per_kg: 0, diff_pct: 0, diff_eur_per_container: 0, diff_usd_per_kg: 0 }
  const b = { ...a, quote: quote({ id: 2, supplier_name: 'Ucraina Sunflower', origin_iso3: 'UKR' }), value_eur_per_kg: 2.757, value_usd_per_kg: 3.069,
    rank: 2, diff_eur_per_kg: 0.979, diff_pct: 55.06, diff_eur_per_container: 19570, diff_usd_per_kg: 1.075 }
  const data: CompareResponse = { basis: 'conservative', fx_mode: 'received', container_kg: 20000, drum_kg: 300, items: [a, b], best_id: 1,
    mixed_destinations: false, mixed_demo: false, incomplete: [1] }
  const qc = newQueryClient()
  qc.setQueryData(['meta'], META)
  qc.setQueryData(['quotes', 'compare', [1, 2], 'conservative', 'received'], data)
  const body = text(render(<CompareView ids={[1, 2]} basis="conservative" fx="received" onBasis={() => {}} onFx={() => {}} onClose={() => {}} onOpen={() => {}} />, { qc }))
  assert.match(body, /Confronto di 2 offerte/)
  assert.match(body, /Calcolo incompleto per China Bee/)
  assert.match(body, /\+0,979\s€/)
  assert.match(body, /\+55,1%/)
  assert.match(body, /\+19\.570\s€/)
  assert.match(body, /Prudente/)
})
