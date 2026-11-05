// /offerte — the owner's private register of supplier quotes, with the landed cost of each (Italy /
// EU customs or USA) from the official duties and ECB rates, a comparison view and a CSV export.
// Quotes never leave this computer and are never deleted by the app (archive instead).
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Download, GitCompareArrows, Lock, Plus, X } from 'lucide-react'
import { useState } from 'react'
import { DemoBadge, ErrorBlock, Loading, PageHeader, Panel } from '@/components/ui'
import { CompareView } from '@/components/quotes/CompareView'
import { QuoteDrawer } from '@/components/quotes/QuoteDrawer'
import { QuoteFilters } from '@/components/quotes/QuoteFilters'
import { QuoteForm } from '@/components/quotes/QuoteForm'
import { QuoteCards, QuoteTable } from '@/components/quotes/QuoteTable'
import { FirstQuote, NoMatches } from '@/components/quotes/QuotesEmpty'
import type { QuotesList, QuotesMeta } from '@/components/quotes/types'
import { useQuoteParams } from '@/components/quotes/useQuoteParams'
import { MAX_COMPARE } from '@/components/quotes/utils'
import { useI18n } from '@/i18n'
import { api, qs } from '@/lib/api'

export default function Quotes() {
  const { t, lang } = useI18n()
  const { view, update, apiFilters, hasFilters } = useQuoteParams()
  const [selected, setSelected] = useState<number[]>([])
  const list = useQuery({
    queryKey: ['quotes', 'list', apiFilters],
    queryFn: () => api.get<QuotesList>('/quotes', apiFilters),
    placeholderData: keepPreviousData,
  })
  const meta = useQuery({ queryKey: ['quotes', 'meta'], queryFn: () => api.get<QuotesMeta>('/quotes/meta'), staleTime: 10 * 60_000 })
  const data = list.data
  const firstUse = data !== undefined && data.total_all === 0
  const anyDemo = (data?.items ?? []).some((i) => i.is_demo)
  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= MAX_COMPARE ? s : [...s, id]))
  const reset = () => update({ status: '', origin: '', variety: '', supplier: '', text: '' })
  const newQuote = () => update({ form: { mode: 'new' }, open: null })
  const exportHref = `/api/quotes/export${qs({ ...apiFilters, lang })}`

  return (
    <div className="min-w-0">
      <PageHeader
        eyebrow={t('quotes.eyebrow')}
        title={t('quotes.title')}
        subtitle={t('quotes.subtitle')}
        actions={(
          <>
            {anyDemo && <DemoBadge />}
            {data && !firstUse && (
              <a className="btn-secondary" href={exportHref} download title={t('quotes.exportHint')}>
                <Download size={17} /> {t('quotes.export')}
              </a>
            )}
            <button type="button" className="btn-primary" onClick={newQuote}><Plus size={18} /> {t('quotes.new')}</button>
          </>
        )}
      />

      {list.isLoading ? <Loading /> : list.error && !data ? <ErrorBlock error={list.error} onRetry={() => list.refetch()} /> : firstUse ? (
        <FirstQuote onAdd={newQuote} fxNewest={meta.data?.fx_newest} />
      ) : data && (
        <>
          <QuoteFilters view={view} data={data} update={update} hasFilters={hasFilters} onReset={reset} />
          <Panel
            bodyClassName="!p-0"
            title={t('quotes.list.title', { n: data.total })}
            actions={selected.length > 0 ? (
              <div className="flex flex-wrap items-center justify-end gap-2">
                <span className="text-[0.9rem] text-muted">{t('quotes.compare.selected', { n: selected.length, max: MAX_COMPARE })}</span>
                <button type="button" className="btn-ghost !px-2 !py-1 text-[0.9rem]" onClick={() => setSelected([])}>
                  <X size={15} /> {t('quotes.compare.clear')}
                </button>
                <button type="button" className="btn-primary !py-1.5" disabled={selected.length < 2}
                  title={selected.length < 2 ? t('quotes.compare.needTwo') : undefined}
                  onClick={() => update({ compare: selected, open: null })}>
                  <GitCompareArrows size={16} /> {t('quotes.compare.open')}
                </button>
              </div>
            ) : (
              <span className="hidden text-[0.88rem] text-muted sm:inline">{t('quotes.compare.hint', { max: MAX_COMPARE })}</span>
            )}
            footer={(
              <div className="flex flex-col gap-1">
                <span>{t(view.fx === 'today' ? 'quotes.list.footerToday' : 'quotes.list.footer')}</span>
                <span className="inline-flex items-start gap-1.5"><Lock size={13} className="mt-1 shrink-0" />{t('quotes.privacy')}</span>
              </div>
            )}
          >
            {list.error && <div className="p-4"><ErrorBlock error={list.error} onRetry={() => list.refetch()} /></div>}
            {data.items.length === 0 ? (
              <NoMatches onReset={reset} archivedHint={!hasFilters && data.counts.archived > 0} />
            ) : (
              <>
                <QuoteCards items={data.items} selected={selected} onToggle={toggle} onOpen={(id) => update({ open: id })} />
                <QuoteTable items={data.items} selected={selected} onToggle={toggle} onOpen={(id) => update({ open: id })} />
              </>
            )}
          </Panel>
        </>
      )}

      {view.open !== null && !view.form && (
        <QuoteDrawer id={view.open} fx={view.fx} onFx={(fx) => update({ fx }, { replace: true })}
          onClose={() => update({ open: null })}
          onEdit={(id) => update({ open: null, form: { mode: 'edit', id } })}
          onOpenQuote={(id) => update({ open: id })} />
      )}
      {view.compare.length > 0 && view.open === null && !view.form && (
        <CompareView ids={view.compare} basis={view.basis} fx={view.fx}
          onBasis={(basis) => update({ basis }, { replace: true })} onFx={(fx) => update({ fx }, { replace: true })}
          onClose={() => update({ compare: [], basis: 'conservative' })} onOpen={(id) => update({ open: id })} />
      )}
      {view.form && (
        <QuoteForm
          key={view.form.mode === 'edit' ? `edit-${view.form.id}` : 'new'}
          mode={view.form.mode}
          quoteId={view.form.mode === 'edit' ? view.form.id : undefined}
          suppliers={(data?.facets.suppliers ?? []).map((s) => s.key)}
          onClose={() => update({ form: null, open: view.form?.mode === 'edit' ? view.form.id : null })}
          onSaved={(q) => update({ form: null, open: q.id })}
        />
      )}
    </div>
  )
}
