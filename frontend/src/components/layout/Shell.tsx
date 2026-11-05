import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Archive, BarChart3, Bell, Bot, CloudSun, Database, FileText, Globe2, LayoutDashboard,
  Menu, Newspaper, RefreshCw, Scale, Search, Ship, WifiOff, X,
} from 'lucide-react'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtAgo } from '@/lib/format'
import { isMirror } from '@/lib/mirror'
import type { CollectState, SourceInfo } from '@/lib/types'
import { FirstRunBanner } from './FirstRunBanner'
import { MirrorStrip, mirrorHidesRoute, NotInCopy } from './MirrorStrip'
import { AlertBell } from '@/components/alerts/AlertBell'

interface NavItem { to: string; key: string; icon: ReactNode; end?: boolean }

const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: 'nav.section.market',
    items: [
      { to: '/', key: 'nav.overview', icon: <LayoutDashboard size={19} />, end: true },
      { to: '/prezzi', key: 'nav.prices', icon: <BarChart3 size={19} /> },
      { to: '/notizie', key: 'nav.news', icon: <Newspaper size={19} /> },
      { to: '/paesi', key: 'nav.countries', icon: <Globe2 size={19} /> },
      { to: '/commercio', key: 'nav.trade', icon: <Ship size={19} /> },
      { to: '/raccolti', key: 'nav.harvest', icon: <CloudSun size={19} /> },
      { to: '/normative', key: 'nav.regulations', icon: <Scale size={19} /> },
    ],
  },
  {
    section: 'nav.section.business',
    items: [
      { to: '/offerte', key: 'nav.quotes', icon: <FileText size={19} /> },
      { to: '/avvisi', key: 'nav.alerts', icon: <Bell size={19} /> },
      { to: '/archivio', key: 'nav.archive', icon: <Archive size={19} /> },
      { to: '/assistente', key: 'nav.assistant', icon: <Bot size={19} /> },
    ],
  },
  {
    section: 'nav.section.system',
    items: [{ to: '/fonti', key: 'nav.sources', icon: <Database size={19} /> }],
  },
]

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n()
  // The read-only online copy lists only what it contains (lib/mirror.ts); empty groups go too.
  const groups = NAV.map((g) => ({ ...g, items: g.items.filter((i) => !mirrorHidesRoute(i.to)) })).filter((g) => g.items.length > 0)
  return (
    <aside
      id="app-menu"
      className={clsx(
        'w-[264px] shrink-0 bg-forest-900 text-ivory flex flex-col h-screen sticky top-0',
        // Below md (phones): a menu that slides in over the page from the top-bar button.
        'max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-[1100] max-md:h-auto max-md:transition-[transform,visibility] max-md:duration-200',
        open ? 'max-md:shadow-2xl' : 'max-md:invisible max-md:-translate-x-full',
      )}
    >
      <div className="px-5 pt-5 pb-4 border-b border-forest-700/60">
        <div className="flex items-center gap-3">
          <svg viewBox="0 0 40 40" className="h-9 w-9 shrink-0" aria-hidden>
            <path d="M20 3 35 11.5v17L20 37 5 28.5v-17z" fill="none" stroke="#C9A85A" strokeWidth="2.2" />
            <path d="M20 11 28 15.5v9L20 29l-8-4.5v-9z" fill="#C9A85A" opacity=".18" stroke="#C9A85A" strokeWidth="1" />
          </svg>
          <div className="leading-tight">
            <div className="font-serif text-[1.15rem] font-semibold tracking-wide">{t('app.name')}</div>
            <div className="text-[0.7rem] uppercase tracking-[0.2em] text-gold-light">{t('app.subtitle')}</div>
          </div>
          <button type="button" onClick={onClose} aria-label={t('mirror.closeMenu')}
            className="md:hidden ml-auto -mr-2 inline-flex h-10 w-10 items-center justify-center rounded-sm text-forest-100 hover:bg-forest-800 hover:text-ivory">
            <X size={22} />
          </button>
        </div>
        <div className="mt-2 text-[0.68rem] text-forest-300 tracking-wide">{t('app.heritage')}</div>
      </div>
      <nav className="flex-1 overflow-y-auto py-3">
        {groups.map((group) => (
          <div key={group.section} className="mb-3">
            <div className="px-5 py-1.5 text-[0.66rem] uppercase tracking-[0.18em] text-forest-300/80">{t(group.section)}</div>
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-3 px-5 py-2.5 text-[0.95rem] border-l-[3px] transition-colors',
                    isActive ? 'bg-forest-800 border-gold text-ivory' : 'border-transparent text-forest-100/85 hover:bg-forest-800/60 hover:text-ivory',
                  )
                }
              >
                <span className="opacity-90">{item.icon}</span>
                <span>{t(item.key)}</span>
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <LanguageSwitch />
    </aside>
  )
}

