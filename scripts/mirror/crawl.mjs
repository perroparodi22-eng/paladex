#!/usr/bin/env node
// Paladex read-only online copy, step 2 (run by scripts/mirror/build.sh).
//
// Drives the NORMAL interface, served by a real backend running on a private-data-free copy of
// the database, through every market page and the filter combinations that matter, and records
// each GET /api/... answer as <out>/<sha256(key)[:24]>.json: exactly the file the read-only build
// asks for when it makes the same request (frontend/src/lib/mirror.ts, ./key.mjs). Views that
// depend on clicks rather than on the address are captured by clicking (price comparison by
// variety, further result pages, duty history, resolved quality checks); the trade page's other
// years and the value metric are fetched directly with the parameters the interface sends.
// Only the read-only market endpoints listed in key.mjs (CAPTURE) are ever written.
//
//   node scripts/mirror/crawl.mjs --base http://127.0.0.1:PORT --out DIR/mirror [--report FILE]
//        [--concurrency 4] [--max-file-mb 8]
//   node scripts/mirror/crawl.mjs --verify http://127.0.0.1:PORT2 --plan FILE [--sample N]
//        opens the finished copy (mirror build) and counts the views it cannot answer.
import { createRequire } from 'node:module'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { capturable, mirrorHash, mirrorKey } from './key.mjs'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const args = {}
for (let i = 2; i < process.argv.length; i++) {
  const a = process.argv[i]
  if (!a.startsWith('--')) throw new Error(`unexpected argument ${a}`)
  args[a.slice(2)] = process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[++i] : 'true'
}
const VERIFY = args.verify ? args.verify.replace(/\/$/, '') : null
const BASE = (args.base ?? '').replace(/\/$/, '')
const OUT = args.out
const CONCURRENCY = Math.max(1, Number(args.concurrency ?? 4))
const MAX_FILE = Number(args['max-file-mb'] ?? 8) * 1024 * 1024
const QUIET_MS = 350
const BLANK = '/__mirror_blank'
const t0 = Date.now()
const log = (...m) => console.log(`[${((Date.now() - t0) / 1000).toFixed(0).padStart(4)} s]`, ...m)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// Interface constants (keep in step with the frontend).
const SEEDS = ['/', '/prezzi', '/notizie', '/paesi', '/commercio', '/aziende', '/raccolti', '/normative', '/fonti']
const PRICE_TYPES = ['wholesale_bulk', 'import_unit_value', 'producer', 'export_unit_value', 'retail', 'other'] // prices/utils.ts
const MIN_RELEVANT = 35                                     // news/useNewsFilters.ts MIN_RELEVANT_SCORE
const MARKET_ORDER = ['ITA', 'DEU', 'USA', 'EU27', 'FRA', 'ESP', 'GBR', 'BEL', 'NLD', 'JPN', 'CHN', 'SAU'] // trade/FlowsPanel.tsx
const TRADE_YEARS = 6                                       // other years on the trade page: the latest six
const TOP_PARTNERS = 10                                     // FlowsPanel top=10
const NEWS_PAGES = 5                                        // "Mostra altre notizie" up to 100 articles
const DOC_PAGES = 10                                        // "Mostra altri documenti" up to 200 documents
const SHARE_AS_DEFAULT = 0.9                                // a filter value covering >= 90% of a view = the view itself
const ALLOWED_ROUTES = /^\/(|prezzi|notizie|paesi|paesi\/[A-Za-z0-9_]+|commercio|aziende|normative|fonti|raccolti(\/.*)?)$/
const MAX_DISCOVERED = 400

// ---------------------------------------------------------------------------------------------
// Recording
// ---------------------------------------------------------------------------------------------
const files = new Map()      // key -> { hash, bytes, via }
const hashes = new Map()     // hash -> key
const failures = []          // { key, status, from }
const excluded = new Map()   // path -> requests seen and deliberately not recorded
const tooLarge = new Map()   // key -> bytes
const jsErrors = []
const slow = []
let pagesVisited = 0

