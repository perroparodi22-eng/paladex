// Homepage — the "morning terminal". In about two minutes the owner should know what is
// happening in the honey market without navigating: data health, today's summary, key
// prices, trade, alerts, news, official reports and the countries on the move.
// Every block shows its source and when its data arrived; empty blocks say which source
// will fill them. Data: GET /api/overview (backend/paladex/api/overview.py).
import { useQuery } from '@tanstack/react-query'
import { Database } from 'lucide-react'
import { PageHeader, QueryState } from '@/components/ui'
import { BriefingPanel } from '@/components/overview/BriefingPanel'
import { fmtClock, fmtLongDate, RefreshButton } from '@/components/overview/parts'
import { PriceTiles } from '@/components/overview/PriceTiles'
import { AlertsPanel, CountryActivityPanel, NewsPanel, ReportsPanel } from '@/components/overview/SidePanels'
import { StatusStrip } from '@/components/overview/StatusStrip'
import { TradeHighlights } from '@/components/overview/TradeHighlights'
import type { OverviewData } from '@/components/overview/types'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { isMirror } from '@/lib/mirror'
import type { CollectState } from '@/lib/types'

function FirstLaunch({ running }: { running: boolean }) {
  const { t } = useI18n()
  return (
    <section className="panel mb-6 border-forest-100 bg-forest-50/60">
      <div className="flex flex-wrap items-start gap-4 px-5 py-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-forest-800 text-gold-light">
          <Database size={20} />
        </div>
        <div className="min-w-0 flex-1 basis-[28rem]">
          <h2 className="font-serif text-[1.2rem] font-semibold text-forest-900">{t('overview.welcome.title')}</h2>
          <p className="mt-1 max-w-3xl text-[0.95rem] text-charcoal-soft">{t('overview.welcome.body')}</p>
          <p className="mt-1.5 max-w-3xl text-[0.85rem] text-muted">{t('overview.welcome.honest')}</p>
        </div>
        <div className="pt-1"><RefreshButton running={running} /></div>
      </div>
    </section>
  )
}

function Body({ d, running }: { d: OverviewData; running: boolean }) {
  const firstLaunch = d.status.never_collected && !d.prices.items.length && !d.trade.available
    && !d.news.items.length && !d.reports.items.length
  return (
    <>
      <StatusStrip status={{ ...d.status, collection_running: d.status.collection_running || running }} quality={d.quality} showDemo={d.show_demo} />
      {firstLaunch && <FirstLaunch running={running} />}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="min-w-0 space-y-6 xl:col-span-2">
          <BriefingPanel b={d.briefing} />
          <PriceTiles block={d.prices} />
          <TradeHighlights block={d.trade} />
        </div>
        {/* Right column; on tablets the four panels flow into two balanced columns. */}
        <div className="min-w-0 gap-6 md:columns-2 xl:columns-1 [&>*]:mb-6 [&>*]:break-inside-avoid">
          {!isMirror() && <AlertsPanel block={d.alerts} />}
          <NewsPanel block={d.news} />
          <ReportsPanel block={d.reports} />
          <CountryActivityPanel block={d.countries} />
        </div>
      </div>
    </>
  )
}

export default function Overview() {
  const { t, lang } = useI18n()
  const q = useQuery({
    queryKey: ['overview', lang],
    queryFn: () => api.get<OverviewData>('/overview', { lang }),
    refetchInterval: 5 * 60_000,
  })
  // Shares the cache entry the top bar polls, so a running collection shows here too.
  const collect = useQuery({ queryKey: ['collect-status'], queryFn: () => api.get<CollectState>('/collect/status') })

  return (
    <div>
      <PageHeader
        eyebrow={t('overview.eyebrow')}
        title={fmtLongDate(q.data?.today, lang)}
        subtitle={t('overview.tagline')}
        actions={q.data && (
          <span className="text-sm text-muted">{t('overview.pageUpdated', { time: fmtClock(q.data.generated_at, lang) })}</span>
        )}
      />
      <QueryState q={q}>{(d) => <Body d={d} running={collect.data?.running ?? false} />}</QueryState>
    </div>
  )
}
