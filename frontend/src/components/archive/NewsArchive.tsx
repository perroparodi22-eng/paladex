// Archivio · Notizie: search the stored news by date range (and words, country), with the number of
// articles per month and the span of the whole archive.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AiBadge, DemoBadge, EmptyState, ErrorBlock, Loading, Note, Panel } from '@/components/ui'
import { PRIORITY_COUNTRIES } from '@/components/news/NewsFilters'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate, fmtPeriod } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { useArchiveParams } from './state'
import type { NewsArchiveResponse } from './types'

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function defaultNewsRange(today = new Date()): { from: string; to: string } {
  const from = new Date(today)
  from.setFullYear(today.getFullYear() - 1)
  return { from: isoDay(from), to: isoDay(today) }
}

export function NewsList({ d }: { d: NewsArchiveResponse }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  return (
    <ul className="flex flex-col divide-y divide-line-soft">
      {d.items.map((a) => {
        const shown = a.display?.[lang]
        return (
          <li key={a.id} className="py-3 min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted mb-0.5">
              {a.is_demo && <DemoBadge />}
              <span className="font-medium text-charcoal-soft">{a.publisher || a.source?.name || '—'}</span>
              <span>· {fmtDate(a.published_at ?? a.collected_at, lang)}</span>
              <span>· {t('archive.n.relevance', { n: a.relevance_score })}</span>
              {a.countries.length > 0 && <span className="break-words">· {a.countries.slice(0, 4).map((c) => country(c)).join(', ')}</span>}
            </div>
            <a href={a.url} target="_blank" rel="noreferrer" className="font-serif text-[1.05rem] leading-snug hover:text-forest-700 break-words">
              {shown?.title ?? a.title}
              <ExternalLink size={13} className="inline ml-1 align-[-1px] text-muted" />
            </a>
            {shown?.title_is_ai && (
              <div className="text-sm text-muted mt-0.5 flex flex-wrap items-center gap-1.5"><AiBadge /> <span className="break-words">{a.title}</span></div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

export function NewsArchive() {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const { sp, set } = useArchiveParams()
  const def = defaultNewsRange()
  const applied = { q: sp.get('nq') ?? '', from: sp.get('dal') ?? def.from, to: sp.get('al') ?? def.to,
    country: sp.get('npaese') ?? '', page: Math.max(1, Number(sp.get('npag')) || 1) }
  const [form, setForm] = useState({ q: applied.q, from: applied.from, to: applied.to, country: applied.country })
  useEffect(() => {      // the form follows the address (back / forward, shared links)
    setForm({ q: applied.q, from: applied.from, to: applied.to, country: applied.country })
  }, [applied.q, applied.from, applied.to, applied.country])
  const badRange = Boolean(applied.from && applied.to && applied.from > applied.to)
  const q = useQuery({
    queryKey: ['archive', 'news', applied],
    queryFn: () => api.get<NewsArchiveResponse>('/archive/news', {
      q: applied.q || undefined, from: applied.from || undefined, to: applied.to || undefined,
      country: applied.country || undefined, page: applied.page, page_size: 20,
    }),
    enabled: !badRange,
    placeholderData: keepPreviousData,
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    set({ nq: form.q.trim() || null, dal: form.from || null, al: form.to || null, npaese: form.country || null, npag: null })
  }
  const d = q.data
  return (
    <div className="flex flex-col gap-5">
      <Panel bodyClassName="p-4">
        <form onSubmit={submit} className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))_auto] items-end">
          <label className="block min-w-0">
            <span className="label">{t('archive.n.q')}</span>
            <input type="search" className="field" value={form.q} placeholder={t('archive.n.qPh')} onChange={(e) => setForm({ ...form, q: e.target.value })} />
          </label>
          <label className="block min-w-0">
            <span className="label">{t('archive.n.from')}</span>
            <input type="date" className="field" value={form.from} onChange={(e) => setForm({ ...form, from: e.target.value })} />
          </label>
          <label className="block min-w-0">
            <span className="label">{t('archive.n.to')}</span>
            <input type="date" className="field" value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })} />
          </label>
          <label className="block min-w-0">
            <span className="label">{t('archive.n.country')}</span>
            <select className="field" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })}>
              <option value="">{t('archive.n.anyCountry')}</option>
              {PRIORITY_COUNTRIES.map((c) => <option key={c} value={c}>{country(c)}</option>)}
            </select>
          </label>
          <button type="submit" className="btn-primary justify-center">{t('archive.n.search')}</button>
        </form>
      </Panel>
      {badRange ? <Note tone="warn">{t('archive.n.badRange')}</Note>
        : q.error ? <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
        : !d ? <Panel><Loading /></Panel>
        : d.archive.articles === 0 ? <Panel><EmptyState hint={t('archive.n.noArchive')} /></Panel>
        : (
          <>
            <Note>{t('archive.n.span', { a: fmtDate(d.archive.oldest, lang), n: d.archive.articles })}</Note>
            {d.months.length > 0 && (
              <Panel title={t('archive.n.perMonth')}>
                <div className="h-[200px] -ml-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={d.months.map((m) => ({ ...m, label: fmtPeriod(m.month, lang) }))} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke="#E9E3D3" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 12, fill: '#6B6A62' }} tickLine={false} axisLine={{ stroke: '#DDD6C4' }} minTickGap={8} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: '#6B6A62' }} tickLine={false} axisLine={false} width={36} />
                      <Tooltip formatter={(v: number) => [v, t('archive.n.perMonth')]} />
                      <Bar dataKey="count" fill="#143A2B" isAnimationActive={false} maxBarSize={36} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Panel>
            )}
            <Panel title={d.total === 1 ? t('archive.n.resultsOne') : t('archive.n.results', { n: d.total })}>
              {d.items.length === 0 ? <EmptyState hint={t('archive.n.none')} /> : <NewsList d={d} />}
              {d.pages > 1 && (
                <div className="flex items-center justify-between gap-3 mt-4">
                  <button type="button" className="btn-secondary" disabled={applied.page <= 1} onClick={() => set({ npag: String(applied.page - 1) })}>{t('archive.n.prev')}</button>
                  <span className="text-sm text-muted">{t('archive.n.page', { p: applied.page, n: d.pages })}</span>
                  <button type="button" className="btn-secondary" disabled={applied.page >= d.pages} onClick={() => set({ npag: String(applied.page + 1) })}>{t('archive.n.next')}</button>
                </div>
              )}
            </Panel>
          </>
        )}
    </div>
  )
}