function store(key, body, via, essential) {
  if (files.has(key)) return
  const hash = mirrorHash(key)
  const other = hashes.get(hash)
  if (other && other !== key) throw new Error(`file name collision: ${key} / ${other}`)
  if (!essential && body.length > MAX_FILE) { tooLarge.set(key, body.length); return }
  writeFileSync(join(OUT, `${hash}.json`), body)
  files.set(key, { hash, bytes: body.length, via })
  hashes.set(hash, key)
  tooLarge.delete(key)
}

function noteExcluded(key) {
  const path = key.slice(0, key.indexOf('?'))
  excluded.set(path, (excluded.get(path) ?? 0) + 1)
}

// ---------------------------------------------------------------------------------------------
// Direct API access (enumerating the options, and the few click-only views of the trade page)
// ---------------------------------------------------------------------------------------------
function apiUrl(path, params = {}) {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {   // same rules as frontend/src/lib/api.ts qs()
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)))
    else sp.append(k, String(v))
  }
  const s = sp.toString()
  return `/api${path}${s ? `?${s}` : ''}`
}

async function api(path, params) {
  const res = await fetch(BASE + apiUrl(path, params))
  if (!res.ok) throw new Error(`GET ${apiUrl(path, params)} -> ${res.status}`)
  return res.json()
}

/** Fetch and record one answer exactly as the interface would request it. */
async function direct(path, params, via = 'direct') {
  const url = apiUrl(path, params)
  const key = mirrorKey(url)
  if (files.has(key)) return null
  if (!capturable(key)) { noteExcluded(key); return null }
  const res = await fetch(BASE + url)
  const body = Buffer.from(await res.arrayBuffer())
  if (res.status !== 200 || !(res.headers.get('content-type') ?? '').includes('json')) {
    failures.push({ key, status: res.status, from: via })
    return null
  }
  store(key, body, via, false)
  return JSON.parse(body.toString('utf8'))
}

async function pool(items, n, fn) {
  let i = 0
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (i < items.length) { const item = items[i++]; await fn(item) }
  }))
}

// ---------------------------------------------------------------------------------------------
// Browser pages
// ---------------------------------------------------------------------------------------------
function instrument(page, mode) {
  const st = { inflight: 0, last: Date.now(), pending: new Set(), task: null, misses: [] }
  const sameOrigin = (req) => { try { return new URL(req.url()).origin === new URL(page.url()).origin } catch { return false } }
  page.on('request', (req) => { if (sameOrigin(req)) { st.inflight++; st.last = Date.now() } })
  const done = (req) => { if (sameOrigin(req)) { st.inflight = Math.max(0, st.inflight - 1); st.last = Date.now() } }
  page.on('requestfinished', done)
  page.on('requestfailed', (req) => {
    done(req)
    const u = new URL(req.url())
    if (mode === 'record' && u.pathname.startsWith('/api/')) failures.push({ key: mirrorKey(u), status: req.failure()?.errorText ?? 'failed', from: st.task?.url })
  })
  page.on('pageerror', (e) => jsErrors.push(`${st.task?.url ?? '(start)'}: ${String(e).slice(0, 300)}`))
  if (mode === 'verify') {
    page.on('console', (m) => {
      const s = m.text()
      if (s.startsWith('[mirror] not in the copy:')) st.misses.push({ page: st.task?.url, key: s.slice(25).trim() })
    })
    return st
  }
  page.on('response', (resp) => {
    const req = resp.request()
    const u = new URL(req.url())
    if (req.method() !== 'GET' || !u.pathname.startsWith('/api/')) return
    const key = mirrorKey(u)
    if (!capturable(key)) { noteExcluded(key); return }
    if (resp.status() !== 200) { failures.push({ key, status: resp.status(), from: st.task?.url }); return }
    if (files.has(key)) return
    const essential = Boolean(st.task?.essential)
    const p = resp.body()
      .then((b) => store(key, b, 'page', essential))
      .catch((e) => failures.push({ key, status: `body: ${e.message}`, from: st.task?.url }))
      .finally(() => st.pending.delete(p))
    st.pending.add(p)
  })
  return st
}

