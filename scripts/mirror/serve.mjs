#!/usr/bin/env node
// Serves a built online copy locally the way Netlify will: an existing file is served as is,
// otherwise the first matching rule of its `_redirects` file applies (splat rules, status codes).
// Also sends the `_headers` of the copy. For checking the copy before it is published:
//
//   node scripts/mirror/serve.mjs <copy-dir> [port]        (default port 8790)
import { createServer } from 'node:http'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { extname, join, normalize, resolve } from 'node:path'

const root = resolve(process.argv[2] ?? '.')
const port = Number(process.argv[3] ?? 8790)
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.woff': 'font/woff',
  '.txt': 'text/plain; charset=utf-8', '.ico': 'image/x-icon',
}

function rules(file, parse) {
  const p = join(root, file)
  return existsSync(p) ? parse(readFileSync(p, 'utf8')) : []
}
const redirects = rules('_redirects', (s) => s.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('#'))
  .map((l) => { const [from, to, status] = l.split(/\s+/); return { from, to, status: Number(status ?? 301) } }))
const headers = rules('_headers', (s) => {
  const out = []
  for (const line of s.split('\n')) {
    if (!line.trim() || line.trim().startsWith('#')) continue
    if (!/^\s/.test(line)) out.push({ path: line.trim(), set: [] })
    else { const i = line.indexOf(':'); out.at(-1)?.set.push([line.slice(0, i).trim(), line.slice(i + 1).trim()]) }
  }
  return out
})
const matches = (pattern, path) => (pattern.endsWith('*') ? path.startsWith(pattern.slice(0, -1)) : path === pattern)

function fileFor(path) {
  const p = normalize(join(root, decodeURIComponent(path)))
  if (!p.startsWith(root)) return null
  if (existsSync(p) && statSync(p).isFile()) return p
  if (existsSync(join(p, 'index.html'))) return join(p, 'index.html')
  return null
}

createServer((req, res) => {
  const path = new URL(req.url, 'http://x').pathname
  let file = fileFor(path)
  let status = 200
  if (!file) {
    const rule = redirects.find((r) => matches(r.from, path))
    file = rule ? fileFor(rule.to) : null
    status = rule ? rule.status : 404
  }
  for (const h of headers) if (matches(h.path, path)) for (const [k, v] of h.set) res.setHeader(k, v)
  if (!file) { res.writeHead(404, { 'Content-Type': 'text/plain' }); res.end('not found'); return }
  res.writeHead(status, { 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' })
  res.end(readFileSync(file))
}).listen(port, '127.0.0.1', () => console.log(`online copy served at http://127.0.0.1:${port} (from ${root})`))
