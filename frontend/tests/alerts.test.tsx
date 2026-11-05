// Alert center (/avvisi): the feed puts unread alerts first and shows every alert's figures with its
// source, period, dates and links; the empty states explain that rules only report new data; rules
// read back in plain words in the UI language; the editor only offers what has data.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { QueryClient } from '@tanstack/react-query'
import { AlertBell, UNREAD_KEY } from '@/components/alerts/AlertBell'
import { EventFeed, type FeedFilters } from '@/components/alerts/EventFeed'
import { PreviewResult } from '@/components/alerts/PreviewResult'
import { RuleList } from '@/components/alerts/RuleList'
import { suggestName } from '@/components/alerts/RuleEditor'
import type { AlertEventItem, AlertRule, EventsResponse, OptionsResponse, PreviewResponse } from '@/components/alerts/types'
import { defaultParams, errorText, fixPrice, fixTrade, paramsReady, parseKeywords } from '@/components/alerts/utils'
import alerts from '@/i18n/pages/alerts'
import { ApiError } from '@/lib/api'
import { hrefs, newQueryClient, render, text } from './helpers'

const SOURCE = { key: 'usda_honey_report', name: 'USDA AMS – National Honey Report (prezzi miele USA)',
  publisher: 'USDA Agricultural Marketing Service (AMS)', reliability: 'official', homepage: null }

function withMeta(qc: QueryClient = newQueryClient()): QueryClient {
  qc.setQueryData(['meta'], {
    flags: {}, show_demo: false, language: 'it',
    countries: [
      { iso3: 'ARG', iso2: 'AR', name_it: 'Argentina', name_en: 'Argentina', priority: true, region: null, lat: null, lon: null },
      { iso3: 'CHN', iso2: 'CN', name_it: 'Cina', name_en: 'China', priority: true, region: null, lat: null, lon: null },
      { iso3: 'USA', iso2: 'US', name_it: 'Stati Uniti', name_en: 'United States', priority: true, region: null, lat: null, lon: null },
    ],
    varieties: [{ key: 'polyflora', it: 'Millefiori', en: 'Multifloral (polyflora)', core: true }],
    price_types: [{ key: 'wholesale_bulk', it: "Prezzo all'ingrosso (sfuso)", en: 'Wholesale (bulk)' }],
    data_status: [], reliability: [],
  })
  return qc
}

function event(o: Partial<AlertEventItem>): AlertEventItem {
  return {
    id: 1, rule_id: 1, rule_name: 'Argentina millefiori +5%', alert_type: 'price_change', dedup_key: 'price:x:2026-09',
    triggered_at: '2026-11-04T10:00:00', severity: 'info',
    title_it: 'Argentina → Stati Uniti · Millefiori · bianco: +6,7% a settembre 2026',
    title_en: 'Argentina → United States · Multifloral (polyflora) · white: +6.7% in September 2026',
    body_it: "Prezzo all'ingrosso (sfuso): 3,94 USD/kg a settembre 2026, contro 3,69 USD/kg ad agosto 2026 (+6,7%).",
    body_en: 'Wholesale (bulk) price: 3.94 USD/kg in September 2026, against 3.69 USD/kg in August 2026 (+6.7%).',
    link: '/prezzi?tipo=wholesale_bulk&origini=ARG&varieta=polyflora', link_internal: true, ref_type: 'price', ref_id: 7,
    read: false, source: SOURCE, source_url: 'https://example.org/FVMHONEY.PDF', published_at: '2026-10-30',
    collected_at: '2026-11-04T08:00:00', period_label: '2026-09', is_demo: false, ...o,
  }
}

function feed(items: AlertEventItem[]): EventsResponse {
  return { items, total: items.length, unread: items.filter((e) => !e.read).length, page: 1, page_size: 20,
    pages: items.length ? 1 : 0, rules: [] }
}

const ALL: FeedFilters = { status: 'all', type: '', page: 1 }

test('an alert shows its figures, period, source, publication date and links', () => {
  const e = event({})
  for (const lang of ['it', 'en'] as const) {
    const html = render(<EventFeed data={feed([e])} filters={ALL} onFilters={() => {}} onToggleRead={() => {}} />, { lang, qc: withMeta() })
    const body = text(html)
    assert.match(body, lang === 'it' ? /\+6,7% a settembre 2026/ : /\+6\.7% in September 2026/)
    assert.match(body, lang === 'it' ? /Da leggere/ : /Unread/)
    assert.match(body, /USDA Agricultural Marketing Service/)
    assert.match(body, lang === 'it' ? /Pubblicato 30 ott 2026/ : /Published 30 Oct 2026/)
    assert.match(body, lang === 'it' ? /Regola: Argentina millefiori \+5%/ : /Rule: Argentina millefiori \+5%/)
    assert.ok(hrefs(html).includes('https://example.org/FVMHONEY.PDF'), 'link to the original document')
    assert.ok(hrefs(html).includes('/prezzi?tipo=wholesale_bulk&origini=ARG&varieta=polyflora'), 'link to the data in the app')
  }
})