async function waitIdle(st, timeout = 120_000) {
  const start = Date.now()
  for (;;) {
    await sleep(40)
    if (st.inflight === 0 && st.pending.size === 0 && Date.now() - st.last >= QUIET_MS) return true
    if (Date.now() - start > timeout) return false
  }
}

/** Client-side navigation (no reload), as a click on a link inside the application would do. */
async function spaGo(page, url) {
  await page.evaluate((u) => {
    window.history.pushState(null, '', u)
    window.dispatchEvent(new PopStateEvent('popstate', { state: null }))
  }, url)
}

async function clickAll(page, st, step) {
  if (step.select) {             // a <select> by its label: choose each value in turn
    const sel = page.getByRole('combobox', { name: step.select }).first()
    if (!(await sel.count())) { slow.push(`${st.task?.url} (no "${step.select}" select)`); return }
    for (const v of step.values) {
      st.last = Date.now()
      try { await sel.selectOption(String(v), { timeout: 5000 }) } catch { continue }
      if (!(await waitIdle(st))) slow.push(`${st.task?.url} (${step.select} ${v})`)
    }
    return
  }
  for (let n = 0; n < (step.repeat ?? 1); n++) {
    const loc = step.role
      ? page.getByRole(step.role, { name: step.text, exact: true })
      : page.locator(step.selector)
    const count = await loc.count()
    if (!count) { if (n === 0 && !step.optional) slow.push(`${st.task?.url} (no "${step.text ?? step.selector}")`); return }
    const targets = step.each ? count : 1
    for (let i = 0; i < targets; i++) {
      const el = loc.nth(step.each ? i : 0)
      try {
        await el.scrollIntoViewIfNeeded({ timeout: 5000 })
        st.last = Date.now()
        await el.click({ timeout: 5000 })
      } catch { return }
      if (!(await waitIdle(st))) slow.push(`${st.task?.url} (${step.text ?? step.selector})`)
    }
  }
}

async function visit(page, st, task, links) {
  st.task = task
  await spaGo(page, BLANK)       // unmount the previous page: its address-derived state is read afresh
  await sleep(25)
  st.last = Date.now()
  await spaGo(page, task.url)
  if (!(await waitIdle(st))) slow.push(task.url)
  for (const step of task.clicks ?? []) await clickAll(page, st, step)
  pagesVisited++
  if (links) {
    const hrefs = await page.$$eval('main a[href^="/"]', (as) => as.map((a) => a.getAttribute('href')))
    for (const h of hrefs) if (h) links.add(h)
  }
}

async function openPage(context, origin, mode) {
  const page = await context.newPage()
  const st = instrument(page, mode)
  if (mode === 'record') {
    // The backend only ever executes the read-only market endpoints: anything else the normal
    // interface asks for (settings, collection status, alert bell, ...) is answered here without
    // reaching it, so nothing private is produced (e.g. alerts evaluated) while the copy is made.
    await page.route('**/api/**', (route) => {
      const req = route.request()
      if (req.method() !== 'GET') return route.fulfill({ status: 405, contentType: 'application/json', body: '{"detail":"read-only export"}' })
      if (!capturable(mirrorKey(new URL(req.url())))) return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"not exported"}' })
      return route.continue()
    })
  }
  await page.goto(`${origin}${BLANK}`, { waitUntil: 'load', timeout: 120_000 })
  await waitIdle(st)
  return { page, st }
}

