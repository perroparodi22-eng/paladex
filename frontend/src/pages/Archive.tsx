// /archivio — historical archive: this year against the previous years (prices, trade, production),
// news by date range, supplier quotes over time, and every revision a source made to a series.
import clsx from 'clsx'
import { NewsArchive } from '@/components/archive/NewsArchive'
import { PriceArchive } from '@/components/archive/PriceArchive'
import { ProductionArchive } from '@/components/archive/ProductionArchive'
import { QuotesArchive } from '@/components/archive/QuotesArchive'
import { RevisionsArchive } from '@/components/archive/RevisionsArchive'
import { useArchiveParams } from '@/components/archive/state'
import { TradeArchive } from '@/components/archive/TradeArchive'
import { VIEWS, type ArchiveView } from '@/components/archive/types'
import { PageHeader } from '@/components/ui'
import { useI18n } from '@/i18n'

export default function Archive() {
  const { t } = useI18n()
  const { sp, set } = useArchiveParams()
  const raw = sp.get('vista') as ArchiveView | null
  const view: ArchiveView = raw && VIEWS.includes(raw) ? raw : 'prezzi'
  return (
    <div>
      <PageHeader eyebrow={t('archive.eyebrow')} title={t('archive.title')} subtitle={t('archive.subtitle')} />
      <div role="tablist" aria-label={t('archive.title')} className="flex flex-wrap gap-1.5 mb-5">
        {VIEWS.map((v) => (
          <button key={v} type="button" role="tab" aria-selected={v === view} onClick={() => set({ vista: v === 'prezzi' ? null : v })}
            className={clsx('rounded-sm border px-3 py-1.5 text-[0.95rem] transition-colors',
              v === view ? 'border-forest-800 bg-forest-800 text-ivory' : 'border-line bg-white text-charcoal-soft hover:border-forest-600 hover:text-forest-800')}>
            {t(`archive.tab.${v}`)}
          </button>
        ))}
      </div>
      {view === 'prezzi' && <PriceArchive />}
      {view === 'commercio' && <TradeArchive />}
      {view === 'produzione' && <ProductionArchive />}
      {view === 'notizie' && <NewsArchive />}
      {view === 'offerte' && <QuotesArchive />}
      {view === 'revisioni' && <RevisionsArchive />}
    </div>
  )
}
