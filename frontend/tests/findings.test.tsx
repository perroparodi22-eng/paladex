// Country page, "Altre fonti (non ufficiali)": recent figures found on the web, each checked by Paladex
// on the page it cites, apart from the official data; the empty state says what was searched; the
// Sources page switch of the optional AI web search shows an honest cost and is hidden in the online copy.
// tests/fixtures/findings-*.json are the real `web_findings` blocks of /api/countries/{BRA,CHN,THA}
// and /api/findings/ai after a live run of the web_findings collector on 06 Nov 2026 (scratch copy of the
// live database, seed of 06 Nov 2026).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ProfileWebFindings } from '@/components/findings/ProfileWebFindings'
import type { AiStatus, WebFindingsBlock } from '@/components/findings/types'
import { WebFindingsAiBody, WebFindingsAiPanel } from '@/components/findings/WebFindingsAiPanel'
import { setMirrorMode } from '@/lib/mirror'
import braJson from './fixtures/findings-BRA.json'
import chnJson from './fixtures/findings-CHN.json'
import thaJson from './fixtures/findings-THA.json'
import aiJson from './fixtures/findings-ai.json'
import { hrefs, newQueryClient, render, text } from './helpers'

const BRA = braJson as unknown as WebFindingsBlock
const CHN = chnJson as unknown as WebFindingsBlock
const THA = thaJson as unknown as WebFindingsBlock
const AI = aiJson as unknown as AiStatus
const page = (iso3: string, b?: WebFindingsBlock) => ({ country: { iso3 }, web_findings: b })

test('the panel: per metric, the value as published, period, status, non-official badge, publisher, quote, link', () => {
  const html = render(<ProfileWebFindings p={page('BRA', BRA)} />)
  const s = text(html)
  assert.match(s, /Altre fonti \(non ufficiali\)/)
  assert.match(s, /Dati recenti trovati sul web/)
  assert.match(s, /ciascuno verificato da Paladex sulla pagina che cita/)
  assert.match(s, /Non sono statistiche ufficiali e non vengono mai sommati ai dati ufficiali/)
  // metrics in order, newest first within a metric
  const pos = (re: RegExp) => s.search(re)
  assert.ok(pos(/Produzione 71,3 mil toneladas/) < pos(/Esportazioni US\$ 42,09 milhões/))
  assert.ok(pos(/Esportazioni US\$ 42,09 milhões/) < pos(/US\$ 116,472 milhões/))
  assert.ok(pos(/US\$ 116,472 milhões/) < pos(/Prezzo all’esportazione/))
  // value as published, the number it means, period as published
  assert.match(s, /71,3 mil toneladas = 71\.300 t Periodo: 2025/)
  assert.match(s, /12\.022 toneladas = 12\.022 t Periodo: 2026-01–2026-05/)
  assert.match(s, /US\$ 3,50 por quilo = 3,50 USD\/kg/)
  // IBGE figure published by the federal government's agency: an official publication, not in a series
  assert.match(s, /Dato ufficiale definitivo Pubblicazione ufficiale, non in serie statistica/)
  assert.match(s, /Agência Gov \(Brazilian federal government news agency, EBC\), reporting IBGE/)
  assert.match(s, /pubblicato il 30 set 2026/)
  // trade press reporting official figures: non-official, and said so
  assert.match(s, /Dato ufficiale provvisorio Non ufficiale Cifra attribuita a una fonte ufficiale dalla pagina citata\./)
  assert.match(s, /Agrolink, reporting the Boletim Conjuntural .* Stampa di settore/)
  // the quote (expandable) and the page it was checked on
  assert.match(html, /<details/)
  assert.match(s, /Frase citata “A produção nacional de mel cresceu 4,5% em 2025, totalizando 71,3 mil toneladas/)
  assert.match(html, /<blockquote[^>]*lang="pt"/)
  assert.ok(hrefs(html).includes('https://agenciagov.ebc.com.br/noticias/202609/quantidade-do-gado-diminui-e-produtividade-aumenta-na-agropecuaria-mostra-ibge'))
  assert.match(s, /Apri la pagina \(agenciagov\.ebc\.com\.br\)/)
  assert.match(s, /Verificato da Paladex sulla pagina il 06 nov 2026/)
  assert.match(s, /Riportato anche da \(non verificato\): movimentoeconomico\.com\.br/)
  assert.match(s, /7 dati verificati/)
  assert.ok(hrefs(html).includes('/fonti#web_findings'))
  // only the pages themselves are linked: no mapped "official page" substitute
  for (const h of hrefs(html).filter((x) => x.startsWith('http'))) assert.ok(!h.includes('comexstat'), h)
})

test('English, other scripts and units as published', () => {
  const s = text(render(<ProfileWebFindings p={page('CHN', CHN)} />, { lang: 'en' }))
  assert.match(s, /Other sources \(non-official\)/)
  assert.match(s, /each checked by Paladex on the page it cites/)
  assert.match(s, /They are not official statistics and are never added to the official figures/)
  assert.match(s, /17\.55 万t = 175,500 t Period: 2025/)
  assert.match(s, /Reported figure Non-official/)
  assert.match(s, /Trade press/)
  assert.match(s, /Quoted sentence/)
  assert.match(s, /Open the page \(fsc\.foodmate\.net\)/)
  assert.match(s, /Checked by Paladex on the page on 06 Nov 2026/)
})

