// Server-side rendering helpers for the frontend tests: the app's real providers (i18n, router,
// react-query) around a component, rendered to static HTML with react-dom/server.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { I18nProvider } from '@/i18n'
import type { Lang } from '@/lib/types'

// react-router's <Link> uses useLayoutEffect, which React reports as a warning on the server.
const consoleError = console.error
console.error = (...args: unknown[]) => {
  if (typeof args[0] === 'string' && args[0].includes('useLayoutEffect does nothing on the server')) return
  consoleError(...args)
}

export function newQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
}

/** Render `node` at `url` in `lang` (the language is read from localStorage, as in the browser). */
export function render(node: ReactNode, { url = '/', lang = 'it', qc = newQueryClient() }: { url?: string; lang?: Lang; qc?: QueryClient } = {}): string {
  const g = globalThis as { localStorage?: unknown }
  const saved = g.localStorage
  g.localStorage = { getItem: () => lang, setItem: () => {} }
  try {
    return renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <I18nProvider>
          <MemoryRouter initialEntries={[url]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{node}</MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    )
  } finally {
    g.localStorage = saved
  }
}

/** Decode the HTML entities renderToStaticMarkup produces, so assertions can use plain text. */
export function text(html: string): string {
  return html.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/\s+/g, ' ').trim()
}

/** All href values in rendered HTML (entities decoded). */
export function hrefs(html: string): string[] {
  return [...html.matchAll(/href="([^"]*)"/g)].map((m) => m[1].replace(/&amp;/g, '&'))
}
