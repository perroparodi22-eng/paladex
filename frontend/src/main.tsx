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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </I18nProvider>
    </QueryClientProvider>
  </StrictMode>,
)