test('read alerts lose the unread marker and offer "mark as unread"', () => {
  const body = text(render(<EventFeed data={feed([event({ id: 2, read: true })])} filters={ALL} onFilters={() => {}} onToggleRead={() => {}} />))
  assert.doesNotMatch(body, /Da leggere 1|DA LEGGERE/)
  assert.match(body, /Segna come da leggere/)
  assert.doesNotMatch(body, /Segna tutti come letti/, 'no "mark all" when nothing is unread')
})

test('empty feed explains that rules only report data that arrives after them', () => {
  const it = text(render(<EventFeed data={feed([])} filters={ALL} onFilters={() => {}} />))
  assert.match(it, /Nessun avviso finora/)
  assert.match(it, /solo per i dati arrivati dopo la sua creazione/)
  assert.match(it, /14 giorni/)
  const en = text(render(<EventFeed data={feed([])} filters={ALL} onFilters={() => {}} />, { lang: 'en' }))
  assert.match(en, /No alerts yet/)
  assert.match(en, /only alerts on data that arrives after it was created/)
  const unread = text(render(<EventFeed data={feed([])} filters={{ ...ALL, status: 'unread' }} onFilters={() => {}} />))
  assert.match(unread, /Nessun avviso da leggere/)
})

function rule(o: Partial<AlertRule>): AlertRule {
  return {
    id: 1, name: "Argentina millefiori +5% (prezzo all'ingrosso)", alert_type: 'price_change', params: {},
    enabled: true, created_at: '2026-11-04T10:00:00', watching_since: '2026-11-04T10:00:00', last_checked_at: '2026-11-04T11:00:00',
    description_it: "Avvisa quando il prezzo all'ingrosso (sfuso) del miele millefiori di origine Argentina sale di almeno il 5%.",
    description_en: 'Alerts when the wholesale (bulk) price of multifloral (polyflora) honey from Argentina rises by at least 5%.',
    events_total: 3, events_unread: 1, last_event_at: '2026-11-04T11:00:00', is_example: true, ...o,
  }
}

