// Weather by region, last 3 months: temperature difference from normal and rainfall in % of normal,
// with the automatic signals of the last 12 months explained in plain words. Grouped by country.
import clsx from 'clsx'
import { AlertTriangle, Flower2 } from 'lucide-react'
import { Fragment } from 'react'
import { Panel, Select } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtPeriod } from '@/lib/format'
import { fmtAnomaly, fmtPctOfNormal, monthSpan, regionName, RULE_ORDER } from './format'
import { AssessmentMark, ConditionBadge, FlagLine } from './parts'
import type { HarvestRegion, RegionMonth, WeatherResponse } from './types'
import type { SignalFilter } from './useHarvestParams'

export function matchesSignal(r: HarvestRegion, signal: SignalFilter): boolean {
  if (!signal) return true
  if (signal === 'any') return r.flags.length > 0
  return r.flags.some((f) => f.rule === signal)
}

export function WeatherTable({ data, country, signal, selected, onSignal, onSelect }: {
  data: WeatherResponse; country: string; signal: SignalFilter; selected: string
  onSignal: (s: SignalFilter) => void; onSelect: (key: string) => void
}) {
  const { t, lang } = useI18n()
  const months = data.recent_months
  const rows = data.regions.filter((r) => (!country || r.country_iso3 === country) && matchesSignal(r, signal))
  const groups = data.countries
    .map((c) => ({ c, regions: rows.filter((r) => r.country_iso3 === c.iso3) }))
    .filter((g) => g.regions.length)
  const cols = 3 + months.length
  return (
    <Panel title={t('harvest.table.title')} eyebrow={t('harvest.table.eyebrow')} className="min-w-0" bodyClassName="!p-0"
      actions={<AssessmentMark className="hidden sm:inline-flex" />}>
      <div className="flex flex-wrap items-end gap-3 px-4 pt-3 pb-3 sm:px-5 border-b border-line-soft">
        <Select label={t('harvest.table.filter')} value={signal} onChange={(e) => onSignal(e.target.value as SignalFilter)} className="w-full sm:w-64">
          <option value="">{t('harvest.table.filterAll')}</option>
          <option value="any">{t('harvest.table.filterAny')}</option>
          {RULE_ORDER.map((k) => <option key={k} value={k}>{t(`harvest.cond.${k}`)}</option>)}
        </Select>
        <p className="text-[0.8rem] text-muted sm:hidden">{t('harvest.table.scrollHint')}</p>
      </div>
      {!groups.length ? (
        <p className="px-5 py-6 text-muted">{t('harvest.table.empty')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-[0.92rem]">
            <thead>
              <tr className="border-b border-line text-left text-[0.82rem] text-muted">
                <th className="sticky left-0 z-[1] bg-paper py-2 pl-4 pr-2 font-medium sm:pl-5">{t('harvest.table.region')}</th>
                <th className="py-2 px-2 font-medium">{t('harvest.table.flowering')}</th>
                {months.map((m) => <th key={m} className="py-2 px-2 font-medium whitespace-nowrap">{fmtPeriod(m, lang)}</th>)}
                <th className="py-2 px-2 pr-4 font-medium sm:pr-5">{t('harvest.table.flags')}</th>
              </tr>
            </thead>
            <tbody>
              {groups.map(({ c, regions }) => (
                <Fragment key={c.iso3}>
                  <tr className="bg-ivory/60">
                    <td colSpan={cols} className="sticky left-0 py-1.5 pl-4 sm:pl-5 font-serif text-[0.98rem] font-semibold text-charcoal">
                      {(lang === 'it' ? c.name_it : c.name_en) ?? c.iso3}
                    </td>
                  </tr>
                  {regions.map((r) => (
                    <RegionRow key={r.key} r={r} months={months} selected={r.key === selected} onSelect={onSelect} />
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="border-t border-line-soft px-4 py-2.5 text-[0.8rem] text-muted sm:px-5">
        <span title={t('harvest.table.tempTitle')}>{t('harvest.table.temp')}: {t('harvest.table.tempTitle')}</span> ·{' '}
        <span>{t('harvest.table.rain')}: {t('harvest.table.rainTitle')}</span> ·{' '}
        <span className="inline-flex items-center gap-1"><Flower2 size={12} className="text-gold-dark" /> {t('harvest.table.inFlowering')}</span>
      </div>
    </Panel>
  )
}

function RegionRow({ r, months, selected, onSelect }: { r: HarvestRegion; months: string[]; selected: boolean; onSelect: (k: string) => void }) {
  const { t, lang } = useI18n()
  const byLabel = new Map(r.recent.map((m) => [m.period_label, m]))
  return (
    <tr className={clsx('border-b border-line-soft align-top', selected && 'bg-gold-pale/40')} aria-current={selected ? 'true' : undefined}>
      <td className={clsx('sticky left-0 z-[1] py-2.5 pl-4 pr-2 sm:pl-5', selected ? 'bg-[#FAF5E6]' : 'bg-white')}>
        <button type="button" onClick={() => onSelect(r.key)} className="link text-left font-medium" title={t('harvest.table.details')}>
          {regionName(r, lang)}
        </button>
        <div className="mt-0.5"><ConditionBadge condition={r.condition} recent={Boolean(r.condition_recent) || r.condition === 'normal'} /></div>
      </td>
      <td className="py-2.5 px-2 whitespace-nowrap text-[0.85rem] text-charcoal-soft">
        {monthSpan(r.context.flowering_months, lang)}
        <div className="text-[0.72rem] uppercase tracking-wide text-muted">{t('harvest.table.contextShort')}</div>
      </td>
      {months.map((label) => <MonthCell key={label} m={byLabel.get(label)} />)}
      <td className="py-2.5 px-2 pr-4 sm:pr-5 min-w-[300px]">
        {r.flags.length ? (
          <div className="flex flex-col gap-1.5">{r.flags.map((f) => <FlagLine key={`${f.rule}-${f.months[0]}`} flag={f} />)}</div>
        ) : (
          <span className="text-[0.86rem] text-muted">{r.has_data ? t('harvest.table.noFlags') : t('harvest.table.noData')}</span>
        )}
      </td>
    </tr>
  )
}

export function MonthCell({ m }: { m: RegionMonth | undefined }) {
  const { t, lang } = useI18n()
  if (!m || !m.points_with_data) {
    return <td className="py-2.5 px-2 text-[0.85rem] text-muted whitespace-nowrap">{t('harvest.table.noData')}</td>
  }
  const t2 = m.temp_anomaly_c
  const p = m.precip_pct
  return (
    <td className="py-2.5 px-2 whitespace-nowrap">
      <div className="flex items-center gap-1.5">
        <span className="text-[0.72rem] text-muted w-[3.1rem]" title={t('harvest.table.tempTitle')}>{t('harvest.table.temp')}</span>
        <span className={clsx('num', t2 !== null && t2 >= 2 ? 'text-down font-medium' : t2 !== null && t2 <= -2 ? 'text-[#2F64B0]' : 'text-charcoal')}>
          {fmtAnomaly(t2, lang)}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-[0.72rem] text-muted w-[3.1rem]" title={t('harvest.table.rainTitle')}>{t('harvest.table.rain')}</span>
        <span className={clsx('num', p !== null && p < 60 ? 'text-warn font-medium' : p !== null && p > 160 ? 'text-[#2F64B0] font-medium' : 'text-charcoal')}>
          {fmtPctOfNormal(p, lang)}
        </span>
        {m.exceptional_points.length > 0 && (
          <span title={t('harvest.table.exceptionalTitle', { points: m.exceptional_points.join(', ') })}>
            <AlertTriangle size={13} className="text-warn" />
          </span>
        )}
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[0.7rem] text-muted">
        {m.flowering && <span className="inline-flex items-center gap-0.5" title={t('harvest.table.inFlowering')}><Flower2 size={13} className="text-gold-dark" /></span>}
        {m.data_status === 'provisional' && <span className="uppercase tracking-wide text-warn" title={t('harvest.table.provisionalTitle')}>{t('harvest.table.provisional')}</span>}
        {m.points_with_data < m.points_total && <span>{t('harvest.table.pointsPartial', { n: m.points_with_data, total: m.points_total })}</span>}
      </div>
    </td>
  )
}
