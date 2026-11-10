// The father's correction box (owner's request, 6 Nov 2026): "Segnala o correggi" on a figure, the
// "Scrivi a Paladex" box (his words -> the AI's proposal "valore attuale -> correzione" -> Conferma),
// the plain form without an AI key, "Corretto da <nome> il <data>" with the official value and undo,
// notes on country pages, notices (conflict, source published a new value, waiting), sync status.
// The read-only phone copy shows the badges, never an action. API: backend/paladex/api/corrections.py.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { ReactNode } from 'react'
import { AnswerView } from '@/components/assistant/AnswerView'
import type { Answer, AssistantFact } from '@/components/assistant/types'
import { errorText } from '@/components/corrections/api'
import { CorrectionBadge } from '@/components/corrections/CorrectionBadge'
import { CorrectionsList, CountryNotes } from '@/components/corrections/CorrectionsPanel'
import { FigureForm } from '@/components/corrections/FigureDialog'
import { editBasis, FixValue, inputText, parseTyped, QuickFixForm } from '@/components/corrections/QuickFix'
import { fmtFigureValue, typedNumber } from '@/components/corrections/format'
import { CandidateView, SyncStatus, SyncSwitch } from '@/components/corrections/parts'
import type { Candidate, CorrectionBrief, CorrectionEvent, FigureRef } from '@/components/corrections/types'
import { WriteBox } from '@/components/corrections/WriteBox'
import { SimpleOverview } from '@/components/simple/SimpleOverview'
import { SourceChip } from '@/components/simple/SourceChip'
import type { OverviewData } from '@/components/overview/types'
import { SourceLine } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { setMirrorMode } from '@/lib/mirror'
import { ViewProvider } from '@/lib/view'
import meta from './fixtures/meta-simple.json'
import overview from './fixtures/overview-simple.json'
import { newQueryClient, render, text } from './helpers'

const BRIEF: CorrectionBrief = {
  event_id: '43831269-2249-46ef-a9ac-c9f069c04dc0', author: 'Papà', created_at: '2026-11-06T01:28:05Z',
  reason: 'offerta ricevuta il 3 novembre: 2,10 USD/lb', field: 'price_value', official_value: 2.04, corrected_value: 2.1,
  unit: 'lb', currency: 'USD',
}
const FIGURE: FigureRef = {
  table: 'price_observations', row_id: 2604, label: 'Argentina · prezzo all\'ingrosso (fusti) negli USA · millefiori, bianco · set 2026',
  value: 1.775, unit: 'lb', currency: 'USD', country_iso3: 'ARG', period_label: '2026-09',
}
const USDA = { key: 'usda_honey_report', name: 'USDA AMS – National Honey Report (prezzi miele USA)', publisher: 'USDA Agricultural Marketing Service (AMS)', reliability: 'official', homepage: null }

function qcWith(llm: boolean, extra: [unknown[], unknown][] = []) {
  const qc = newQueryClient()
  qc.setQueryData(['meta'], { ...meta, flags: { ...meta.flags, llm_enabled: llm } })
  qc.setQueryData(['corrections', 'settings'], { author: 'Papà', default_author: 'Utente' })
  qc.setQueryData(['corrections', 'sync'], { enabled: true, pending: 1, running: false, last_push_at: null, last_pull_at: null, error: null })
  for (const [k, v] of extra) qc.setQueryData(k, v)
  return qc
}

function show(node: ReactNode, opts: { lang?: 'it' | 'en'; qc?: ReturnType<typeof newQueryClient>; url?: string } = {}) {
  return render(<ViewProvider initial="simple">{node}</ViewProvider>, { lang: opts.lang ?? 'it', qc: opts.qc ?? qcWith(false), url: opts.url })
}

function mirror<T>(fn: () => T): T {
  setMirrorMode(true)
  try {
    return fn()
  } finally {
    setMirrorMode(null)
  }
}