test('badges: forecast, estimate, official estimate; AI-found; a failed later check keeps the figure and says so', () => {
  const base = BRA.metrics[0].findings[0]
  const b: WebFindingsBlock = {
    ...BRA, count: 3,
    metrics: [{
      metric: 'production', count: 3, findings: [
        { ...base, id: 1, status: 'forecast', kind: 'usda_fas', is_official: true, publisher: 'USDA FAS' },
        { ...base, id: 2, status: 'estimate', kind: 'association', is_official: false, publisher: 'ABEMEL',
          found_by: 'ai_web_search', ai_model: 'claude-haiku-5-5' },
        { ...base, id: 3, status: 'official_estimate', kind: 'news', is_official: false, publisher: 'Some news',
          last_check: { at: '2026-12-08T09:40:00', ok: false, reason: 'unreachable', detail: 'page not found (HTTP 404)', doc_type: null, number_in_quote: null } },
      ],
    }],
  }
  const s = text(render(<ProfileWebFindings p={page('BRA', b)} />))
  assert.match(s, /Previsione Pubblicazione ufficiale, non in serie statistica/)
  assert.match(s, /Stima Non ufficiale Trovato dalla ricerca IA/)
  assert.match(s, /Stima ufficiale Non ufficiale Cifra attribuita a una fonte ufficiale/)
  assert.match(s, /Ultimo controllo non riuscito il 0?8 dic 2026 \(pagina non raggiungibile\): il dato resta come verificato il 06 nov 2026\./)
  // never the word "official" alone on a non-official figure
  assert.equal((s.match(/Non ufficiale/g) ?? []).length, 2)
})

test('empty state: "no recent figures found" and what was searched', () => {
  const s = text(render(<ProfileWebFindings p={page('THA', THA)} />))
  assert.match(s, /Altre fonti \(non ufficiali\)/)
  assert.match(s, /Nessun dato recente trovato/)
  assert.match(s, /Ricerca sul web del 06 nov 2026/)
  assert.match(s, /Cosa è stato cercato: Thai-language and English searches for 2025\/2026 honey/)
  assert.match(s, /Esito: No 2025 or 2026 national honey figure found\./)
  const none = text(render(<ProfileWebFindings p={page('ISL', { ...THA, not_found: [] })} />, { lang: 'en' }))
  assert.match(none, /No recent figures found No web search has been made for this country yet\./)
  // an answer recorded before the feature (online copy): nothing is claimed
  assert.equal(render(<ProfileWebFindings p={page('BRA')} />), '')
})

test('Sources page: the AI web search is off by default, with the prices used, their date and the cap', () => {
  assert.equal(AI.enabled, false)
  const s = text(render(<WebFindingsAiBody s={AI} />))
  assert.match(s, /Ricerca web settimanale con IA \(facoltativa\)/)
  assert.match(s, /Disattivata \(impostazione iniziale\)/)
  assert.match(s, /salva il dato solo se vi trova la frase citata e il numero/)
  assert.match(s, /mai il nome dell’azienda, le offerte dei fornitori/)
  assert.match(s, /Funziona solo con Anthropic \(Claude\)\. Con OpenAI la ricerca web non è supportata\./)
  assert.match(s, /Serve una chiave Anthropic \(Claude\)/)
  assert.match(s, /circa 0,26 \$ per settimana \(al massimo 20 ricerche\)/)
  assert.match(s, /circa 1,13 \$ al mese/)
  assert.match(s, /listino Claude API al 05 nov 2026\): ricerca web 10 \$ ogni 1\.000 ricerche; Claude Haiku 5\.5: 0,10 \$ per milione di token in ingresso, 0,50 \$ per milione in uscita/)
  assert.match(s, /circa 20\.000 token in ingresso e 2\.000 in uscita per ricerca; 4,33 esecuzioni al mese/)
  assert.match(s, /Nessuna esecuzione registrata\./)
  const html = render(<WebFindingsAiBody s={AI} />)
  assert.match(html, /role="switch" aria-checked="false" disabled=""/)     // no key: cannot be switched on
  const on: AiStatus = {
    ...AI, enabled: true, enabled_by: 'setting', unavailable: null, will_run: true,
    runs: [{ at: '2026-11-08T09:41:00', model: 'claude-haiku-5-5', searches: 18, cost_usd: 0.214, cost_known: true,
      countries: [{ iso3: 'ITA', searches: 3, proposed: 4, stored: 1 }], proposed: 9, stored: 3, error: null }],
  }
  const en = text(render(<WebFindingsAiBody s={on} />, { lang: 'en' }))
  assert.match(en, /Weekly AI web search \(optional\)/)
  assert.match(en, /about 0\.26 \$ per week \(at most 20 searches\)/)
  assert.match(en, /08 Nov 2026: 18 searches, 0\.214 \$ · countries: 1 · 3 figures verified of 9 proposed/)
  assert.match(render(<WebFindingsAiBody s={on} />), /role="switch" aria-checked="true"/)
})

test('the AI switch never appears in the read-only online copy', () => {
  const qc = newQueryClient()
  qc.setQueryData(['findings-ai'], AI)
  assert.match(text(render(<WebFindingsAiPanel />, { qc })), /Ricerca web settimanale con IA/)
  setMirrorMode(true)
  try {
    assert.equal(render(<WebFindingsAiPanel />, { qc }), '')
    // the country panel still renders from the recorded country answer
    assert.match(text(render(<ProfileWebFindings p={page('BRA', BRA)} />)), /71,3 mil toneladas/)
  } finally {
    setMirrorMode(null)
  }
})
