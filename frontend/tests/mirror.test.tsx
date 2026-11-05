// Read-only online copy (lib/mirror.ts, scripts/mirror/): the file names the copy asks for must be
// exactly those the exporter writes, nothing can be written through it, a view it does not contain
// is shown as a friendly note, and the menu only offers what the copy contains.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { test } from 'node:test'
import { Shell } from '@/components/layout/Shell'
import { ErrorBlock } from '@/components/ui'
import { api, ApiError, qs } from '@/lib/api'
import { isMirror, isMirrorMissing, mirrorHash, mirrorKey, MirrorMissingError, setMirrorMode, sha256 } from '@/lib/mirror'
import { hrefs, render, text } from './helpers'

const sha = (s: string) => createHash('sha256').update(s, 'utf8').digest('hex')

/** The exporter's own module (scripts/mirror/key.mjs), loaded by Node itself: importing a file
 *  outside the frontend through Vite would leave a file watcher open and keep the runner alive. */
type ExporterKey = { mirrorKey: (u: string | URL) => string; mirrorHash: (k: string) => string }
const nativeImport = new Function('u', 'return import(u)') as (u: string) => Promise<ExporterKey>
const exporter = () => nativeImport(new URL('../../scripts/mirror/key.mjs', import.meta.url).href)

/** Run `fn` in mirror mode with `fetch` answered by `answer`; restores both afterwards. */
async function inMirror<T>(answer: (url: string) => Response, fn: (calls: string[]) => Promise<T>): Promise<T> {
  const saved = globalThis.fetch
  const calls: string[] = []
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    calls.push(url)
    return answer(url)
  }) as typeof fetch
  setMirrorMode(true)
  try {
    return await fn(calls)
  } finally {
    setMirrorMode(null)
    globalThis.fetch = saved
  }
}
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

test('the key ignores parameter order but keeps every value', () => {
  assert.equal(mirrorKey('/api/prices/series?price_type=producer&origin=ARG&freq=M'),
    mirrorKey('/api/prices/series?freq=M&origin=ARG&price_type=producer'))
  assert.equal(mirrorKey('/api/prices/series?price_type=producer&origin=ARG&freq=M'), '/prices/series?freq=M&origin=ARG&price_type=producer')
  assert.equal(mirrorKey('/api/prices/series?origin=ARG&origin=UKR'), '/prices/series?origin=ARG&origin=UKR')
  assert.notEqual(mirrorKey('/api/prices/series?origin=ARG&origin=UKR'), mirrorKey('/api/prices/series?origin=UKR&origin=ARG'))
  assert.equal(mirrorKey('/api/meta'), '/meta?')
  // Spaces, commas and accents are encoded the same way whatever form the URL arrives in.
  assert.equal(mirrorKey(`/api/news${qs({ q: 'miele d’acacia, prezzi' })}`), mirrorKey('/api/news?q=miele+d%E2%80%99acacia%2C+prezzi'))
})

test('the interface and the exporter compute the same file name for real requests', async () => {
  const { mirrorKey: exporterKey, mirrorHash: exporterHash } = await exporter()
  const requests = [
    `/api/prices/series${qs({ price_type: 'import_unit_value', origin: ['ARG', 'UKR'], from: '2023-12', freq: 'M', currency: 'EUR' })}`,
    `/api/news${qs({ q: 'miele d’acacia', country: 'ARG,UKR', min_relevance: 35, page: 2, page_size: 20 })}`,
    `/api/countries/${encodeURIComponent('ARG')}`,
    `/api/trade/flows${qs({ reporter: 'ITA', flow: 'import', year: 2024, metric: 'value', top: 10 })}`,
    '/api/overview?lang=en',
    '/api/meta',
  ]
  for (const url of requests) {
    const key = mirrorKey(url)
    // The exporter sees the absolute address the browser requested.
    assert.equal(exporterKey(new URL(url, 'http://127.0.0.1:9999')), key)
    assert.equal(await mirrorHash(key), exporterHash(key))
    assert.equal(await mirrorHash(key), sha(key).slice(0, 24))
  }
})

test('the SHA-256 fallback (pages without crypto.subtle) is correct', () => {
  const enc = new TextEncoder()
  for (const s of ['', 'abc', 'a'.repeat(55), 'a'.repeat(56), 'b'.repeat(63), 'c'.repeat(64), 'd'.repeat(65), 'è€✓'.repeat(300)]) {
    const hex = [...sha256(enc.encode(s))].map((b) => b.toString(16).padStart(2, '0')).join('')
    assert.equal(hex, sha(s), `input of length ${s.length}`)
  }
})

test('in the copy nothing can be written', async () => {
  await inMirror(() => json({}), async (calls) => {
    for (const call of [() => api.post('/collect', {}), () => api.put('/settings', { show_demo: true }), () => api.del('/demo')]) {
      await assert.rejects(call(), (e: unknown) => e instanceof ApiError && e.status === 405 && /sola lettura/.test(e.message))
    }
    assert.equal(calls.length, 0)
  })
})

test('in the copy a GET reads the recorded answer of exactly that request', async () => {
  await inMirror((url) => (url.startsWith('/mirror/') ? json({ ok: url }) : new Response('no', { status: 500 })), async (calls) => {
    const got = await api.get<{ ok: string }>('/prices/latest', { currency: 'EUR', price_type: 'producer' })
    const file = `/mirror/${sha('/prices/latest?currency=EUR&price_type=producer').slice(0, 24)}.json`
    assert.deepEqual(calls, [file])
    assert.equal(got.ok, file)
  })
})