test('"Corretto da Papà il 6 nov 2026", the official value, the reason and undo; the phone copy shows no undo', () => {
  const it = text(show(<CorrectionBadge c={BRIEF} />))
  assert.match(it, /Corretto da Papà il 6 nov 2026 · valore della fonte: 2,04 USD\/lb «offerta ricevuta il 3 novembre: 2,10 USD\/lb» Annulla correzione/)
  assert.match(text(show(<CorrectionBadge c={BRIEF} />, { lang: 'en' })), /Corrected by Papà on 6 Nov 2026 · source value: 2\.04 USD\/lb/)
  assert.equal(text(show(<CorrectionBadge c={BRIEF} compact />)), 'Corretto da Papà')
  const copy = mirror(() => text(show(<CorrectionBadge c={BRIEF} />)))
  assert.match(copy, /Corretto da Papà il 6 nov 2026/)
  assert.doesNotMatch(copy, /Annulla correzione/)
})

test('the source chip carries the badge and, opened, "Segnala o correggi"; never in the phone copy', () => {
  const p = { source: USDA, period_label: '2026-09', data_status: 'user_entered', correction: BRIEF }
  const closed = text(show(<SourceChip p={p} figure={FIGURE} />))
  assert.match(closed, /Fonte: USDA · set 2026 Corretto da Papà il 6 nov 2026/)
  assert.doesNotMatch(closed, /Inserito|Correggi/)          // no duplicate "user entered" badge
  const open = text(show(<SourceChip p={p} figure={FIGURE} defaultOpen />))
  assert.match(open, /Inserito dall'utente Correggi/)
  assert.doesNotMatch(text(show(<SourceChip p={{ source: USDA, period_label: '2026-09' }} defaultOpen />)), /Correggi/)  // no stored row: no action
  const copy = mirror(() => text(show(<SourceChip p={p} figure={FIGURE} defaultOpen />)))
  assert.match(copy, /Corretto da Papà/)
  assert.doesNotMatch(copy, /Correggi/)
})

test('full view: the provenance line shows the badge and "Segnala o correggi" next to it', () => {
  const out = text(show(<SourceLine p={{ source: USDA, published_at: '2026-10-30', correction: BRIEF }} figure={FIGURE} />))
  assert.match(out, /Fonte: USDA Agricultural Marketing Service \(AMS\) · Pubblicato 30 ott 2026 Correggi Corretto da Papà il 6 nov 2026/)
  assert.doesNotMatch(text(show(<SourceLine p={{ source: USDA }} />)), /Segnala|Corretto/)
})

test('the figure panel: current value with its own precision, three choices, value in any unit and currency', () => {
  const out = show(<FigureForm figure={FIGURE} />)
  const t = text(out)
  assert.match(t, /Argentina · prezzo all'ingrosso \(fusti\) negli USA · millefiori, bianco · set 2026 Valore attuale: 1,775 USD\/lb/)
  assert.match(t, /Il valore giusto è… Mi sembra sbagliato Aggiungi una nota/)
  assert.match(t, /Valore giusto .*Puoi scriverlo nell’unità e nella valuta che preferisci/)
  assert.match(out, /<option value="USD" selected="">USD<\/option>/)
  assert.match(out, /<option value="lb" selected="">lb<\/option>/)
  assert.match(t, /Conferma Il valore ufficiale della fonte resta nello storico/)
  assert.match(t, /Firmi come: Papà cambia/)
  assert.doesNotMatch(t, /Oppure scrivilo a parole/)                 // no AI key: the plain form only
  assert.match(text(show(<FigureForm figure={FIGURE} />, { qc: qcWith(true) })), /Oppure scrivilo a parole/)
  const note = text(show(<FigureForm figure={FIGURE} defaultMode="note" />))
  assert.match(note, /Paese .*Argentina.*Nota/)
  const trade = show(<FigureForm figure={{ ...FIGURE, table: 'trade_flows', value: 40_000_000, unit: 'kg', currency: null, field: 'net_weight_kg' }} />)
  assert.match(text(trade), /Valore attuale: 40\.000 t/)
  assert.doesNotMatch(trade, /<option value="USD"/)
})

const CANDIDATE: Candidate = {
  table: 'price_observations', row_id: 2603, source: USDA, label: 'Argentina · Millefiori · light amber · ingrosso (Stati Uniti) · 2026-09',
  field: 'price_value', period_label: '2026-09', current: { value: 1.77, unit: 'lb', currency: 'USD' }, correction: null, matches_old_value: true,
  provenance: { source_url: null, published_at: '2026-10-30', collected_at: null }, link: '/prezzi',
  proposal: { from: 1.77, to: 1.8, unit: 'lb', currency: 'USD', entered: { value: 1.8, unit: 'lb', currency: 'USD' },
    create: { kind: 'value_correction', target: { table: 'price_observations', row_id: 2603 }, value: 1.8, unit: 'lb', currency: 'USD' } },
  proposal_error: null,
}

test('a candidate reads "valore attuale → correzione", with the number he can change', () => {
  const out = show(<CandidateView c={CANDIDATE} selected onSelect={() => {}} value={typedNumber(1.8, 'it')} onValue={() => {}} />)
  assert.match(text(out), /Argentina · Millefiori · light amber .*Fonte: USDA · set 2026 · Pubblicato 30 ott 2026 · il valore che hai citato Valore attuale 1,77 USD\/lb → correzione USD\/lb/)
  assert.match(out, /value="1,8"/)
  const err = text(show(<CandidateView c={{ ...CANDIDATE, proposal: null, proposal_error: { code: 'fx_unavailable', message_it: 'Manca il cambio EUR/USD per questo periodo.', message_en: 'No rate.' } }}
    selected={false} onSelect={() => {}} value="" onValue={() => {}} />))
  assert.match(err, /Manca il cambio EUR\/USD per questo periodo\./)
})

test('"Scrivi a Paladex": words with an AI key; without one, how to correct from the figure and a note form; nothing in the phone copy', () => {
  const ai = show(<WriteBox />, { qc: qcWith(true) })
  assert.match(ai, /data-write-box="ai"/)
  assert.match(text(ai), /Invia Nulla cambia finché non premi «Conferma»\. Firmi come: Papà cambia Sincronizzazione: 1 correzione in attesa di invio Sincronizza ora/)
  const plain = text(show(<WriteBox />, { qc: qcWith(false) }))
  // without a key a number is fixed by tapping it: only the note on a country is left here, one tap away
  assert.match(plain, /^Lascia una nota su un paese Firmi come: Papà/)
  assert.doesNotMatch(plain, /Salva la nota/)
  assert.equal(mirror(() => show(<WriteBox />, { qc: qcWith(true) })), '')
  assert.match(text(show(<WriteBox />, { qc: qcWith(true), lang: 'en' })), /Send Nothing changes until you press “Confirm”/)
})

test('the simple Panoramica has the box as a fifth card (not in the phone copy)', () => {
  const qc = qcWith(false)
  const out = text(show(<SimpleOverview d={overview as unknown as OverviewData} />, { qc }))
  assert.match(out, /Notizie .* Scrivi a Paladex Un numero è sbagliato\? Toccalo e scrivi quello giusto\./)
  assert.doesNotMatch(mirror(() => text(show(<SimpleOverview d={overview as unknown as OverviewData} />, { qc }))), /Scrivi a Paladex/)
})

function ev(o: Partial<CorrectionEvent>): CorrectionEvent {
  return {
    event_id: 'e1', kind: 'value_correction', created_at: '2026-11-06T01:28:05Z', author: 'Papà', made_here: true, origin: 'local',
    target: { table: 'price_observations', source_key: 'usda_honey_report', series_key: 'x', period_label: '2026-09', unit: 'lb', currency: 'USD',
      field: 'price_value', country_iso3: 'BRA', label: 'Brasile · Millefiori · light amber · ingrosso (Stati Uniti) · 2026-09', row_id: 2605 },
    official_value: 2.04, corrected_value: 2.1, entered: null, normalized: null, reverts_event_id: null, reason: 'offerta ricevuta',
    text: null, ai_interpretation: null, status: 'applied', status_detail: null, applied_row_id: 40355, issue_id: null, revertible: true,
    sync: { state: 'synced', synced_at: null, error: null }, ...o,
  }
}

test('corrections list: notices first (conflict, source published a new value, waiting), each with what happened', () => {
  const items = [
    ev({ event_id: 'a' }),
    ev({ event_id: 'b', status: 'superseded_by_source', revertible: false, status_detail: { new_official_value: 2.15, unit: 'lb', currency: 'USD' } }),
    ev({ event_id: 'c', status: 'conflict', revertible: false }),
    ev({ event_id: 'd', kind: 'note', status: 'recorded', text: 'Raccolto in ritardo', reason: null, target: null, sync: { state: 'pending_sync', synced_at: null, error: null } }),
    ev({ event_id: 'e', status: 'waiting', revertible: false }),
  ]
  const qc = qcWith(false, [[['corrections', 'list', { limit: 20 }], { total: 5, items, counts: {}, pending_sync: 1, author: 'Papà' }]])
  const out = text(show(<CorrectionsList />, { qc }))
  assert.match(out, /3 correzioni da controllare\./)
  const order = ['la fonte ha pubblicato un nuovo valore \\(2,15 USD\\/lb\\)', 'non applicata: qui il valore ufficiale è diverso', 'in attesa: il dato non è ancora arrivato', 'applicata', 'nota registrata']
  assert.match(out, new RegExp(order.join('.*')))
  assert.match(out, /Brasile · Millefiori · light amber · ingrosso \(Stati Uniti\) · 2026-09: 2,04 USD\/lb → 2,10 USD\/lb «offerta ricevuta» da Papà il 6 nov 2026/)
  assert.match(out, /Raccolto in ritardo .*in attesa di invio agli altri computer/)
})

test('country notes: listed on the country page with "Aggiungi una nota"; not in the phone copy', () => {
  const note = ev({ event_id: 'n1', kind: 'note', status: 'recorded', text: 'Raccolto 2026 in ritardo per la siccità', reason: null, target: null })
  const qc = qcWith(false, [[['corrections', 'list', { kind: 'note', country: 'ARG', status: 'recorded', limit: 50 }], { total: 1, items: [note], counts: {}, pending_sync: 0, author: 'Papà' }]])
  const out = text(show(<CountryNotes iso3="ARG" name="Argentina" />, { qc }))
  assert.match(out, /Note su Argentina Aggiungi una nota Raccolto 2026 in ritardo per la siccità da Papà il 6 nov 2026 nota registrata Ritira/)
  assert.equal(mirror(() => show(<CountryNotes iso3="ARG" name="Argentina" />, { qc })), '')
})

test('sync status: pending, error message, off', () => {
  const st = (s: object) => text(show(<SyncStatus />, { qc: qcWith(false, [[['corrections', 'sync'], s]]) }))
  assert.match(st({ enabled: true, pending: 2, error: null }), /Sincronizzazione: 2 correzioni in attesa di invio Sincronizza ora/)
  assert.match(st({ enabled: true, pending: 0, error: { code: 'push_failed', message_it: 'Invio non riuscito: rete assente.', message_en: 'Push failed.' } }), /Invio non riuscito: rete assente\./)
  assert.match(st({ enabled: false, reason: 'no_remote', reason_message_it: 'Nessun archivio remoto configurato.', pending: 0 }), /Sincronizzazione: Nessun archivio remoto configurato\./)
})

test('error answers are read in the interface language', () => {
  const e = new ApiError(409, JSON.stringify({ code: 'same_as_official', message_it: 'È lo stesso valore della fonte.', message_en: 'Same as the source.' }))
  assert.equal(errorText(e, 'it'), 'È lo stesso valore della fonte.')
  assert.equal(errorText(e, 'en'), 'Same as the source.')
  assert.equal(errorText(new Error('boom'), 'it'), 'boom')
})

test('values read with their own precision and unit', () => {
  assert.equal(fmtFigureValue(1.775, 'lb', 'USD', 'it'), '1,775 USD/lb')
  assert.equal(fmtFigureValue(2.04, 'lb', 'USD', 'it'), '2,04 USD/lb')
  assert.equal(fmtFigureValue(40_000_000, 'kg', null, 'it'), '40.000 t')
  assert.equal(fmtFigureValue(69297.65, 't', null, 'it'), '69.298 t')
})

test('assistant: a corrected market figure carries the same "Corretto da" mark and the official value', () => {
  const f: AssistantFact = {
    id: 1, kind: 'price', title: 'Brasile · Millefiori · prezzo all\'ingrosso', text: 'Brasile — 2,10 USD/lb, set 2026.',
    status: 'corrected', status_label: 'Corretto da Papà il 6 nov 2026', source: null, source_name: 'USDA AMS', url: null, link: '/prezzi',
    published_at: '2026-10-30', period_label: '2026-09', unit: 'USD/lb', data_status: 'user_entered', reliability: 'user', is_demo: false,
    private: false, country: 'BRA', price_type: 'wholesale_bulk', change_pct: null,
    correction: { event_id: 'x', author: 'Papà', created_at: '2026-11-06T01:28:05Z', reason: null, official_value: 2.04, unit: 'lb', currency: 'USD' },
  }
  const a = {
    question: 'Prezzi Brasile?', lang: 'it', asked_at: '2026-11-06T09:00:00', ai_used: false,
    understood: { mode: 'country', countries: [{ iso3: 'BRA', name: 'Brasile' }], eu: false, jurisdictions: [], varieties: [], price_types: [],
      topics: [], flow: null, direction: null, period: null, years: [], sources: [], llm_entities: false },
    ai: { enabled: false, provider: null, model: null }, intro: '', facts: [f], notes: [], warnings: [], is_demo: false,
    insufficient: false, insufficient_note: null, checks: null, private_data_used: false, sent_private_to_ai: false,
    sections: [{ key: 'verified', title: 'Fatti verificati', ai: false, analysis: false, items: [{ text: f.text, refs: [1], status: 'corrected' }] }],
  } as unknown as Answer
  const html = render(<AnswerView answer={a} />)
  assert.match(text(html), /Corretto a mano Brasile — 2,10 USD\/lb, set 2026\./)
  assert.match(text(html), /Corretto da Papà il 6 nov 2026 · valore della fonte: 2,04 USD\/lb/)
  assert.match(html, /data-corrected-tag/)
})

test('the exchange with the other computers is a switch, off by default, saying what it does', () => {
  const off = show(<SyncSwitch />, { qc: qcWith(false, [[['corrections', 'settings'], { author: 'Papà', sync_enabled: false }]]) })
  assert.match(off, /role="switch" aria-checked="false"/)
  assert.match(text(off), /Scambia le correzioni con gli altri computer Da attivare su ogni computer .*repository GitHub privato.*le offerte dei fornitori non lasciano mai questo computer/)
  const on = show(<SyncSwitch />, { qc: qcWith(false, [[['corrections', 'settings'], { author: 'Papà', sync_enabled: true }]]) })
  assert.match(on, /aria-checked="true"/)
  // the box links to it when the exchange is off
  const st = text(show(<SyncStatus compact />, { qc: qcWith(false, [[['corrections', 'sync'], { enabled: false, reason: 'disabled', reason_message_it: 'Scambio delle correzioni spento su questo computer.', pending: 0 }]]) }))
  assert.match(st, /Sincronizzazione: Scambio delle correzioni spento su questo computer\. Impostazioni/)
  assert.match(text(show(<SyncSwitch />, { lang: 'en', qc: qcWith(false, [[['corrections', 'settings'], { author: 'Papà', sync_enabled: false }]]) })), /Exchange corrections with the other computers/)
})

// --- 11 Nov 2026: fixing a number in place (owner: "not like a comment, like fixing the price") ----------
test('a typed number is read as an Italian reads it, and an ambiguous one by what the figure is', () => {
  assert.equal(parseTyped('3,5', 'it'), 3.5)
  assert.equal(parseTyped('3.5', 'it'), 3.5)                      // people also type a point
  assert.equal(parseTyped('69.298', 'it', 69298), 69298)           // tonnes: sixty-nine thousand
  assert.equal(parseTyped('1.775', 'it', 1.775), 1.775)            // a price of one dollar seventy-seven
  assert.equal(parseTyped('3.420', 'it', 3.42), 3.42)
  assert.equal(parseTyped('69.298', 'it'), 69298)                  // nothing to compare with: the Italian reading
  assert.equal(parseTyped('1.234.567,8', 'it'), 1234567.8)
  assert.equal(parseTyped('1,234.5', 'en'), 1234.5)
  assert.equal(parseTyped('69,298', 'en', 69298), 69298)
  assert.equal(parseTyped(' 3,50 € ', 'it'), 3.5)
  for (const bad of ['', 'circa 3', '3,4,5', '-2', '1.2.3,4,5']) assert.equal(parseTyped(bad, 'it'), null, bad)
})

test('the box opens with the number as shown: euros per kilo on screen, tonnes for big weights', () => {
  assert.deepEqual(editBasis(FIGURE), { value: 1.775, unit: 'lb', currency: 'USD' })
  assert.deepEqual(editBasis({ ...FIGURE, shown: { value: 3.4183, unit: 'kg', currency: 'EUR' } }), { value: 3.42, unit: 'kg', currency: 'EUR' })
  assert.deepEqual(editBasis({ ...FIGURE, table: 'trade_flows', value: 93811000, unit: 'kg', currency: null }), { value: 93811, unit: 't', currency: null })
  assert.equal(inputText(1.775, 'it'), '1,775')
  assert.equal(inputText(3.42, 'it'), '3,42')
  assert.equal(inputText(69298, 'it'), '69.298')
  assert.equal(parseTyped(inputText(69298, 'it'), 'it', 69298), 69298)
  assert.equal(inputText(null, 'it'), '')
})

test('fixing a number: one box with the number, Save, and the source\'s number one tap away', () => {
  const html = show(<QuickFixForm figure={{ ...FIGURE, shown: { value: 3.42, unit: 'kg', currency: 'EUR' } }} onCancel={() => {}} onMore={() => {}} />)
  const s = text(html)
  assert.match(s, /^Argentina · prezzo all'ingrosso \(fusti\) negli USA · millefiori, bianco · set 2026 Scrivi il numero giusto €\/kg Adesso: 3,42 €\/kg Salva Annulla/)
  assert.match(html, /value="3,42"/)
  assert.match(html, /<button type="submit"[^>]*disabled/)          // nothing to save until the number changes
  assert.doesNotMatch(html, /<textarea/)                            // no reason to write, no comment
  assert.match(s, /Il numero della fonte resta salvato/)
  assert.match(s, /Firmi come: Papà cambia Non sai il numero giusto\? Segnala un dubbio$/)
  const fixed = text(show(<QuickFixForm figure={FIGURE} correction={BRIEF} />))
  assert.match(fixed, /Corretto da Papà il 6 nov 2026\. La fonte dice 2,04 \$\/lb\. Rimetti il numero della fonte/)
  assert.match(text(show(<QuickFixForm figure={FIGURE} />, { lang: 'en' })), /Type the right number \$\/lb Now: 1.775 \$\/lb Save/)
})

test('the number itself is the button; in the phone copy, or without a stored row, it is just the number', () => {
  const html = show(<FixValue figure={FIGURE}><span>3,42 €/kg</span></FixValue>)
  assert.match(html, /<button type="button" title="Tocca per correggere questo numero" data-fix-value="2604"/)
  assert.match(text(html), /^3,42 €\/kg Tocca per correggere questo numero$/)
  assert.equal(show(<FixValue figure={null}><span>3,42</span></FixValue>), '<span>3,42</span>')
  assert.equal(mirror(() => show(<FixValue figure={FIGURE}><span>3,42</span></FixValue>)), '<span>3,42</span>')
  // every price of the simple Panoramica can be fixed by tapping it
  const d = structuredClone(overview) as unknown as OverviewData
  d.prices.items.forEach((x, i) => { if (i === 0) { x.row_id = null; x.row_ids = [901, 902] } else x.row_id = 100 + i })   // the first: an average of two rows
  const home = show(<SimpleOverview d={d} />, { qc: qcWith(false) })
  assert.match(home, /data-fix-value="901"/)
  assert.match(home, /data-fix-value="101"/)
  assert.doesNotMatch(mirror(() => show(<SimpleOverview d={d} />, { qc: qcWith(false) })), /data-fix-value=/)
})
