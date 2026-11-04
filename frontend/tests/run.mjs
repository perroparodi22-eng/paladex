// Frontend regression tests: `npm test` (no extra dependencies).
// Each tests/**/*.test.ts(x) file is loaded through Vite's SSR pipeline (same aliases, JSX and
// import.meta.glob handling as the app) and uses Node's built-in `node:test` runner.
import { readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { after } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('..', import.meta.url))
const only = process.argv.slice(2)

function find(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f)
    return statSync(p).isDirectory() ? find(p) : /\.test\.tsx?$/.test(f) ? [p] : []
  })
}

const server = await createServer({
  root, configFile: join(root, 'vite.config.ts'), logLevel: 'error',
  server: { middlewareMode: true, watch: null, hmr: false }, appType: 'custom', optimizeDeps: { noDiscovery: true },
})
after(() => server.close())
for (const file of find(join(root, 'tests')).sort()) {
  const rel = relative(root, file)
  if (only.length && !only.some((o) => rel.includes(o))) continue
  await server.ssrLoadModule(`/${rel}`)
}