function LanguageSwitch() {
  const { lang, setLang, t } = useI18n()
  return (
    <div className="px-5 py-4 border-t border-forest-700/60 flex items-center justify-between">
      <span className="text-[0.72rem] uppercase tracking-[0.16em] text-forest-300">{t('ui.language')}</span>
      <div className="flex border border-forest-600 rounded-sm overflow-hidden">
        {(['it', 'en'] as const).map((l) => (
          <button
            key={l}
            onClick={() => setLang(l)}
            className={clsx('px-3 py-1 text-sm font-medium', lang === l ? 'bg-gold text-forest-950' : 'text-forest-100 hover:bg-forest-800')}
            aria-pressed={lang === l}
          >
            {l.toUpperCase()}
          </button>
        ))}
      </div>
    </div>
  )
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { t, lang } = useI18n()
  const mirror = isMirror()   // read-only online copy: no search, no collection, no alerts
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine)

  useEffect(() => {
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => {
      window.removeEventListener('online', on)
      window.removeEventListener('offline', off)
    }
  }, [])

  const status = useQuery({
    queryKey: ['collect-status'],
    queryFn: () => api.get<CollectState>('/collect/status'),
    refetchInterval: (query) => (query.state.data?.running ? 3000 : 30000),
  })
  const sources = useQuery({ queryKey: ['sources'], queryFn: () => api.get<{ sources: SourceInfo[] }>('/sources'), refetchInterval: 60000 })
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api.get<{ show_demo: boolean }>('/settings') })

  const running = status.data?.running ?? false
  const [wasRunning, setWasRunning] = useState(false)
  useEffect(() => {
    if (wasRunning && !running) qc.invalidateQueries()   // new data arrived: refresh every view
    setWasRunning(running)
  }, [running, wasRunning, qc])

  const refresh = useMutation({
    mutationFn: () => api.post('/collect', {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['collect-status'] }),
  })

  const lastCheck = sources.data?.sources.map((s) => s.last_run_at).filter(Boolean).sort().at(-1) ?? null

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (q.trim()) navigate(`/cerca?q=${encodeURIComponent(q.trim())}`)
  }

  useEffect(() => {
    if (!location.pathname.startsWith('/cerca')) setQ('')
  }, [location.pathname])

  return (
    <div className="sticky top-0 z-[1000] bg-paper/95 backdrop-blur border-b border-line">
      {mirror && <MirrorStrip />}
      {settings.data?.show_demo && (
        <div className="bg-[#9A2A17] text-white text-center text-[0.78rem] tracking-[0.14em] py-1 font-semibold">{t('top.demoOn')}</div>
      )}
      <div className="flex items-center gap-2 sm:gap-4 px-3 sm:px-4 md:px-8 h-[56px] md:h-[64px]">
        <button type="button" onClick={onMenu} aria-label={t('mirror.menu')} aria-controls="app-menu"
          className="md:hidden -ml-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-sm text-forest-800 hover:bg-forest-50">
          <Menu size={22} />
        </button>
        {mirror && (
          <div className="md:hidden min-w-0 leading-tight">
            <div className="font-serif text-[1.05rem] font-semibold text-forest-900 truncate">{t('app.name')}</div>
            <div className="text-[0.62rem] uppercase tracking-[0.18em] text-gold-dark truncate">{t('app.subtitle')}</div>
          </div>
        )}
        {!mirror && (
          <form onSubmit={submit} className="flex-1 min-w-0 max-w-xl relative">
            <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('top.search')}
              className="field !pl-10 !py-2.5 bg-white"
              aria-label={t('ui.search')}
            />
          </form>
        )}
        <div className="flex items-center gap-2 sm:gap-4 ml-auto">
          {!online && (
            <span className="flex items-center gap-1.5 text-sm text-warn" title={t('top.offline')}><WifiOff size={16} /> <span className="hidden sm:inline">{t('top.offline')}</span></span>
          )}
          <span className="text-sm text-muted hidden md:inline">
            {t('top.lastUpdate')}: <span className="text-charcoal-soft">{lastCheck ? fmtAgo(lastCheck, lang) : t('top.never')}</span>
          </span>
          {!mirror && <AlertBell />}
          {!mirror && (
            <button className="btn-primary max-sm:!px-3" onClick={() => refresh.mutate()} disabled={running || refresh.isPending || !online}
              title={running ? t('top.refreshing') : t('top.refresh')}>
              <RefreshCw size={16} className={clsx(running && 'animate-spin')} />
              <span className="max-sm:sr-only">{running ? t('top.refreshing') : t('top.refresh')}</span>
            </button>
          )}
        </div>
      </div>
      {!mirror && <FirstRunBanner status={status.data} />}
    </div>
  )
}

/** Attribution required by the sources' terms (FAOSTAT/Eurostat CC BY 4.0, GDELT citation, NASS API notice). */
function AttributionFooter() {
  const { t } = useI18n()
  return (
    <footer className="px-4 md:px-8 py-4 border-t border-line text-[0.75rem] leading-relaxed text-muted max-w-[1600px]">
      <span className="font-medium text-charcoal-soft">{t('footer.sources')}</span>{' '}
      USDA AMS · USDA FAS · USDA NASS · Eurostat (CC BY 4.0) · European Commission · UN Comtrade · FAOSTAT (CC BY 4.0) ·
      ECB · The GDELT Project (gdeltproject.org) · Osservatorio Nazionale Miele · ISMEA · CCIAA Cuneo · CCIAA Arezzo-Siena ·
      Federal Register · EUR-Lex. {t('footer.nass')} {isMirror() ? t('mirror.footer') : t('footer.private')}
    </footer>
  )
}

export function Shell({ children }: { children: ReactNode }) {
  // Phones (below md): the menu slides in over the page; any navigation or Esc closes it.
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()
  useEffect(() => setMenuOpen(false), [location.key])
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  return (
    <div className="flex min-h-screen">
      <Sidebar open={menuOpen} onClose={() => setMenuOpen(false)} />
      {menuOpen && <div className="md:hidden fixed inset-0 z-[1090] bg-forest-950/50" onClick={() => setMenuOpen(false)} aria-hidden />}
      <div className="flex-1 min-w-0 flex flex-col">
        <TopBar onMenu={() => setMenuOpen(true)} />
        <main className="flex-1 px-4 py-5 md:px-8 md:py-7 max-w-[1600px] w-full min-w-0">
          {mirrorHidesRoute(location.pathname) ? <NotInCopy /> : children}
        </main>
        <AttributionFooter />
      </div>
    </div>
  )
}