test('a view the copy lacks is reported as missing, not as an error of the data', async () => {
  const html = () => new Response('<!doctype html>', { status: 200, headers: { 'Content-Type': 'text/html' } })
  const notFound = () => new Response('{"missing": true}', { status: 404, headers: { 'Content-Type': 'application/json' } })
  const info = console.info
  console.info = () => {}
  try {
    for (const answer of [html, notFound]) {
      await inMirror(answer, async () => {
        await assert.rejects(api.get('/countries/XYZ'), (e: unknown) => isMirrorMissing(e) && !(e instanceof ApiError))
      })
    }
  } finally {
    console.info = info
  }
  // Private or computer-only answers are never even requested.
  await inMirror(() => json({ show_demo: true }), async (calls) => {
    for (const path of ['/settings', '/collect/status', '/quality/keys', '/alerts/unread-count', '/quotes', '/assistant/history', '/archive/quotes', '/sources/x/runs', '/search']) {
      await assert.rejects(api.get(path), (e: unknown) => e instanceof MirrorMissingError)
    }
    assert.equal(calls.length, 0)
  })
})

test('the friendly note replaces the error block, in both languages', () => {
  const e = new MirrorMissingError('/countries/XYZ?')
  const it = text(render(<ErrorBlock error={e} onRetry={() => {}} />))
  assert.match(it, /Questa vista non è inclusa nella copia online: è disponibile sul computer\./)
  assert.doesNotMatch(it, /Impossibile caricare|Riprova/)
  const en = text(render(<ErrorBlock error={e} />, { lang: 'en' }))
  assert.match(en, /This view is not included in the online copy: it is available on the computer\./)
  // Real errors are unchanged.
  assert.match(text(render(<ErrorBlock error={new Error('boom')} />)), /Impossibile caricare i dati.*boom/)
})

test('normal build: requests go to the backend as before', async () => {
  assert.equal(isMirror(), false)
  const saved = globalThis.fetch
  const calls: string[] = []
  globalThis.fetch = (async (input: RequestInfo | URL) => { calls.push(String(input)); return json({ a: 1 }) }) as typeof fetch
  try {
    assert.deepEqual(await api.get('/prices/facets', { price_type: 'producer' }), { a: 1 })
    await api.post('/collect', {})
    assert.deepEqual(calls, ['/api/prices/facets?price_type=producer', '/api/collect'])
  } finally {
    globalThis.fetch = saved
  }
})

test('the copy shows its strip and only the market sections; the computer shows everything', () => {
  const normal = render(<Shell><p>page</p></Shell>, { url: '/' })
  for (const route of ['/offerte', '/avvisi', '/archivio', '/assistente']) assert.ok(hrefs(normal).includes(route), route)
  assert.match(text(normal), /Aggiorna dati/)
  assert.doesNotMatch(text(normal), /Copia online di sola lettura/)

  setMirrorMode(true)
  try {
    const copy = render(<Shell><p>page</p></Shell>, { url: '/' })
    for (const route of ['/offerte', '/avvisi', '/archivio', '/assistente', '/cerca']) assert.ok(!hrefs(copy).includes(route), route)
    for (const route of ['/', '/prezzi', '/notizie', '/paesi', '/commercio', '/aziende', '/normative', '/fonti']) assert.ok(hrefs(copy).includes(route), route)
    assert.match(text(copy), /Copia online di sola lettura/)
    assert.doesNotMatch(text(copy), /Aggiorna dati/)
    assert.doesNotMatch(copy, /<input/)                       // no search box
    assert.match(text(copy), /page/)
    // A tool of the computer opened by its address: an honest note instead of the tool.
    const tool = text(render(<Shell><p>quotes tool</p></Shell>, { url: '/offerte' }))
    assert.doesNotMatch(tool, /quotes tool/)
    assert.match(tool, /Questa vista non è inclusa nella copia online/)
  } finally {
    setMirrorMode(null)
  }
})

test('the strip says when the data was collected, and warns when the copy or the data is old', async () => {
  const { MirrorStrip } = await import('@/components/layout/MirrorStrip')
  const { newQueryClient } = await import('./helpers')
  const iso = (hoursAgo: number) => new Date(Date.now() - hoursAgo * 3_600_000).toISOString().slice(0, 19) + 'Z'
  const strip = (generated: number, collected: number | null, lang: 'it' | 'en' = 'it') => {
    const qc = newQueryClient()
    qc.setQueryData(['mirror-manifest'], { format: 1, generated_at: iso(generated), data_collected_until: collected === null ? null : iso(collected), refresh: 'daily', files: 1 })
    setMirrorMode(true)
    try {
      return text(render(<MirrorStrip />, { qc, lang }))
    } finally {
      setMirrorMode(null)
    }
  }
  const fresh = strip(2, 3)
  assert.match(fresh, /Copia online di sola lettura · dati raccolti fino al \d{1,2} \w{3} \d{4} \d{2}:\d{2}/)
  assert.match(fresh, /aggiornata ogni giorno/)
  assert.doesNotMatch(fresh, /possono essere vecchi/)
  assert.match(strip(24 * 3 + 2, 24 * 3 + 3), /copia non aggiornata da 3 giorni: i dati possono essere vecchi/)
  assert.match(strip(2, 24 * 4), /le fonti non rispondono da 4 giorni/)
  assert.match(strip(2, null), /data di raccolta non disponibile/)
  assert.match(strip(2, 3, 'en'), /Read-only online copy · data collected up to/)
})
