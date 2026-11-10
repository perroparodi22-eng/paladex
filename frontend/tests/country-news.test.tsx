// Round of 10 Nov 2026: the country page leads its news with the one or two trade stories that matter
// most (exports, imports, prices), the simple view shows them too, and small display fixes found in
// the review (a change that rounds to zero carries no sign; value-only countries never read "— t").
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ProfileNews } from '@/components/countries/ProfileSections'
import type { CountryProfile, NewsItem } from '@/components/countries/types'
import { fmtPct } from '@/lib/format'
import { render, text } from './helpers'

const SRC = { key: 'news_ua_landlord_med', name: 'Landlord – miele (Ucraina)', name_en: 'Landlord – honey (Ukraine)', publisher: 'Landlord', reliability: 'trade_press', homepage: null }

function item(over: Partial<NewsItem>): NewsItem {
  return {
    id: 1, title: 'Titolo', title_it: null, title_en: null, language: 'it', publisher: 'Landlord', url: 'https://example.org/a',
    published_at: '2026-04-20T08:00:00', collected_at: '2026-11-10T08:00:00', snippet: null, summary_it: null, summary_en: null,
    ai_model: null, relevance_score: 80, duplicate_count: 0, topics: ['trade'], source: SRC, is_demo: false,
    topic_labels: { it: ['Commercio, export e import'], en: ['Trade, exports & imports'] },
    ...over,
  }
}

function profile(news: Partial<CountryProfile['news']>): CountryProfile {
  return {
    country: { iso3: 'UKR', name_it: 'Ucraina', name_en: 'Ukraine' },
    news: { available: true, items: [], count_30d: 0, days: 30, link: '/notizie?country=UKR', providers: [], ...news },
  } as unknown as CountryProfile
}

const TOP = item({ id: 10, title: 'Експорт українського меду може скоротитися', language: 'uk' })
const TOP_AI = item({ id: 11, title: 'Grain Alliance планує увійти в медовий бізнес', language: 'uk', title_it: 'Grain Alliance entra nel settore del miele', published_at: '2026-03-06T08:00:00' })
const PLAIN = item({ id: 12, title: 'Come preparare le api all\'inverno', language: 'it', topics: ['colony_health'], topic_labels: { it: ['Apicoltura e salute degli alveari'], en: ['Beekeeping & colony health'] }, published_at: '2026-11-08T08:00:00' })

test('country news: the trade stories lead, then the latest; nothing is listed twice', () => {
  const html = render(<ProfileNews p={profile({ highlights: [TOP, TOP_AI], items: [PLAIN, TOP, TOP_AI] })} />)
  const s = text(html)
  assert.match(s, /Export, import e prezzi: le più importanti/)
  assert.ok(s.indexOf('Експорт українського меду') < s.indexOf('Ultime notizie'))
  assert.ok(s.indexOf('Ultime notizie') < s.indexOf('Come preparare le api'))
  assert.equal(s.split('Експорт українського меду').length - 1, 1)
  // a headline in another language says what it is about, and an AI translation is labelled
  assert.match(s, /· uk · Commercio, export e import/)
  assert.match(s, /Grain Alliance entra nel settore del miele IA/)
  assert.match(html, /title="Grain Alliance планує увійти в медовий бізнес"/)
  assert.match(s, /20 apr 2026/)                       // every story carries its own date
  assert.match(html, /href="\/notizie\?country=UKR"/)
})

test('country news, simple view: only the one or two trade stories, or the two latest when there is none', () => {
  const withTop = text(render(<ProfileNews compact p={profile({ highlights: [TOP], items: [PLAIN, TOP] })} />))
  assert.match(withTop, /Експорт українського меду/)
  assert.doesNotMatch(withTop, /Come preparare le api/)
  const without = text(render(<ProfileNews compact p={profile({ highlights: [], items: [PLAIN, item({ id: 13, title: 'Seconda' }), item({ id: 14, title: 'Terza' })] })} />))
  assert.match(without, /Come preparare le api/)
  assert.match(without, /Seconda/)
  assert.doesNotMatch(without, /Terza/)
  assert.doesNotMatch(without, /le più importanti/)
  // no news at all: the simple view shows no empty panel (the full view explains which sources would bring news)
  assert.equal(render(<ProfileNews compact p={profile({ available: false, items: [], highlights: [] })} />), '')
  assert.match(text(render(<ProfileNews p={profile({ available: false, items: [], highlights: [] })} />)), /Notizie che citano il paese/)
})

test('an answer from an older backend (no highlights field) still shows the latest news', () => {
  const s = text(render(<ProfileNews p={profile({ items: [PLAIN] })} />))
  assert.match(s, /Come preparare le api/)
  assert.doesNotMatch(s, /le più importanti/)
})

test('a change that rounds to zero has no sign', () => {
  assert.equal(fmtPct(0.04, 'it'), '0,0%')
  assert.equal(fmtPct(-0.04, 'it'), '0,0%')
  assert.equal(fmtPct(0, 'it'), '0,0%')
  assert.equal(fmtPct(0.05, 'it'), '+0,1%')
  assert.equal(fmtPct(-0.06, 'it'), '−0,1%')
  assert.equal(fmtPct(-12.34, 'en'), '−12.3%')
})

test('old news is never shown as current: the panel says the month of the newest article', () => {
  const OLD = item({ id: 20, title: 'La miel de Colombia cumple altos estándares internacionales', language: 'es', published_at: '2022-07-12T14:00:00' })
  const old = profile({ highlights: [OLD], items: [OLD], latest_at: '2022-07-12T14:00:00' })
  ;(old as { today: string }).today = '2026-11-10'
  const s = text(render(<ProfileNews compact p={old} />))
  assert.match(s, /Nessuna notizia recente sul miele di questo paese: la più recente trovata è di luglio 2022\./)
  assert.match(s, /La miel de Colombia/)
  assert.match(s, /12 lug 2022/)
  assert.match(text(render(<ProfileNews p={old} />, { lang: 'en' })), /the latest one found is from July 2022\./)
  // recent news carries no such note
  const fresh = profile({ highlights: [TOP], items: [TOP], latest_at: '2026-10-20T08:00:00' })
  ;(fresh as { today: string }).today = '2026-11-10'
  assert.doesNotMatch(text(render(<ProfileNews p={fresh} />)), /Nessuna notizia recente/)
})
