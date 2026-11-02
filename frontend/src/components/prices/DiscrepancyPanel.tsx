// Shows where sources disagree (>10% for the same origin, variety, market, period).
// Every value is shown with its source; nothing is chosen or averaged away.
import { AlertTriangle } from 'lucide-react'
import { DemoBadge, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtPct } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { DocLink } from './bits'
import type { Discrepancy, MassUnit } from './types'
import { colorLabel, fmtPeriodLabel, fmtPrice, toUnit, unitLabel } from './utils'

export const DISCREPANCY_ANCHOR = 'discrepanze'

/** Compact notice for the top of the page, linking to the detailed panel. */
export function DiscrepancyNotice({ items }: { items: Discrepancy[] }) {
  const { t } = useI18n()
  if (!items.length) return null
  return (
    <div className="mb-5 flex items-start gap-3 rounded-sm border border-[#EED9B0] bg-[#FBF5E8] px-4 py-3 text-[#7A5414]">
      <AlertTriangle size={18} className="mt-0.5 shrink-0" />
      <div className="flex-1">
        <span className="font-semibold">{t('prices.disc.title')}. </span>
        {t('prices.disc.notice', { n: items.length, t: items[0].threshold_pct })}{' '}
        <a href={`#${DISCREPANCY_ANCHOR}`} className="link whitespace-nowrap">{t('prices.disc.see')}</a>
      </div>
    </div>
  )
}

export function DiscrepancyPanel({ items, unit, className }: { items: Discrepancy[]; unit: MassUnit; className?: string }) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  if (!items.length) return null
  return (
    <div id={DISCREPANCY_ANCHOR} className={className}>
      <Panel title={t('prices.disc.title')} eyebrow={unitLabel(items[0].currency, unit)} bodyClassName="p-0">
        <ul>
          {items.slice(0, 12).map((d) => (
            <li key={`${d.origin_iso3}-${d.variety}-${d.market_iso3}-${d.period_label}`} className="px-5 py-3 border-b border-line-soft last:border-b-0">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium text-charcoal">
                  {d.origin_iso3 ? country(d.origin_iso3) : t('prices.originUnknown')} · {variety(d.variety)}
                  <span className="text-muted font-normal"> · {fmtPeriodLabel(d.period_label, lang)}</span>
                  {d.market_iso3 && <span className="text-muted font-normal"> · {t('prices.marketShort')} {country(d.market_iso3)}</span>}
                </span>
                <span className="num text-warn text-sm">{t('prices.disc.spread', { pct: fmtPct(d.spread_pct, lang, 1, false) })}</span>
              </div>
              <ul className="mt-1.5 flex flex-col gap-1">
                {d.entries.map((e, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-x-3 text-[0.88rem]">
                    <span className="num text-charcoal w-16 text-right">{fmtPrice(toUnit(e.value, unit), lang)}</span>
                    <span className="text-charcoal-soft">{e.source?.publisher || e.source?.name}</span>
                    {e.color_grades.length > 0 && <span className="text-muted">{t('prices.disc.grades', { c: e.color_grades.map((c) => colorLabel(c, t)).join(', ') })}</span>}
                    {e.published_at && <span className="text-muted">{t('prov.published')} {fmtDate(e.published_at, lang)}</span>}
                    {e.is_demo && <DemoBadge />}
                    <DocLink url={e.source_url} />
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}
