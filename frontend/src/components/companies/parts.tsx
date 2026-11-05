// Building blocks of the Companies page (/aziende) and of the "Aziende" block of a country profile:
// what a country publishes (availability), the lists with figures (exact value or band, as published)
// and the lists of names only (alphabetical, never ranked), each with its source.
import { ExternalLink, Search } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { Badge, DemoBadge, FreshnessBadge, Note, Panel, SourceLine } from '@/components/ui'
import { expectedUpdate, useI18n } from '@/i18n'
import { fmtCompact, fmtDate, fmtNumber, fmtPeriod } from '@/lib/format'
import type { Lang } from '@/lib/types'
import type {
  Availability, AvailabilityStatus, CompanyList, FigureCell, FiguresList, PeriodInfo, RegisterList,
} from './types'

const TONE: Record<AvailabilityStatus, 'forest' | 'gold' | 'warn' | 'neutral' | 'outline'> = {
  figures: 'forest', register: 'gold', unavailable: 'warn', not_published: 'neutral', unverified: 'outline',
}
export const PREVIEW_ROWS = 25

export function AvailabilityBadge({ status, short = false }: { status: AvailabilityStatus; short?: boolean }) {
  const { t } = useI18n()
  return <Badge tone={TONE[status]}>{t(`companies.status.${status}${short ? '.short' : ''}`)}</Badge>
}

