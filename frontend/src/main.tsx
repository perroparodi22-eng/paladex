import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { I18nProvider } from './i18n'
import { isMirrorMissing } from './lib/mirror'
import './styles/index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    // One retry, except for a view the read-only online copy does not contain (lib/mirror.ts).
    queries: { staleTime: 60_000, retry: (n, e) => n < 1 && !isMirrorMissing(e), refetchOnWindowFocus: false },
  },
})

// Opt in to the v7 behaviour now: without these flags React Router prints two deprecation
// warnings in every browser console, production build included.
const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true } as const

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <BrowserRouter future={ROUTER_FUTURE}>
          <App />
        </BrowserRouter>
      </I18nProvider>
    </QueryClientProvider>
  </StrictMode>,
)