test('rules read back in plain words, with an accessible on/off switch', () => {
  const rules = [rule({}), rule({ id: 2, name: 'Notizie Cina', alert_type: 'news_keyword', enabled: false, is_example: false,
    events_total: 0, events_unread: 0, last_event_at: null })]
  const html = render(<RuleList rules={rules} onToggle={() => {}} onEdit={() => {}} onDelete={() => {}} />)
  const body = text(html)
  assert.match(body, /Avvisa quando il prezzo all'ingrosso \(sfuso\) del miele millefiori/)
  assert.match(body, /Esempio/)
  assert.match(body, /3 avvisi/)
  assert.match(body, /1 da leggere/)
  assert.match(body, /nessun avviso finora/)
  assert.match(html, /role="switch" aria-checked="true"/)
  assert.match(html, /role="switch" aria-checked="false"/)
  const en = text(render(<RuleList rules={rules} />, { lang: 'en' }))
  assert.match(en, /Alerts when the wholesale \(bulk\) price/)
  assert.match(en, /Example/)
})

test('the test-now result names each comparison and why it does or does not fire', () => {
  const pv: PreviewResponse = {
    alert_type: 'price_change', total: 1, window_days: null,
    description_it: '…', description_en: '…',
    items: [{ dedup_key: 'price:a:2026-09', title_it: 'Argentina: +6,7% a settembre 2026', title_en: 'Argentina: +6.7% in September 2026',
      body_it: '…', body_en: '…', severity: 'warning', link: null, ref_type: 'price', ref_id: 1, observed_at: null,
      published_at: '2026-10-30', period_label: '2026-09', source: SOURCE, source_url: null, already_sent: true }],
    checked: [
      { label_it: 'Argentina → Stati Uniti · Millefiori · bianco', label_en: 'Argentina → United States · white', period_label: '2026-09',
        previous_period_label: '2026-08', value: 3.94, previous_value: 3.69, currency: 'USD', pct: 6.78, reason: 'fires' },
      { label_it: 'Argentina → Stati Uniti · Millefiori · ambra', label_en: 'x', period_label: '2026-09', previous_period_label: '2026-08',
        value: 3.9, previous_value: null, currency: 'USD', pct: null, reason: 'no_previous' },
    ],
  }
  const body = text(render(<PreviewResult pv={pv} />))
  assert.match(body, /troverebbe 1 avviso/)
  assert.match(body, /già segnalato/)
  assert.match(body, /supera la soglia/)
  assert.match(body, /manca il periodo di confronto/)
  assert.match(body, /3,94 USD\/kg/)
})

test('the bell shows the unread count and links to the alert center', () => {
  const qc = newQueryClient()
  qc.setQueryData([...UNREAD_KEY], { unread: 3, unread_warning: 1, latest_unread_at: null })
  const html = render(<AlertBell />, { qc })
  assert.ok(hrefs(html).includes('/avvisi'))
  assert.match(html, /aria-label="Avvisi da leggere: 3"/)
  assert.match(text(html), /^3$/)
  const none = newQueryClient()
  none.setQueryData([...UNREAD_KEY], { unread: 0, unread_warning: 0, latest_unread_at: null })
  assert.match(render(<AlertBell />, { qc: none, lang: 'en' }), /aria-label="Alerts: none unread"/)
})

const OPTIONS: OptionsResponse = {
  price: [
    { price_type: 'wholesale_bulk', origin: 'ARG', variety: 'polyflora', market: 'USA', color_grade: 'white', count: 18, last_period: '2026-09', first_period: '2024-03' },
    { price_type: 'wholesale_bulk', origin: 'ARG', variety: 'polyflora', market: 'USA', color_grade: 'light amber', count: 18, last_period: '2026-09', first_period: '2024-03' },
    { price_type: 'import_unit_value', origin: 'ARG', variety: 'unspecified', market: 'EU27', color_grade: null, count: 57, last_period: '2026-08', first_period: '2021-12' },
  ],
  report_sources: [{ ...SOURCE, reports: 23, latest_published_at: '2026-10-30' }],
  news: { countries: [], articles: 0 },
  regulation: { jurisdictions: [], doc_types: [], countries: [] },
  trade: [{ iso3: 'EU27', flows: { import: { freqs: ['M', 'A'], partners: ['WLD', 'ARG'], rows: 100, last_period: '2026-08' } } }],
  examples: [],
}

test('the editor only offers combinations that have data', () => {
  const p = defaultParams('price_change', OPTIONS)
  assert.deepEqual([p.price_type, p.origin, p.variety], ['wholesale_bulk', 'ARG', 'polyflora'])
  // a price type without that variety moves to one it has; a market it does not have is cleared
  const fixed = fixPrice(OPTIONS.price, { ...p, price_type: 'import_unit_value', market: 'USA', color_grade: 'white' })
  assert.deepEqual([fixed.variety, fixed.market, fixed.color_grade], ['unspecified', null, null])
  const t = fixTrade(OPTIONS.trade, { reporter: 'XXX', flow: 'export', partner: 'CHN', freq: 'Q' })
  assert.deepEqual([t.reporter, t.flow, t.partner, t.freq], ['EU27', 'import', 'WLD', 'M'])
  assert.deepEqual(defaultParams('new_report', OPTIONS), { source_keys: ['usda_honey_report'] })
  assert.equal(paramsReady('news_keyword', { keywords: [], countries: [] }), false)
  assert.equal(paramsReady('news_keyword', { keywords: parseKeywords(' export, dazi ,export,, ') }), true)
  assert.deepEqual(parseKeywords(' export, dazi ,export,, '), ['export', 'dazi'])
})

test('suggested names and bilingual error messages', () => {
  const fns = { t: (k: string) => alerts.it[k.replace('alerts.', '') as keyof typeof alerts.it] ?? k,
    country: (c: string) => ({ ARG: 'Argentina', EU27: 'Unione Europea' } as Record<string, string>)[c] ?? c,
    variety: (v: string) => (v === 'polyflora' ? 'Millefiori' : v), lang: 'it' as const }
  assert.equal(suggestName('price_change', { origin: 'ARG', variety: 'polyflora', threshold_pct: 5, direction: 'up' }, fns), 'Argentina millefiori +5%')
  assert.equal(suggestName('trade_change', { reporter: 'EU27', partner: 'ARG', flow: 'import', threshold_pct: 20, direction: 'any' }, fns),
    'Importazioni Unione Europea · Argentina ±20%')
  const err = new ApiError(422, 'Tipo di prezzo non valido / Invalid price type')
  assert.equal(errorText(err, 'it'), 'Tipo di prezzo non valido')
  assert.equal(errorText(err, 'en'), 'Invalid price type')
})

test('every alert string exists in both languages', () => {
  assert.deepEqual(Object.keys(alerts.it).sort(), Object.keys(alerts.en).sort())
  for (const [k, v] of Object.entries(alerts.en)) assert.ok(v.trim(), `alerts.en.${k} is empty`)
})
