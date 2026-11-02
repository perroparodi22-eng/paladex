// "Ultimi prezzi pubblicati": latest point per series with m/m and y/y changes and provenance.
import clsx from 'clsx'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge, FreshnessBadge, Panel, StatusBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { Change, DocLink, Swatch } from './bits'
import type { LatestRow, MassUnit } from './types'
import { colorLabel, fmtPeriodLabel, fmtPrice, toUnit, unitLabel } from './utils'

type SortKey = 'default' | 'price' | 'prev' | 'yoy'

const PERIODS_PER_YEAR: Record<string, number> = { M: 12, Q: 4, A: 1 }

function SortTh({ k, sort, onSort, children }: {
  k: SortKey; sort: { key: SortKey; dir: 1 | -1 }; onSort: (k: SortKey) => void; children: string
}) {
  const { t } = useI18n()
  return (
    <th className="!text-right" aria-sort={sort.key === k ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="inline-flex items-center gap-1 uppercase tracking-wider hover:text-forest-800" onClick={() => onSort(k)}
        title={t('prices.latest.sortBy', { c: children })}>
        {children}
        {sort.key === k && (sort.dir === -1 ? <ArrowDown size={12} /> : <ArrowUp size={12} />)}
      </button>
    </th>
  )
}

function shiftLabel(label: string, freq: string, steps: number): string {
  if (freq === 'A') return String(Number(label) + steps)
  if (freq === 'Q') {
    const idx = Number(label.slice(0, 4)) * 4 + Number(label.slice(-1)) - 1 + steps
    return `${Math.floor(idx / 4)}-Q${(idx % 4) + 1}`
  }
  const idx = Number(label.slice(0, 4)) * 12 + Number(label.slice(5, 7)) - 1 + steps
  return `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, '0')}`
}

export function LatestTable({ rows, unit, colorOf, toggle }: {
  rows: LatestRow[]
  unit: MassUnit
  colorOf: (id: string) => string | undefined
  toggle: (id: string) => void
}) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'default', dir: -1 })

  const sorted = useMemo(() => {
    if (sort.key === 'default') return rows
    const val = (r: LatestRow) => (sort.key === 'price' ? r.latest.value : sort.key === 'prev' ? r.change_prev_pct : r.change_yoy_pct)
    return [...rows].sort((a, b) => {
      const va = val(a)
      const vb = val(b)
      if (va === null) return 1
      if (vb === null) return -1
      return (va - vb) * sort.dir
    })
  }, [rows, sort])

  const ccy = rows[0]?.currency ?? 'USD'
  const anyColour = rows.some((r) => r.color_grade)
  const onSort = (key: SortKey) => setSort((s) => (s.key === key ? { key, dir: s.dir === -1 ? 1 : -1 } : { key, dir: -1 }))

  return (
    <Panel
      className="mb-5"
      title={t('prices.latest.title')}
      eyebrow={unitLabel(ccy, unit)}
      bodyClassName="p-0"
      footer={t('prices.latest.subtitle')}
    >
      <div className="overflow-x-auto">
        <table className="table-clean [&_th]:whitespace-nowrap [&_th]:!px-2.5 [&_td]:!px-2.5 [&_td]:!py-2">
          <thead>
            <tr>
              <th className="w-10 !px-2 text-center" title={t('prices.latest.col.chart')}><span className="sr-only">{t('prices.latest.col.chart')}</span></th>
              <th>{t('prices.latest.col.origin')}</th>
              <th>{t('prices.latest.col.variety')}</th>
              {anyColour && <th>{t('prices.latest.col.colour')}</th>}
              <SortTh k="price" sort={sort} onSort={onSort}>{t('prices.latest.col.price')}</SortTh>
              <th>{t('prices.latest.col.period')}</th>
              <SortTh k="prev" sort={sort} onSort={onSort}>{t('prices.latest.col.mom')}</SortTh>
              <SortTh k="yoy" sort={sort} onSort={onSort}>{t('prices.latest.col.yoy')}</SortTh>
              <th>{t('prices.latest.col.source')}</th>
              <th>{t('prices.latest.col.status')}</th>
              <th className="!text-center">{t('prices.latest.col.doc')}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => {
              const c = colorOf(r.series_id)
              const p = r.latest
              const partial = p.expected_points !== null && p.n_points < p.expected_points
              const orig = p.original
              return (
                <tr key={r.series_id} className={clsx(r.is_stale && 'bg-[#FBF7EC]')}>
                  <td className="!px-2 text-center">
                    <button type="button" onClick={() => toggle(r.series_id)} className="p-1 rounded-sm hover:bg-forest-50 align-middle"
                      title={c ? t('prices.latest.hide') : t('prices.latest.show')} aria-pressed={Boolean(c)}>
                      <Swatch color={c} on={Boolean(c)} size={13} />
                    </button>
                  </td>
                  <td className="font-medium text-charcoal whitespace-nowrap">
                    {r.origin_iso3 ? country(r.origin_iso3) : r.origin_label || t('prices.originUnknown')}
                    {r.organic && <Badge tone="forest" className="ml-1.5">{t('prices.organic')}</Badge>}
                  </td>
                  <td className="min-w-[8rem]" title={r.variety_raw.join(', ')}>{variety(r.variety)}</td>
                  {anyColour && <td className="whitespace-nowrap text-charcoal-soft">{r.color_grade ? colorLabel(r.color_grade, t) : '—'}</td>}
                  <td className="text-right whitespace-nowrap">
                    {p.value === null ? (
                      <span className="text-muted" title={orig ? t('prices.latest.fxMissing', { v: `${fmtPrice(orig.value, lang)} ${orig.currency}/${orig.unit}` }) : undefined}>—</span>
                    ) : (
                      <span title={orig ? `${t('prices.chart.as_published')}: ${fmtPrice(orig.value, lang)} ${orig.currency}/${orig.unit}` : undefined}>
                        <span className="num text-[1.05rem] text-charcoal">{fmtPrice(toUnit(p.value, unit), lang)}</span>
                        {p.low !== null && p.high !== null && (
                          <span className="num block text-[0.75rem] text-muted">{fmtPrice(toUnit(p.low, unit), lang)}–{fmtPrice(toUnit(p.high, unit), lang)}</span>
                        )}
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap">
                    <span className="num">{fmtPeriodLabel(r.period_label, lang)}</span>
                    {partial && <span className="block text-[0.72rem] text-muted">{t(p.n_points === 1 ? 'prices.chart.partialOne' : 'prices.chart.partial', { n: p.n_points, m: p.expected_points! })}</span>}
                  </td>
                  <td className="text-right">
                    <Change pct={r.change_prev_pct} cmp={r.previous} expectedLabel={shiftLabel(r.period_label, r.freq, -1)} unit={unit} unitText={unitLabel(r.currency, unit)} />
                  </td>
                  <td className="text-right">
                    <Change pct={r.change_yoy_pct} cmp={r.year_ago} expectedLabel={shiftLabel(r.period_label, r.freq, -(PERIODS_PER_YEAR[r.freq] ?? 12))} unit={unit} unitText={unitLabel(r.currency, unit)} />
                  </td>
                  <td className="text-[0.85rem] leading-snug whitespace-nowrap" title={r.source?.name}>
                    <span className="text-charcoal-soft">{r.source?.publisher || r.source?.name}</span>
                    <span className="block text-muted num text-[0.8rem]" title={t('prov.published')}>{r.published_at ? fmtDate(r.published_at, lang) : '—'}</span>
                  </td>
                  <td>
                    <div className="flex flex-col items-start gap-1" title={r.is_stale ? t('prices.latest.stale') : undefined}>
                      <FreshnessBadge status={r.freshness.status} ageDays={r.freshness.age_days} />
                      {r.data_status !== 'published' && <StatusBadge status={r.data_status} />}
                    </div>
                  </td>
                  <td className="text-center"><DocLink url={r.source_url} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
