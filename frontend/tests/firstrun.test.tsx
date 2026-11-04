// The first minutes after installation: the owner must never be left looking at empty pages
// without an explanation, and real starter data is always presented with its collection date.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { FirstRunBanner } from '@/components/layout/FirstRunBanner'
import type { CollectState, FirstRunState } from '@/lib/types'
import { render, text } from './helpers'

const starter = { built_at: '2026-11-04T23:10:00', data_collected_until: '2026-11-04T20:35:12', imported_at: '2026-11-05T07:00:00' }
const state = (running: boolean, first_run: FirstRunState): CollectState => ({ running, started_at: null, keys: null, results: null, first_run })

test('starter data is shown with its collection date while this computer updates it', () => {
  const body = text(render(<FirstRunBanner status={state(true, { has_data: true, local_runs: {}, starter })} />))
  assert.match(body, /dati reali già raccolti dalle fonti ufficiali fino al/)
  assert.match(body, /2026/)
  assert.match(body, /aggiornando ora/)
  const en = text(render(<FirstRunBanner status={state(false, { has_data: true, local_runs: {}, starter })} />, { lang: 'en' }))
  assert.match(en, /real data already collected from the official sources up to/)
})

test('no internet on the first start is said plainly', () => {
  const body = text(render(<FirstRunBanner status={state(false, { has_data: true, local_runs: { offline: 47 }, starter })} />))
  assert.match(body, /Nessuna connessione a internet/)
  const empty = text(render(<FirstRunBanner status={state(false, { has_data: false, local_runs: { offline: 3 }, starter: null })} />))
  assert.match(empty, /non risulta collegato a internet/)
})

test('a first collection without starter data explains that pages fill in', () => {
  const body = text(render(<FirstRunBanner status={state(true, { has_data: false, local_runs: {}, starter: null })} />))
  assert.match(body, /Primo avvio/)
  assert.match(body, /30–40 minuti/)
})

test('the notice disappears once this computer has checked the sources', () => {
  for (const fr of [
    { has_data: true, local_runs: { success: 20, no_change: 10 }, starter },
    { has_data: true, local_runs: { no_change: 1 }, starter: null },
    { has_data: true, local_runs: {}, starter: null },
  ]) {
    assert.equal(text(render(<FirstRunBanner status={state(false, fr)} />)).trim(), '')
  }
})
