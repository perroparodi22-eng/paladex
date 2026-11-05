// FE-5: on an empty or partly filled database the empty states must say what has (not) been
// collected, never claim that a country "has not declared" data nobody has checked.
// FE-6: an unknown address is a broken link, not a section "in development · Milestone 0 / 404".
// FE-8: "e altre 1 fonti" is bad Italian: one hidden source reads "e un'altra fonte".
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { BlockEmpty } from '@/components/overview/parts'
import type { Provider } from '@/components/overview/types'
import countries from '@/i18n/pages/countries'
import trade from '@/i18n/pages/trade'
import Later from '@/pages/Later'
import { hrefs, render, text } from './helpers'

test('trade empty states describe collection, not what a country declared', () => {
  const strings = [
    ['it', countries.it['trade.noDeclared']], ['en', countries.en['trade.noDeclared']],
    ['it', trade.it['leaders.noExports']], ['en', trade.en['leaders.noExports']],
    ['it', trade.it['leaders.noImports']], ['en', trade.en['leaders.noImports']],
  ]
  for (const [lang, s] of strings) {
    assert.ok(s, 'string exists')
    assert.doesNotMatch(s, /ha dichiarato|non ha dichiarato|has not declared|has declared|have declared/i, s)
    assert.match(s, lang === 'it' ? /raccolt/ : /collected/, s)
  }
})

test('an unknown address says "page not found", not "in development"', () => {
  for (const lang of ['it', 'en'] as const) {
    const html = render(<Later section="nonexistent" />, { url: '/nonexistent', lang })
    const body = text(html)
    assert.doesNotMatch(body, /Milestone|404|In sviluppo|In development/i)
    assert.match(body, lang === 'it' ? /Pagina non trovata/ : /Page not found/)
    assert.ok(hrefs(html).includes('/'), 'offers a way back to the overview')
  }
})

test('a planned section still shows its milestone', () => {
  assert.match(text(render(<Later section="harvest" />, { url: '/raccolti' })), /Milestone 5/)
})

const provider = (publisher: string): Provider => ({ key: publisher, name: publisher, publisher, enabled: true } as unknown as Provider)

test('one hidden source is named in correct Italian and English', () => {
  const four = ['CCIAA Arezzo-Siena', 'CCIAA Cuneo', 'ISMEA', 'USDA'].map(provider)
  const it = text(render(<BlockEmpty what="Prezzi" providers={four} fallbackSources="—" />))
  assert.doesNotMatch(it, /altre 1 fonti/)
  assert.match(it, /CCIAA Arezzo-Siena, CCIAA Cuneo, ISMEA e un’altra fonte/)
  const en = text(render(<BlockEmpty what="Prices" providers={four} fallbackSources="—" />, { lang: 'en' }))
  assert.doesNotMatch(en, /and 1 more sources/)
  assert.match(en, /ISMEA and one more source/)
  const five = [...four, provider('FAO')]
  assert.match(text(render(<BlockEmpty what="Prezzi" providers={five} fallbackSources="—" />)), /ISMEA e altre 2 fonti/)
})
