// Archivio · Offerte fornitori: every supplier quote over time (archived ones included) for an
// origin / variety, and a summary per year that never mixes currencies or Incoterms.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Badge, DemoBadge, EmptyState, ErrorBlock, Loading, Note, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate, fmtNumber, fmtTonnes } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { useArchiveParams } from './state'
import type { QuoteItem, QuotesHistoryResponse } from './types'

function QuoteState({ q }: { q: QuoteItem }) {
  const { t } = useI18n()
  if (q.archived) return <Badge tone="neutral">{t('archive.q.archived')}</Badge>
  if (q.expired) return <Badge tone="warn">{t('archive.q.expired')}</Badge>
  return <Badge tone="up">{t('archive.q.valid')}</Badge>
}

export function QuotesTables({ d }: { d: QuotesHistoryResponse }) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  return (
    <>
      <Panel title={t('archive.q.summaryTitle')} footer={t('archive.q.note')}>
        <div className="overflow-x-auto -mx-5 px-5">
          <table className="table-clean min-w-[620px]">
            <thead>
              <tr>
                <th>{t('archive.q.col.year')}</th>
                <th>{t('archive.q.col.terms')}</th>
                <th className="!text-right">{t('archive.q.col.quotes')}</th>
                <th className="!text-right">{t('archive.q.col.suppliers')}</th>
                <th className="!text-right">{t('archive.q.col.min')}</th>
                <th className="!text-right">{t('archive.q.col.avg')}</th>
                <th className="!text-right">{t('archive.q.col.max')}</th>
              </tr>
            </thead>
            <tbody>
              {d.summary.map((s) => (
                <tr key={`${s.year}-${s.currency}-${s.incoterm}`}>
                  <td className="num font-medium">{s.year}{s.is_demo && <span className="ml-1"><DemoBadge /></span>}</td>
                  <td>{s.incoterm ?? '—'} · {s.currency}/kg</td>
                  <td className="num text-right">{s.quotes}</td>
                  <td className="num text-right">{s.suppliers}</td>
                  <td className="num text-right">{fmtNumber(s.min, lang, 2)}</td>
                  <td className="num text-right font-medium">{fmtNumber(s.average, lang, 2)}</td>
                  <td className="num text-right">{fmtNumber(s.max, lang, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title={t('archive.q.allTitle')}>
        <div className="overflow-x-auto -mx-5 px-5">
          <table className="table-clean min-w-[860px]">
            <thead>
              <tr>
                <th>{t('archive.q.col.date')}</th>
                <th>{t('archive.q.col.supplier')}</th>
                <th>{t('archive.q.col.origin')}</th>
                <th>{t('archive.q.col.variety')}</th>
                <th className="!text-right">{t('archive.q.col.price')}</th>
                <th>{t('archive.q.col.terms')}</th>
                <th className="!text-right">{t('archive.q.col.qty')}</th>
                <th>{t('archive.q.col.valid')}</th>
                <th>{t('archive.q.col.state')}</th>
              </tr>
            </thead>
            <tbody>
              {d.items.map((q) => (
                <tr key={q.id} className={q.archived ? 'text-muted' : undefined}>
                  <td className="num whitespace-nowrap">{fmtDate(q.date_received, lang)}</td>
                  <td className="font-medium">{q.supplier_name}{q.is_demo && <span className="ml-1"><DemoBadge /></span>}</td>
                  <td>{country(q.origin_iso3)}</td>
                  <td>{variety(q.variety)}{q.variety_note && <span className="block text-[0.78rem] text-muted">{q.variety_note}</span>}</td>
                  <td className="num text-right whitespace-nowrap">
                    {fmtNumber(q.price_per_kg, lang, 2)} {q.currency}/kg
                    {q.price_unit === 'lb' && q.price_quoted !== null && (
                      <span className="block text-[0.78rem] text-muted">{t('archive.q.quotedLb', { v: fmtNumber(q.price_quoted, lang, 2), c: q.currency })}</span>
                    )}
                  </td>
                  <td>{[q.incoterm, q.incoterm_place].filter(Boolean).join(' ') || '—'}</td>
                  <td className="num text-right">{q.quantity_kg ? fmtTonnes(q.quantity_kg, lang) : '—'}</td>
                  <td className="num whitespace-nowrap">{fmtDate(q.valid_until, lang)}</td>
                  <td><QuoteState q={q} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  )
}

export function QuotesArchive() {
  const { t } = useI18n()
  const { country, variety } = useLabels()
  const { sp, set } = useArchiveParams()
  const origin = sp.get('qorigine') ?? ''
  const vty = sp.get('qvarieta') ?? ''
  const q = useQuery({
    queryKey: ['archive', 'quotes', origin, vty],
    queryFn: () => api.get<QuotesHistoryResponse>('/archive/quotes', { origin: origin || undefined, variety: vty || undefined }),
    placeholderData: keepPreviousData,
  })
  const d = q.data
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
  if (!d) return null
  if (d.total_all === 0) {
    return (
      <Panel>
        <EmptyState title={t('archive.q.emptyTitle')} hint={t('archive.q.emptyHint')}
          action={<Link to="/offerte" className="btn-secondary">{t('archive.q.go')}</Link>} />
      </Panel>
    )
  }
  return (
    <div className="flex flex-col gap-5">
      <Panel bodyClassName="p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block min-w-[12rem] flex-1 sm:flex-none">
            <span className="label">{t('archive.q.origin')}</span>
            <select className="field" value={origin} onChange={(e) => set({ qorigine: e.target.value || null, qvarieta: null })}>
              <option value="">{t('archive.q.anyOrigin')}</option>
              {d.origins.map((o) => <option key={o.iso3} value={o.iso3}>{country(o.iso3)} ({o.count})</option>)}
            </select>
          </label>
          <label className="block min-w-[12rem] flex-1 sm:flex-none">
            <span className="label">{t('archive.q.variety')}</span>
            <select className="field" value={vty} onChange={(e) => set({ qvarieta: e.target.value || null })}>
              <option value="">{t('archive.q.anyVariety')}</option>
              {d.varieties.map((v) => <option key={v.key} value={v.key}>{variety(v.key)} ({v.count})</option>)}
            </select>
          </label>
        </div>
      </Panel>
      {!d.available ? <Note>{t('archive.q.noMatch')}</Note> : <QuotesTables d={d} />}
    </div>
  )
}