async function launch() {
  try {
    return await chromium.launch()
  } catch (e) {
    if (!/Executable doesn't exist|browserType\.launch/.test(String(e))) throw e
    return chromium.launch({ channel: 'chrome' })   // a Chrome installed on the machine
  }
}

const CONTEXTS = {
  it: { lang: 'it', timezoneId: 'Europe/Rome' },
  en: { lang: 'en', timezoneId: 'Europe/Rome' },
  // "Oggi / 7 giorni / 30 giorni" on the news page depend on the viewer's date: the American
  // evening is still the previous day in the US while the copy is produced in the European morning.
  la: { lang: 'it', timezoneId: 'America/Los_Angeles' },
}

async function runTasks(browser, origin, tasks, mode, linkSink) {
  const byCtx = {}
  for (const t of tasks) (byCtx[t.ctx] ??= []).push(t)
  await Promise.all(Object.entries(byCtx).map(async ([name, list]) => {
    const spec = CONTEXTS[name]
    const context = await browser.newContext({
      locale: spec.lang === 'it' ? 'it-IT' : 'en-GB', timezoneId: spec.timezoneId, viewport: { width: 1440, height: 1000 },
    })
    await context.addInitScript((lang) => { try { localStorage.setItem('paladex.lang', lang) } catch { /* ignore */ } }, spec.lang)
    const n = name === 'it' ? CONCURRENCY : 1
    const pages = await Promise.all(Array.from({ length: Math.min(n, list.length) }, () => openPage(context, origin, mode)))
    let i = 0
    let done = 0
    await Promise.all(pages.map(async ({ page, st }) => {
      while (i < list.length) {
        const task = list[i++]
        try {
          await visit(page, st, task, task.links ? linkSink : null)
        } catch (e) {
          failures.push({ key: '(page)', status: String(e).slice(0, 200), from: task.url })
        }
        if (++done % 100 === 0) log(`  ${name}: ${done}/${list.length} pages`)
      }
    }))
    if (mode === 'verify') for (const { st } of pages) verifyMisses.push(...st.misses)
    await context.close()
  }))
}

// ---------------------------------------------------------------------------------------------
// What to visit
// ---------------------------------------------------------------------------------------------
/** Same reading of the price page address as frontend/src/components/prices/useFilters.ts. */
const PRICE_ALIASES = { tipo: 'price_type', origini: 'origin', varieta: 'variety', mercato: 'market', fonte: 'source', colore: 'color_grade' }
function priceParam(sp, key) {
  const v = sp.get(key)
  if (v !== null) return v
  const all = sp.getAll(PRICE_ALIASES[key] ?? '').filter(Boolean)
  return all.length ? all.join(',') : null
}

/** One signature per distinct page state, so a discovered link to a view already planned is skipped. */
function signature(href, defaultPriceType) {
  const u = new URL(href, 'http://x')
  const sp = u.searchParams
  if (u.pathname === '/prezzi') {
    const tipo = priceParam(sp, 'tipo') || defaultPriceType
    return JSON.stringify(['/prezzi', tipo, (priceParam(sp, 'origini') ?? '').split(',').filter(Boolean).sort(),
      priceParam(sp, 'varieta') ?? '', priceParam(sp, 'mercato') ?? '', priceParam(sp, 'fonte') ?? '', priceParam(sp, 'colore') ?? '',
      sp.get('valuta') ?? 'USD', sp.get('periodo') ?? '3y', sp.get('freq') ?? 'M', sp.get('piccole') === '1'])
  }
  if (u.pathname === '/commercio') {
    const r = (sp.get('reporter') ?? '').toUpperCase()
    return JSON.stringify(['/commercio', r, r ? (sp.get('partner') ?? 'WLD').toUpperCase() : '', sp.get('flow') === 'export' ? 'export' : 'import'])
  }
  const keep = [...sp.entries()].filter(([k]) => k !== 'misura').sort()
  return JSON.stringify([u.pathname, keep])
}

async function plan() {
  const tasks = []
  const add = (ctx, url, opts = {}) => tasks.push({ ctx, url, ...opts })
  for (const url of SEEDS) add('it', url, { essential: true, links: true })
  for (const url of SEEDS) add('en', url, { essential: true, links: true })

  // Prices: every price type with data; its default view in each currency, frequency and period;
  // and each single filter value (origin, variety, market, source, colour) with data.
  const all = await api('/prices/facets')
  const typeCount = Object.fromEntries(all.price_types.map((p) => [p.key, p.count]))
  const types = PRICE_TYPES.filter((k) => (typeCount[k] ?? 0) > 0)
  const defaultType = types[0] ?? 'wholesale_bulk'
  const priceCounts = {}
  for (const T of types) {
    const base = `/prezzi?tipo=${T}`
    add('it', base, { essential: true, links: true, clicks: [
      { role: 'tab', text: 'Per varietà' },
      { role: 'button', text: 'Successivi', optional: true },
    ] })
    add('it', `${base}&valuta=EUR`, { clicks: [{ role: 'tab', text: 'Per varietà' }] })
    for (const v of ['freq=Q', 'freq=A', 'periodo=1y', 'periodo=5y', 'periodo=all']) add('it', `${base}&${v}`)
    const f = await api('/prices/facets', { price_type: T })
    let n = 0
    for (const [param, list] of [['origini', f.origins], ['varieta', f.varieties], ['mercato', f.markets], ['fonte', f.sources], ['colore', f.color_grades]]) {
      if ((list ?? []).length <= 1) continue                 // a single option: the select is disabled
      for (const o of list) {
        if (!o.count || o.count >= SHARE_AS_DEFAULT * f.total) continue
        add('it', `${base}&${param}=${encodeURIComponent(o.key)}`)
        n++
      }
    }
    priceCounts[T] = n
  }

  // News: the default list and its switches, the period presets (in two time zones), and each
  // country, topic, source and language that has relevant news.
  const n1 = await api('/news', { min_relevance: MIN_RELEVANT, page: 1, page_size: 20 })
  const more = { role: 'button', text: 'Mostra altre notizie', repeat: NEWS_PAGES - 1, optional: true }
  add('it', '/notizie?relevance=all', { clicks: [more] })
  add('it', '/notizie?sort=relevance')
  for (const p of ['today', '7d', '30d']) { add('it', `/notizie?period=${p}`); add('la', `/notizie?period=${p}`) }
  for (const [param, list] of [['country', n1.facets.countries], ['topic', n1.facets.topics], ['source', n1.facets.sources], ['lang', n1.facets.languages]]) {
    for (const o of list ?? []) if (o.count) add('it', `/notizie?${param}=${encodeURIComponent(o.key)}`)
  }
  tasks.find((t) => t.ctx === 'it' && t.url === '/notizie').clicks = [more]

  // Countries: every country profile with data (their links are followed afterwards).
  const cl = await api('/countries')
  const countries = cl.countries.filter((c) => Object.values(c.available ?? {}).some(Boolean)).map((c) => c.iso3).sort()
  for (const c of countries) add('it', `/paesi/${c}`, { links: true })

  // Companies: every country of the official company lists (its availability, and its lists when any).
  const co = await api('/companies')
  for (const c of co.countries ?? []) add('it', `/aziende?paese=${c.iso3}`)

  // Trade: the latest years in both metrics and both views of exports (select and switches),
  // then every market and flow (its top partners and total trend open from the address).
  const tf = await api('/trade/facets')
  const years = tradeYears(tf)
  tasks.find((t) => t.ctx === 'it' && t.url === '/commercio').clicks = [
    { role: 'tab', text: 'Valore' }, { select: 'Anno', values: years },
    { role: 'tab', text: 'Volume' }, { select: 'Anno', values: years },
    { role: 'tab', text: 'Secondo gli importatori' }, { select: 'Anno', values: years },
    { role: 'tab', text: 'Valore' }, { select: 'Anno', values: years },
  ]
  let tradeViews = 0
  for (const r of [...tf.reporters].sort((a, b) => a.iso3.localeCompare(b.iso3))) {
    for (const flow of ['import', 'export']) if (r.flows?.[flow]) { add('it', `/commercio?reporter=${r.iso3}&flow=${flow}`); tradeViews++ }
  }

  // Regulations: duty history of every origin (one click each), document pages and filters.
  const rg = await api('/regulations', { page: 1, page_size: 20 })
  tasks.find((t) => t.ctx === 'it' && t.url === '/normative').clicks = [
    { selector: 'button[aria-expanded]:has(svg.lucide-history)', each: true, optional: true },
    { role: 'button', text: 'Mostra altri documenti', repeat: DOC_PAGES - 1, optional: true },
  ]
  for (const [param, list] of [['jurisdiction', rg.facets.jurisdictions], ['type', rg.facets.doc_types], ['country', rg.facets.countries]]) {
    for (const o of list ?? []) if (o.count) add('it', `/normative?${param}=${encodeURIComponent(o.key)}`)
  }

  // Sources and data quality: the resolved checks too.
  tasks.find((t) => t.ctx === 'it' && t.url === '/fonti').clicks = [{ role: 'tab', text: 'Risolti' }]

  return { tasks, defaultType, types, priceCounts, countries: countries.length, tradeViews, tf }
}

/** The latest years offered by the trade page's year select (Trade.tsx). */
function tradeYears(tf) {
  return tf.years.filter((y) => y.import_complete + y.export_complete > 0).map((y) => y.year).sort((a, b) => b - a).slice(0, TRADE_YEARS)
}

/** The trade page's other years and the value metric (select and switch, not in the address):
 * recorded through the interface by the plan; fetched here too for the markets the plan does not
 * click through (the parameters are those FlowsPanel and Trade.tsx send). */
async function tradeExtras(tf, meta) {
  const jobs = []
  const defaultYear = tf.default_year?.import ?? tf.default_year?.export ?? tf.years.at(-1)?.year ?? null
  const years = tradeYears(tf)
  for (const year of years) {
    for (const metric of ['volume', 'value']) {
      jobs.push(['/trade/leaders', { flow: 'import', year, metric, basis: 'declared', limit: 100 }])
      jobs.push(['/trade/leaders', { flow: 'export', year, metric, basis: 'declared', limit: 100 }])
      jobs.push(['/trade/leaders', { flow: 'export', year, metric, basis: 'mirror', limit: 100 }])
    }
  }
  // Flows panel: the market shown first (FlowsPanel MARKET_ORDER) for every year and metric, and
  // the main markets (Parodi Group's own, the big buyers, the priority origins) in detail.
  const priority = (meta.countries ?? []).filter((c) => c.priority).map((c) => c.iso3)
  const byIso = new Map(tf.reporters.map((r) => [r.iso3, r]))
  const first = (flow) => [...MARKET_ORDER.filter((c) => byIso.get(c)?.flows?.[flow]), ...tf.reporters.filter((r) => r.flows?.[flow]).map((r) => r.iso3).sort()][0]
  const askYear = (r, flow, y) => (y !== null && (r.flows[flow].years ?? []).includes(y) ? y : undefined)
  for (const flow of ['import', 'export']) {
    const r = byIso.get(first(flow))
    if (!r) continue
    for (const year of years) for (const metric of ['volume', 'value']) {
      jobs.push(['/trade/flows', { reporter: r.iso3, flow, year: askYear(r, flow, year), metric, top: TOP_PARTNERS }])
    }
  }
  const main = [...new Set([...MARKET_ORDER, ...priority])].filter((c) => byIso.has(c))
  const partnerJobs = []
  for (const iso of main) {
    const r = byIso.get(iso)
    for (const flow of ['import', 'export']) {
      if (!r.flows?.[flow]) continue
      const y = askYear(r, flow, defaultYear)
      jobs.push(['/trade/flows', { reporter: iso, flow, year: y, metric: 'value', top: TOP_PARTNERS }])
      if ((r.flows[flow].frequencies ?? []).includes('M')) jobs.push(['/trade/series', { reporter: iso, partner: 'WLD', flow, freq: 'M' }])
      partnerJobs.push([iso, flow, y])
    }
  }
  await pool(jobs, 6, ([p, q]) => direct(p, q, 'trade'))
  // Each main market's top partners: the trend that opens when a row of the table is chosen.
  await pool(partnerJobs, 6, async ([iso, flow, year]) => {
    const fl = await api('/trade/flows', { reporter: iso, flow, year, metric: 'volume', top: TOP_PARTNERS })
    for (const row of (fl.rows ?? []).slice(0, TOP_PARTNERS)) {
      if (!row.iso3 || row.iso3 === 'WLD') continue
      await direct('/trade/series', { reporter: iso, partner: row.iso3, flow, freq: 'A' }, 'trade')
    }
  })
  return { jobs: jobs.length, partnerMarkets: partnerJobs.length }
}

/** Last guard: the recorded overview must not carry alert events (private; the copy's database
 * has none and the export never runs alert code). Stops the export rather than publish them. */
function privacyCheck() {
  for (const [key, f] of files) {
    if (!key.startsWith('/overview?')) continue
    const d = JSON.parse(readFileSync(join(OUT, `${f.hash}.json`), 'utf8'))
    if ((d.alerts?.items ?? []).length || d.alerts?.unread) {
      console.error(`PRIVATE DATA in ${key}: alert events present; the copy is not finished.`)
      process.exit(1)
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Manifest and report
// ---------------------------------------------------------------------------------------------
const utcIso = (s) => (s ? `${String(s).slice(0, 19)}Z` : null)

async function manifest() {
  const summary = await api('/quality/summary')
  let collected = summary.last_success_at
  if (!collected) {
    try { collected = (await api('/collect/status')).first_run?.starter?.data_collected_until ?? null } catch { /* older backend */ }
  }
  collected = collected ?? summary.last_new_data_at ?? null
  let bytes = 0
  for (const f of files.values()) bytes += f.bytes
  const m = {
    format: 1,
    generated_at: new Date().toISOString().slice(0, 19) + 'Z',
    data_collected_until: utcIso(collected),
    last_new_data_at: utcIso(summary.last_new_data_at),
    refresh: 'daily',
    files: files.size,
    bytes,
  }
  writeFileSync(join(OUT, 'manifest.json'), JSON.stringify(m, null, 1) + '\n')
  return m
}

function report(extra) {
  const byPath = {}
  for (const [key, f] of files) {
    const p = key.slice(0, key.indexOf('?')).replace(/\/[A-Z]{3}$|\/[A-Z0-9_]+$|\/\d+$/, '/{id}')
    const e = (byPath[p] ??= { files: 0, mb: 0 })
    e.files++
    e.mb += f.bytes / 1e6
  }
  for (const e of Object.values(byPath)) e.mb = Number(e.mb.toFixed(1))
  return {
    seconds: Math.round((Date.now() - t0) / 1000),
    pages_visited: pagesVisited,
    files: files.size,
    mb: Number(([...files.values()].reduce((a, f) => a + f.bytes, 0) / 1e6).toFixed(1)),
    by_endpoint: Object.fromEntries(Object.entries(byPath).sort()),
    not_recorded_by_design: Object.fromEntries([...excluded.entries()].sort()),
    too_large_skipped: [...tooLarge.entries()].map(([key, b]) => ({ key, mb: Number((b / 1e6).toFixed(1)) })),
    failed: failures,
    slow_pages: slow,
    js_errors: jsErrors.slice(0, 50),
    ...extra,
  }
}

// ---------------------------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------------------------
const verifyMisses = []

async function main() {
  if (VERIFY) {
    const saved = JSON.parse(readFileSync(args.plan, 'utf8'))
    let tasks = saved.tasks
    const sample = Number(args.sample ?? 0)
    if (sample > 0 && tasks.length > sample) {
      const step = tasks.length / sample
      tasks = tasks.filter((t, i) => t.essential || Math.floor(i % step) === 0)
    }
    log(`verifying ${tasks.length} pages of the copy at ${VERIFY}`)
    const browser = await launch()
    await runTasks(browser, VERIFY, tasks.map((t) => ({ ...t, links: false })), 'verify', null)
    await browser.close()
    const keys = new Map()
    for (const m of verifyMisses) if (!keys.has(m.key)) keys.set(m.key, m.page)
    const pagesWithMisses = new Set(verifyMisses.map((m) => m.page)).size
    log(`verify: ${pagesVisited} pages opened in the copy, ${pagesWithMisses} with a view not in the copy, ${keys.size} distinct missing answer(s)`)
    for (const [k, p] of [...keys.entries()].slice(0, 40)) console.log(`  missing ${k}   (page ${p})`)
    if (jsErrors.length) { console.log(`  JavaScript errors: ${jsErrors.length}`); jsErrors.slice(0, 10).forEach((e) => console.log(`   ${e}`)) }
    for (const x of slow.slice(0, 20)) console.log(`  slow or not found: ${x}`)
    if (args.report) writeFileSync(args.report, JSON.stringify({ pages: pagesVisited, pages_with_misses: pagesWithMisses, missing: [...keys.entries()], js_errors: jsErrors }, null, 1))
    return
  }
  if (!BASE || !OUT) throw new Error('usage: crawl.mjs --base URL --out DIR [--report FILE]')
  mkdirSync(OUT, { recursive: true })
  const meta = await api('/meta')
  const p = await plan()
  // --only REGEX / --limit N: development aids (a subset of the pages).
  const only = args.only ? new RegExp(args.only) : null
  if (only) p.tasks = p.tasks.filter((t) => only.test(t.url))
  const seeds = p.tasks.filter((t) => t.essential)
  const rest = p.tasks.filter((t) => !t.essential).slice(0, args.limit ? Number(args.limit) : undefined)
  log(`plan: ${p.tasks.length} pages (${seeds.length} default views; price types ${p.types.join(', ')}; `
    + `${Object.values(p.priceCounts).reduce((a, b) => a + b, 0)} price filters; ${p.countries} countries; ${p.tradeViews} trade markets)`)
  const browser = await launch()
  const links = new Set()
  log('default views of every section (Italian and English)')
  await runTasks(browser, BASE, seeds, 'record', links)
  log(`filters, countries, markets: ${rest.length} pages`)
  await runTasks(browser, BASE, rest, 'record', links)

  // Links the pages offer (overview tiles, country profiles, quality checks...) to views not planned.
  const seen = new Set(p.tasks.map((t) => signature(t.url, p.defaultType)))
  const extra = []
  for (const href of [...links].sort()) {
    const u = new URL(href, 'http://x')
    if (!ALLOWED_ROUTES.test(u.pathname)) continue
    const sig = signature(href, p.defaultType)
    if (seen.has(sig)) continue
    seen.add(sig)
    extra.push({ ctx: 'it', url: u.pathname + u.search })
  }
  const followed = extra.slice(0, MAX_DISCOVERED)
  log(`links found on the pages: ${links.size}; new views to open: ${extra.length}${extra.length > followed.length ? ` (first ${followed.length})` : ''}`)
  await runTasks(browser, BASE, followed, 'record', null)
  await browser.close()

  log('trade: other years, value metric, monthly trends and partner trends of the main markets')
  const te = await tradeExtras(p.tf, meta)
  privacyCheck()
  const m = await manifest()
  const r = report({ plan: { pages: p.tasks.length + followed.length, price_filters: p.priceCounts, countries: p.countries,
    trade_markets: p.tradeViews, discovered_links_followed: followed.length, trade_direct: te }, manifest: m })
  if (args.report) writeFileSync(args.report, JSON.stringify({ ...r, tasks: [...p.tasks, ...followed] }, null, 1))
  log(`done: ${r.pages_visited} pages visited, ${r.files} answers recorded (${r.mb} MB), ${r.failed.length} failed request(s), `
    + `${tooLarge.size} too large, ${jsErrors.length} JavaScript error(s)`)
  for (const [k, v] of Object.entries(r.by_endpoint)) console.log(`  ${k.padEnd(28)} ${String(v.files).padStart(5)} files ${String(v.mb).padStart(7)} MB`)
  console.log(`  not recorded by design (private or computer-only): ${Object.entries(r.not_recorded_by_design).map(([k, v]) => `${k} ×${v}`).join(', ') || 'none'}`)
  for (const f of r.failed.slice(0, 30)) console.log(`  FAILED ${f.status} ${f.key} (from ${f.from})`)
  for (const t of r.too_large_skipped) console.log(`  too large, not in the copy: ${t.key} (${t.mb} MB)`)
  for (const e of jsErrors.slice(0, 10)) console.log(`  JS error: ${e}`)
  for (const x of slow.slice(0, 20)) console.log(`  slow or not found: ${x}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
