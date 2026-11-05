// Assistant page (/assistente): answers rendered from the API response.
// - Retrieval-only answer: section headings with status badges, one citation chip per fact that opens
//   the original document (or the app page) and names source and date, the "no AI" label and how to
//   enable the AI; a DEMO answer is badged.
// - AI answer: the AI's text is badged as AI, analysis / outlook sections carry the "Analisi IA" label,
//   the automatic check says how many sentences were removed, warnings are shown.
// - The eight suggested questions in Italian and English, the AI status panel and the page shell.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AiKeyPanel } from '@/components/assistant/AiKeyPanel'
import { AnswerView } from '@/components/assistant/AnswerView'
import { isAboutOffers } from '@/components/assistant/AskBox'
import { AiStatusPanel, Suggestions } from '@/components/assistant/SidePanels'
import type { Answer, AssistantFact, AssistantStatus } from '@/components/assistant/types'
import Assistant, { TurnView } from '@/pages/Assistant'
import { fmtDate } from '@/lib/format'
import { setMirrorMode } from '@/lib/mirror'
import { hrefs, newQueryClient, render, text } from './helpers'

function fact(o: Partial<AssistantFact>): AssistantFact {
  return {
    id: 1, kind: 'price', title: 'Argentina · Millefiori (bianco) · prezzo all\'ingrosso (sfuso)',
    text: 'Argentina · Millefiori (bianco) — prezzo all\'ingrosso (sfuso), mercato: Stati Uniti: 3,91 USD/kg, set 2026.',
    status: 'verified_official', status_label: 'Dato ufficiale verificato',
    source: { key: 'usda_honey_report', name: 'USDA AMS – National Honey Report', publisher: 'USDA AMS', reliability: 'official', homepage: null },
    source_name: 'USDA AMS', url: 'https://www.ams.usda.gov/mnreports/fvmhoney.pdf', link: '/prezzi?origin=ARG',
    published_at: '2026-10-30', period_label: '2026-09', unit: 'USD/kg', data_status: 'published', reliability: 'official',
    is_demo: false, private: false, country: 'ARG', price_type: 'wholesale_bulk', change_pct: null, ...o,
  }
}

const understood = {
  mode: 'country', countries: [{ iso3: 'ARG', name: 'Argentina' }], eu: false, jurisdictions: [], varieties: [],
  price_types: [], topics: [{ key: 'prices', name: 'prezzi' }], flow: null, direction: null, period: null, years: [],
  sources: [], llm_entities: false,
}

function plainAnswer(o: Partial<Answer> = {}): Answer {
  const eu = fact({ id: 2, title: 'Argentina · valore unitario import (dogana)', status: 'provisional', status_label: 'Dato provvisorio',
    text: 'Argentina — valore unitario import (dogana), mercato: Unione Europea (CIF): 2,50 EUR/kg, ago 2026.',
    source_name: 'Eurostat', url: 'https://ec.europa.eu/eurostat/comext', published_at: '2026-10-16', period_label: '2026-08' })
  const news = fact({ id: 3, kind: 'news', title: 'Argentina: beekeepers expect a smaller harvest', status: 'press',
    status_label: 'Notizia (non verificata)', text: 'Honey Times, 2 nov 2026: «Argentina: beekeepers expect a smaller harvest»',
    source_name: 'Honey Times', url: 'https://news.example.org/1', link: '/notizie', published_at: '2026-11-02', period_label: null })
  const old = fact({ id: 4, status: 'historical', status_label: 'Dato storico', text: 'Argentina — valore unitario export 2024: 2,20 USD/kg.',
    url: null, link: '/paesi/ARG', period_label: '2024' })
  return {
    id: 'abc', question: 'Cosa sta succedendo ai prezzi del miele argentino?', lang: 'it', asked_at: '2026-11-04T09:30:00',
    understood, ai_used: false, ai: { enabled: false, provider: null, model: null },
    intro: 'Ecco i dati disponibili nel database su: Argentina · prezzi.',
    sections: [
      { key: 'verified', title: 'Fatti verificati', ai: false, analysis: false, items: [
        { text: fact({}).text, refs: [1], kind: 'price', status: 'verified_official' },
        { text: eu.text, refs: [2], kind: 'price', status: 'provisional' }] },
      { key: 'historical', title: 'Contesto storico', ai: false, analysis: false, items: [{ text: old.text, refs: [4], status: 'historical' }] },
      { key: 'news', title: 'Notizie', ai: false, analysis: false, items: [{ text: news.text, refs: [3], kind: 'news', status: 'press' }] },
    ],
    facts: [fact({}), eu, news, old],
    notes: ['Nessuna notizia su Argentina negli ultimi 30 giorni nel database.'], warnings: [], is_demo: false,
    insufficient: false, insufficient_note: null, checks: null,
    how_to_enable: { file: '.env', lines: ['PALADEX_LLM_PROVIDER=anthropic', 'PALADEX_ANTHROPIC_API_KEY=…'], alternative: [],
      text: 'Per attivare l\'analisi IA, aggiungere al file .env …' },
    private_data_used: false, sent_private_to_ai: false, ...o,
  }
}

