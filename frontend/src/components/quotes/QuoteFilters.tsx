// Status tabs, filters and the exchange-rate choice above the quote list.
import clsx from 'clsx'
import { RotateCcw, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Segmented } from '@/components/ui'
import { useI18n } from '@/i18n'
import { useLabels } from '@/lib/meta'
import type { FxMode, QuotesList } from './types'
import type { QuoteView, StatusFilter } from './useQuoteParams'

const TABS: StatusFilter[] = ['', 'active', 'expiring', 'expired', 'archived']

export function StatusTabs({ value, counts, onChange }: {
  value: StatusFilter; counts: QuotesList['counts'] | undefined; onChange: (v: StatusFilter) => void
}) {
  const { t } = useI18n()
  const n = (k: StatusFilter): number | null => {
    if (!counts) return null
    if (k === '') return counts.active + counts.expiring + counts.expired
    if (k === 'all') return counts.active + counts.expiring + counts.expired + counts.archived
    return counts[k]
  }
  return (
    <div className="flex flex-wrap gap-1.5" role="tablist" aria-label={t('quotes.filters.status')}>
      {TABS.map((k) => {
        const active = value === k
        const count = n(k)
        return (
          <button key={k || 'open'} type="button" role="tab" aria-selected={active} onClick={() => onChange(k)}
            className={clsx('inline-flex items-center gap-1.5 rounded-sm border px-3 py-1.5 text-[0.95rem] transition-colors',
              active ? 'border-forest-800 bg-forest-800 text-ivory' : 'border-line bg-white text-charcoal-soft hover:border-forest-600')}>
            {t(`quotes.tab.${k || 'open'}`)}
            {count !== null && (
              <span className={clsx('num rounded-sm px-1 text-[0.8rem]', active ? 'bg-forest-700 text-gold-light' : 'bg-paper text-muted')}>{count}</span>
            )}
          </button>
        )
      })}
    </div>
  )
}

export function QuoteFilters({ view, data, update, hasFilters, onReset }: {
  view: QuoteView
  data: QuotesList | undefined
  update: (p: Partial<QuoteView>, o?: { replace?: boolean }) => void
  hasFilters: boolean
  onReset: () => void
}) {
  const { t } = useI18n()
  const { country, variety } = useLabels()
  const [text, setText] = useState(view.text)
  useEffect(() => setText(view.text), [view.text])
  useEffect(() => {
    if (text === view.text) return
    const h = setTimeout(() => update({ text }, { replace: true }), 300)
    return () => clearTimeout(h)
  }, [text, view.text, update])

  const facets = data?.facets
  const origins = [...(facets?.origins ?? [])]
  if (view.origin && !origins.some((o) => o.key === view.origin)) origins.push({ key: view.origin, count: 0 })
  const varieties = [...(facets?.varieties ?? [])]
  if (view.variety && !varieties.some((o) => o.key === view.variety)) varieties.push({ key: view.variety, count: 0 })
  const suppliers = [...(facets?.suppliers ?? [])]
  if (view.supplier && !suppliers.some((o) => o.key.toLowerCase() === view.supplier.toLowerCase())) suppliers.push({ key: view.supplier, count: 0 })

  return (
    <div className="mb-4 space-y-3">
      <StatusTabs value={view.status} counts={data?.counts} onChange={(status) => update({ status })} />
      <div className="grid items-end gap-3 sm:grid-cols-2 xl:grid-cols-[repeat(3,minmax(0,13rem))_minmax(0,1fr)]">
        <label className="block min-w-0">
          <span className="label">{t('quotes.filters.origin')}</span>
          <select className="field pr-8" value={view.origin} onChange={(e) => update({ origin: e.target.value })}>
            <option value="">{t('ui.all')}</option>
            {origins.map((o) => <option key={o.key} value={o.key}>{country(o.key)} ({o.count})</option>)}
          </select>
        </label>
        <label className="block min-w-0">
          <span className="label">{t('quotes.filters.variety')}</span>
          <select className="field pr-8" value={view.variety} onChange={(e) => update({ variety: e.target.value })}>
            <option value="">{t('ui.all')}</option>
            {varieties.map((o) => <option key={o.key} value={o.key}>{variety(o.key)} ({o.count})</option>)}
          </select>
        </label>
        <label className="block min-w-0">
          <span className="label">{t('quotes.filters.supplier')}</span>
          <select className="field pr-8" value={view.supplier} onChange={(e) => update({ supplier: e.target.value })}>
            <option value="">{t('ui.all')}</option>
            {suppliers.map((o) => <option key={o.key} value={o.key}>{o.key} ({o.count})</option>)}
          </select>
        </label>
        <label className="block min-w-0">
          <span className="label">{t('quotes.filters.text')}</span>
          <span className="relative block">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input type="search" className="field !pl-9" value={text} placeholder={t('quotes.filters.textPlaceholder')}
              onChange={(e) => setText(e.target.value)} />
          </span>
        </label>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[0.9rem] text-muted">{t('quotes.fx.label')}</span>
          <Segmented<FxMode> size="sm" value={view.fx} onChange={(fx) => update({ fx })}
            options={[{ value: 'received', label: t('quotes.fx.received') }, { value: 'today', label: t('quotes.fx.today') }]} />
        </div>
        {hasFilters && (
          <button type="button" className="btn-ghost !px-2 !py-1 text-[0.9rem]" onClick={onReset}>
            <RotateCcw size={15} /> {t('ui.reset')}
          </button>
        )}
      </div>
    </div>
  )
}