/** What the country's authorities publish, and why nothing more is shown. */
export function AvailabilityNote({ a, compact = false }: { a: Availability; compact?: boolean }) {
  const { t, lang } = useI18n()
  const reason = lang === 'it' ? a.reason_it : a.reason_en
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <AvailabilityBadge status={a.status} />
        {a.checked_on && <span className="text-[0.8rem] text-muted">{t('companies.checkedOn', { d: fmtDate(a.checked_on, lang) })}</span>}
      </div>
      <p className={compact ? 'text-[0.92rem] leading-relaxed' : 'leading-relaxed'}>{reason}</p>
      {a.authority && a.authority !== '—' && (
        <div className="text-[0.85rem] text-muted">
          {t('companies.authority')}: <span className="text-charcoal-soft">{a.authority}</span>
          {a.url && (
            <>
              {' · '}
              <a href={a.url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">
                {t('companies.officialSite')} <ExternalLink size={12} />
              </a>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function monthShort(month: number, lang: Lang): string {
  return fmtDate(`2001-${String(month).padStart(2, '0')}-15`, lang, { month: 'short' })
}

/** "2025", or "2026 (gen–ott)" for a running year. */
export function periodHeading(p: PeriodInfo, lang: Lang, t: (k: string, v?: Record<string, string | number>) => string): string {
  if (p.running_year && p.months_covered) return t('companies.ytd', { y: p.label, m: monthShort(p.months_covered[1], lang) })
  return fmtPeriod(p.label, lang)
}

/** A figure exactly as the source gives it: an exact value, or a band shown as a band. */
export function FigureValue({ cell, currency, lang }: { cell: FigureCell | undefined; currency: string | null; lang: Lang }) {
  if (!cell) return <span className="text-muted">—</span>
  if (cell.value !== null) {
    return <span title={`${fmtNumber(cell.value, lang, 2)} ${currency ?? ''}`.trim()}>{fmtNumber(cell.value, lang, 0)}</span>
  }
  if (cell.value_min !== null || cell.value_max !== null) {
    const lo = cell.value_min !== null ? fmtCompact(cell.value_min, lang) : null
    const hi = cell.value_max !== null ? fmtCompact(cell.value_max, lang) : null
    return <span>{lo && hi ? `${lo}–${hi}` : lo ? `> ${lo}` : `< ${hi}`}</span>
  }
  if (cell.volume_kg !== null) return <span>{fmtNumber(cell.volume_kg / 1000, lang, 1)} t</span>
  return <span className="text-muted">—</span>
}

function SearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { t } = useI18n()
  return (
    <label className="relative block w-full sm:max-w-xs">
      <span className="sr-only">{t('companies.search')}</span>
      <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
      <input type="search" value={value} onChange={(e) => onChange(e.target.value)} placeholder={t('companies.search')}
        className="field !py-1.5 pl-8" />
    </label>
  )
}

function useFiltered<T extends { name: string; location: string | null }>(items: T[], query: string, showAll: boolean) {
  return useMemo(() => {
    const q = query.trim().toLocaleLowerCase()
    const found = q ? items.filter((c) => `${c.name} ${c.location ?? ''}`.toLocaleLowerCase().includes(q)) : items
    return { found, shown: q || showAll ? found : found.slice(0, PREVIEW_ROWS) }
  }, [items, query, showAll])
}

function MoreButton({ total, showAll, onToggle }: { total: number; showAll: boolean; onToggle: () => void }) {
  const { t } = useI18n()
  if (total <= PREVIEW_ROWS) return null
  return (
    <button type="button" onClick={onToggle} className="mt-2 text-sm link">
      {showAll ? t('companies.showLess') : t('companies.showAll', { n: total })}
    </button>
  )
}

/** Companies x years with the published figure; position and share only for the latest complete year. */
export function FiguresTable({ list, initialQuery = '' }: { list: FiguresList; initialQuery?: string }) {
  const { t, lang } = useI18n()
  const [query, setQuery] = useState(initialQuery)
  const [showAll, setShowAll] = useState(false)
  const { found, shown } = useFiltered(list.companies, query, showAll)
  const ref = list.ref_period
  // Newest year first (on a phone the recent figures are the first ones visible), the share right after
  // the year it belongs to. The position sits in the sticky company cell, so it never scrolls away.
  const cols: ({ kind: 'period'; p: PeriodInfo } | { kind: 'share' })[] = []
  for (const p of [...list.periods].reverse()) {
    cols.push({ kind: 'period', p })
    if (p.label === ref) cols.push({ kind: 'share' })
  }
  const hasTotals = Object.keys(list.national_totals).length > 0
  return (
    <div>
      {list.companies.length > PREVIEW_ROWS && <div className="mb-2"><SearchBox value={query} onChange={setQuery} /></div>}
      <div className="overflow-x-auto">
        <table className="table-clean w-full min-w-[680px]">
          <thead>
            <tr>
              <th className="sticky left-0 z-[1] bg-paper min-w-[10.5rem] sm:min-w-[16rem]">{t('companies.col.rank')} · {t('companies.col.company')}</th>
              {cols.map((col) => col.kind === 'share'
                ? <th key="share" className="!text-right whitespace-nowrap">{t('companies.col.share', { y: ref ?? '' })}</th>
                : <th key={col.p.label} className="!text-right whitespace-nowrap">{periodHeading(col.p, lang, t)}</th>)}
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.name}>
                <td className="sticky left-0 z-[1] bg-white font-medium">
                  <span className="flex gap-2">
                    <span className="num text-muted font-normal w-5 shrink-0 text-right">{c.rank_in_ref ?? ''}</span>
                    <span>
                      {c.name}
                      {c.location && <span className="block text-[0.8rem] text-muted font-normal">{c.location}</span>}
                    </span>
                  </span>
                </td>
                {cols.map((col) => col.kind === 'share'
                  ? (
                    <td key="share" className="text-right num whitespace-nowrap text-muted">
                      {ref && c.values[ref]?.share_pct !== undefined ? `${fmtNumber(c.values[ref].share_pct, lang, 1)}%` : ''}
                    </td>
                  ) : (
                    <td key={col.p.label} className="text-right num whitespace-nowrap">
                      <FigureValue cell={c.values[col.p.label]} currency={list.currency} lang={lang} />
                    </td>
                  ))}
              </tr>
            ))}
            {found.length === 0 && (
              <tr><td colSpan={cols.length + 1} className="text-muted">{t('companies.noMatch')}</td></tr>
            )}
          </tbody>
          {hasTotals && (
            <tfoot>
              <tr>
                <td className="sticky left-0 z-[1] bg-white font-semibold"><span className="pl-7">{t('companies.total')}</span></td>
                {cols.map((col) => col.kind === 'share'
                  ? <td key="share" className="text-right num text-muted">100%</td>
                  : (
                    <td key={col.p.label} className="text-right num font-semibold whitespace-nowrap">
                      {list.national_totals[col.p.label] !== undefined ? fmtNumber(list.national_totals[col.p.label], lang, 0) : '—'}
                    </td>
                  ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      <MoreButton total={found.length} showAll={showAll || !!query} onToggle={() => setShowAll((v) => !v)} />
    </div>
  )
}

/** Names only (no figure published): alphabetical, with the months each company is listed in. */
export function RegisterTable({ list, initialQuery = '' }: { list: RegisterList; initialQuery?: string }) {
  const { t, lang } = useI18n()
  const [query, setQuery] = useState(initialQuery)
  const [showAll, setShowAll] = useState(false)
  const { found, shown } = useFiltered(list.companies, query, showAll)
  // How long a company is listed: months of a monthly list, years of a yearly one; for a register
  // (approved establishments) the count of months it was seen listed says nothing about trade: no column.
  const unit = list.frequency === 'A' ? 'years' : list.frequency === 'register' ? null : 'months'
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[0.85rem] text-muted">
          {t('companies.periodRange', { a: fmtPeriod(list.first_period, lang), b: fmtPeriod(list.latest_period, lang) })}
        </span>
        {list.companies.length > PREVIEW_ROWS && <SearchBox value={query} onChange={setQuery} />}
      </div>
      <div className="overflow-x-auto">
        <table className="table-clean w-full">
          <thead>
            <tr>
              <th>{t('companies.col.company')}</th>
              {unit && <th className="!text-right whitespace-nowrap">{t(unit === 'years' ? 'companies.col.years' : 'companies.col.months')}</th>}
              <th className="!text-right whitespace-nowrap">{t(unit === 'years' ? 'companies.col.latestYear' : unit ? 'companies.col.latest' : 'companies.col.latestList')}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((c, i) => (
              <tr key={`${c.name}|${c.location}|${i}`}>
                <td>
                  <span className="font-medium">{c.name}</span>
                  {c.location && <span className="block text-[0.8rem] text-muted">{c.location}</span>}
                </td>
                {unit && (
                  <td className="text-right num whitespace-nowrap">
                    {unit === 'years'
                      ? (c.periods.length === 1 ? t('companies.yearsListedOne') : t('companies.yearsListed', { n: c.periods.length }))
                      : (c.periods.length === 1 ? t('companies.monthsListedOne') : t('companies.monthsListed', { n: c.periods.length }))}
                  </td>
                )}
                <td className="text-right whitespace-nowrap">{fmtPeriod(c.latest_period, lang)}</td>
              </tr>
            ))}
            {found.length === 0 && <tr><td colSpan={unit ? 3 : 2} className="text-muted">{t('companies.noMatch')}</td></tr>}
          </tbody>
        </table>
      </div>
      <MoreButton total={found.length} showAll={showAll || !!query} onToggle={() => setShowAll((v) => !v)} />
    </div>
  )
}

/** "What the figure is", in plain words. */
export function WhatNote({ list }: { list: CompanyList }) {
  const { t } = useI18n()
  if (list.measure_kind === 'none') return <Note>{t('companies.what.none')}</Note>
  const basis = list.value_basis ?? ''
  const running = list.periods.find((p) => p.running_year)
  return (
    <Note>
      {t(`companies.what.${list.measure_kind}`, { basis, cur: list.currency ?? '' })}
      {list.ref_period && <> {t('companies.rankNote', { y: list.ref_period })}</>}
      {running?.months_covered && <> <RunningNote p={running} /></>}
    </Note>
  )
}

function RunningNote({ p }: { p: PeriodInfo }) {
  const { t, lang } = useI18n()
  return <>{t('companies.ytdNote', { y: p.label, m: fmtDate(`2001-${String(p.months_covered![1]).padStart(2, '0')}-15`, lang, { month: 'long' }) })}</>
}

/** Source, period, collection date, rhythm and freshness of one list. */
export function ListSource({ list }: { list: CompanyList }) {
  const { t, lang } = useI18n()
  const s = list.source
  const period = list.measure_kind === 'none'
    ? (list.first_period === list.latest_period ? list.latest_period : `${fmtPeriod(list.first_period, lang)} – ${fmtPeriod(list.latest_period, lang)}`)
    : list.periods.length ? `${list.periods[0].label} – ${list.periods[list.periods.length - 1].label}` : ''
  const rhythm = s ? expectedUpdate(s, lang) : null
  return (
    <div className="flex flex-col gap-1">
      <SourceLine p={{ source: s, source_url: list.source_url, published_at: list.published_at, collected_at: list.collected_at, period_label: period, is_demo: list.is_demo }} />
      <div className="flex flex-wrap items-center gap-2 text-[0.8rem] text-muted">
        {s?.freshness && <FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} />}
        {rhythm && <span>{t('companies.rhythm')}: {rhythm}</span>}
        {list.web_url && (
          <a href={list.web_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">
            {t('companies.openSource')} <ExternalLink size={12} />
          </a>
        )}
      </div>
    </div>
  )
}

export function ListPanel({ list }: { list: CompanyList }) {
  const { t } = useI18n()
  const count = list.company_count === 1 ? t('companies.companiesOne') : t('companies.companies', { n: list.company_count })
  return (
    <Panel
      title={t(`companies.role.${list.role}`)}
      eyebrow={`${count} · HS ${list.hs_code}`}
      actions={list.is_demo ? <DemoBadge /> : undefined}
      footer={<ListSource list={list} />}
    >
      <div className="flex flex-col gap-3">
        <WhatNote list={list} />
        {list.measure_kind === 'none' ? <RegisterTable list={list} /> : <FiguresTable list={list} />}
      </div>
    </Panel>
  )
}

export function Small({ children }: { children: ReactNode }) {
  return <span className="text-[0.82rem] text-muted">{children}</span>
}