function aiAnswer(): Answer {
  const base = plainAnswer()
  return {
    ...base, ai_used: true, ai: { enabled: true, provider: 'anthropic', model: 'claude-sonnet-5-5' }, how_to_enable: undefined,
    intro: 'Risposta redatta dall\'IA solo con i 4 dati recuperati dal database (Argentina · prezzi).',
    sections: [
      { key: 'verified', title: 'Fatti verificati', ai: true, analysis: false, items: [
        { text: 'Il prezzo all\'ingrosso negli Stati Uniti del millefiori bianco argentino era 3,91 USD/kg a settembre 2026.', refs: [1] },
        { text: 'Il valore unitario all\'import nell\'UE, provvisorio, era 2,50 EUR/kg ad agosto 2026.', refs: [2] }] },
      { key: 'analysis', title: 'Analisi (IA)', ai: true, analysis: true, items: [{ text: 'Il miele argentino resta richiesto.', refs: [1, 2] }] },
      { key: 'forecast', title: 'Previsioni (IA, incerte)', ai: true, analysis: true, items: [{ text: 'I prezzi potrebbero restare sostenuti.', refs: [] }] },
    ],
    checks: { sentences: 5, dropped: 1, dropped_items: [{ text: 'x', reason: 'invented_number', numbers: ['2,95'] }], rejected: false },
    warnings: ['1 frase della risposta dell\'IA è stata rimossa perché conteneva numeri o citazioni non verificabili sulle fonti.'],
  }
}

test('retrieval-only answer: sections, badges, citation chips that open the source', () => {
  const html = render(<AnswerView answer={plainAnswer()} />)
  const body = text(html)
  assert.match(body, /Dati dal database · senza IA/)
  assert.match(body, /Ecco i dati disponibili nel database su: Argentina · prezzi\./)
  assert.match(body, /Ho cercato: Argentina prezzi/)
  for (const h of ['Fatti verificati', 'Contesto storico', 'Notizie']) assert.match(body, new RegExp(h))
  assert.match(body, /Dato verificato/)
  assert.match(body, /Dato storico/)
  assert.match(body, /Stampa · non verificato/)
  assert.match(body, /Provvisorio/, 'a provisional figure is tagged inside the verified section')
  assert.doesNotMatch(html, /bg-\[#EEEAF6\]/, 'no AI badge on an answer without AI')
  assert.doesNotMatch(body, /Testo IA|Risposta scritta dall'IA|Analisi \(IA\)/)
  assert.match(body, /Analisi IA non attiva\. Per attivare l'analisi IA, aggiungere al file \.env/)
  assert.match(body, /Nessuna notizia su Argentina negli ultimi 30 giorni/)
  // chip [1] opens the original document and names source, date and period
  const links = hrefs(html)
  assert.ok(links.includes('https://www.ams.usda.gov/mnreports/fvmhoney.pdf'))
  assert.ok(links.includes('/paesi/ARG'), 'a fact without a document URL opens its page in the app')
  const published = fmtDate('2026-10-30', 'it')
  assert.ok(html.includes(`aria-label="[1] USDA AMS · Pubblicato ${published} · Periodo set 2026 · Dato ufficiale verificato"`), html)
  assert.match(body, /Fonti citate \(4\)/)
  assert.doesNotMatch(body, /DEMO/)
  assert.match(text(render(<AnswerView answer={plainAnswer({ is_demo: true })} />)), /DEMO/)
})

test('AI answer: AI text and analysis are labelled, removed sentences are reported', () => {
  const body = text(render(<AnswerView answer={aiAnswer()} />))
  assert.match(body, /Risposta scritta dall'IA/)
  assert.match(body, /Dato verificato/)
  assert.match(body, /Testo IA/)
  assert.match(body, /Analisi \(IA\)/)
  assert.match(body, /Analisi IA/)
  assert.match(body, /Previsioni \(IA, incerte\)/)
  assert.match(body, /Previsione IA · incerta/)
  assert.match(body, /Controllo automatico: 4 frasi verificate sui dati citati, 1 rimosse/)
  assert.match(body, /1 frase della risposta dell'IA è stata rimossa/)
  assert.doesNotMatch(body, /PALADEX_LLM_PROVIDER/)
  const en = text(render(<AnswerView answer={{ ...aiAnswer(), lang: 'en' }} />, { lang: 'en' }))
  assert.match(en, /Answer written by the AI/)
  assert.match(en, /AI outlook · uncertain/)
  assert.match(en, /Cited sources \(4\)/)
})

test('suggested questions in Italian and English', () => {
  const it = text(render(<Suggestions onPick={() => {}} />))
  for (const q of ['Cosa sta succedendo ai prezzi del miele argentino?', 'Confronta Argentina e Ucraina',
    'Quali paesi hanno aumentato le esportazioni quest\'anno?', 'Ultime notizie sul mercato cinese',
    'Cosa è successo questa settimana nel mercato mondiale?', 'Quali sviluppi recenti possono influire sui nostri costi di acquisto?',
    'Riassumi l\'ultimo report USDA', 'Confronta queste tre offerte']) assert.ok(it.includes(q), q)
  const en = text(render(<Suggestions onPick={() => {}} />, { lang: 'en' }))
  assert.ok(en.includes('Summarize the latest USDA report') && en.includes('Compare these three offers'))
  assert.ok(isAboutOffers('Confronta queste tre offerte') && isAboutOffers('Compare these three offers'))
  assert.ok(!isAboutOffers('Confronta Argentina e Ucraina'))
})

const status: AssistantStatus = {
  llm_enabled: false, provider: null, model: null, provider_configured: false, key_missing: false,
  how_to_enable: {
    it: { file: '.env', lines: ['PALADEX_LLM_PROVIDER=anthropic', 'PALADEX_ANTHROPIC_API_KEY=…'], alternative: [], text: 'Per attivare l\'analisi IA…' },
    en: { file: '.env', lines: ['PALADEX_LLM_PROVIDER=anthropic', 'PALADEX_ANTHROPIC_API_KEY=…'], alternative: [], text: 'To enable AI analysis…' },
  },
  briefing: { date: '2026-11-04', schedule: '07:00', items: [] }, history_count: 0, quotes_count: 0,
  limits: { max_facts: 36, news_days: 30, question_max_chars: 1000 },
}

test('AI status: honest when not configured, with how to enable it', () => {
  const off = text(render(<AiStatusPanel status={status} />))
  assert.match(off, /Intelligenza artificiale non configurata/)
  assert.match(off, /risponde comunque, con i dati recuperati dal database/)
  assert.match(off, /PALADEX_ANTHROPIC_API_KEY/)
  const on = text(render(<AiStatusPanel status={{ ...status, llm_enabled: true, provider: 'anthropic', model: 'claude-sonnet-5-5' }} />))
  assert.match(on, /Intelligenza artificiale attiva/)
  assert.match(on, /anthropic · claude-sonnet-5-5/)
})

test('page: welcome with the suggestions; a pending turn and an answered one', () => {
  const qc = newQueryClient()
  qc.setQueryData(['assistant', 'status'], status)
  qc.setQueryData(['assistant', 'history'], { items: [{ id: 'abc', asked_at: '2026-11-04T09:30:00', question: 'Confronta Argentina e Ucraina', lang: 'it', ai_used: false, facts: 19, insufficient: false }], count: 1, max: 40 })
  const page = text(render(<Assistant />, { url: '/assistente', qc }))
  assert.match(page, /Assistente di mercato/)
  assert.match(page, /Che cosa vuoi sapere\?/)
  assert.match(page, /Domande suggerite/)
  assert.match(page, /Intelligenza artificiale non configurata/)
  assert.match(page, /Domande precedenti/)
  assert.match(page, /19 dati/)
  assert.match(page, /La tua domanda/)
  const pending = text(render(<TurnView turn={{ key: 'k', question: 'Confronta Argentina e Ucraina', pending: true }} aiEnabled={false}
    onRetry={() => {}} onRemove={() => {}} />))
  assert.match(pending, /Cerco nel database…/)
  const done = text(render(<TurnView turn={{ key: 'k', question: 'Q', pending: false, answer: plainAnswer() }} aiEnabled={false}
    onRetry={() => {}} onRemove={() => {}} />))
  assert.match(done, /Fatti verificati/)
})

test('AI service and key on screen: provider choice, a password field, paid per use, offers anonymised', () => {
  const html = render(<AiStatusPanel status={{ ...status, provider_setting: 'none', keys_saved: { anthropic: false, openai: false } }} />)
  const off = text(html)
  assert.match(off, /Anthropic \(Claude\) OpenAI Nessuno \(IA spenta\)/)
  assert.match(off, /Servizio a pagamento: il fornitore scelto addebita sul tuo conto ogni uso/)
  assert.match(off, /offerte dei fornitori sono inviate solo quando la domanda riguarda le offerte, e in forma anonima/)
  assert.match(off, /non viene mai mostrata di nuovo/)
  assert.doesNotMatch(html, /type="password"/)                // no service chosen yet: no key field
  // a service chosen with its key saved: a password field (empty), never the key
  const chosen = render(<AiStatusPanel status={{ ...status, provider_setting: 'anthropic', provider_configured: true, key_missing: false,
    llm_enabled: true, provider: 'anthropic', model: 'claude-sonnet-5-5', keys_saved: { anthropic: true, openai: false } }} />)
  assert.match(text(chosen), /Cambia servizio o chiave/)
  const qc = newQueryClient()
  qc.setQueryData(['assistant', 'status'], { ...status, provider_setting: 'openai', provider_configured: true, key_missing: true,
    keys_saved: { anthropic: false, openai: false } })
  const panel = render(<AiKeyPanel />, { qc, lang: 'en' })
  assert.match(panel, /type="password"/)
  assert.match(text(panel), /AI service and key/)
  assert.match(text(panel), /No key saved for this service/)
  assert.match(text(panel), /Paid service: the chosen provider charges your account for every use/)
  assert.match(text(panel), /sent only when the question is about offers, and anonymised/)
  setMirrorMode(true)
  try {
    assert.equal(render(<AiKeyPanel />, { qc }), '')           // never in the read-only online copy
  } finally {
    setMirrorMode(null)
  }
})
