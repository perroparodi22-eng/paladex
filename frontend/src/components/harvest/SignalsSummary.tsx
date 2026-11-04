// Beside the map: how many regions carry each automatic signal, and the signals of the last 3 months
// (each one a click away from its region). Automatic assessments, labelled as such.
import { Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { regionName, RULE_ORDER } from './format'
import { ConditionDot, FlagLine } from './parts'
import type { WeatherResponse } from './types'
import type { SignalFilter } from './useHarvestParams'

export function SignalsSummary({ data, country = '', onSelect, onSignal }: {
  data: WeatherResponse; country?: string; onSelect: (key: string) => void; onSignal: (s: SignalFilter) => void
}) {
  const { t, lang } = useI18n()
  const withData = data.regions.filter((r) => r.has_data && (!country || r.country_iso3 === country))
  const c = country ? data.countries.find((x) => x.iso3 === country) : undefined
  const countryName = c ? ((lang === 'it' ? c.name_it : c.name_en) ?? c.iso3) : null
  const counts = RULE_ORDER.map((rule) => ({
    rule,
    n: withData.filter((r) => r.flags.some((f) => f.rule === rule)).length,
    recent: withData.filter((r) => r.flags.some((f) => f.rule === rule && f.recent)).length,
  }))
  const quiet = withData.filter((r) => !r.flags.length).length
  const recent = withData.map((r) => ({ r, flags: r.flags.filter((f) => f.recent) })).filter((x) => x.flags.length)
  const label = lang === 'it' ? data.assessment_label_it : data.assessment_label_en
  const regionsText = (n: number) => (
    <span className="text-[0.9rem] text-charcoal-soft"><span className="num">{n}</span> {n === 1 ? t('harvest.summary.region1') : t('harvest.summary.regions')}</span>
  )
  return (
    <Panel title={countryName ? `${t('harvest.summary.title')} · ${countryName}` : t('harvest.summary.title')} eyebrow={label} className="min-w-0">
      <ul className="flex flex-col gap-1.5">
        {counts.map((c) => (
          <li key={c.rule} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <ConditionDot condition={c.rule} />
            <button type="button" className="link text-left font-medium" onClick={() => onSignal(c.rule)} title={t('harvest.summary.filter')}>
              {t(`harvest.cond.${c.rule}`)}
            </button>
            {regionsText(c.n)}
            {c.recent > 0 && <span className="text-[0.8rem] text-muted">· {t('harvest.summary.recentCount', { n: c.recent })}</span>}
          </li>
        ))}
        <li className="flex items-center gap-2">
          <ConditionDot condition="normal" />
          <span className="font-medium text-charcoal-soft">{t('harvest.cond.normal')}</span>
          {regionsText(quiet)}
        </li>
      </ul>
      <div className="mt-4 border-t border-line-soft pt-3">
        <div className="eyebrow mb-2">{t('harvest.summary.recentTitle')}</div>
        {recent.length ? (
          <ul className="flex flex-col gap-2.5">
            {recent.map(({ r, flags }) => (
              <li key={r.key} className="min-w-0">
                <button type="button" className="link text-left text-[0.92rem] font-medium" onClick={() => onSelect(r.key)}>
                  {regionName(r, lang)}
                </button>
                <span className="text-[0.82rem] text-muted"> · {(lang === 'it' ? r.country_name_it : r.country_name_en) ?? r.country_iso3}</span>
                <div className="mt-0.5 flex flex-col gap-1">{flags.map((f) => <FlagLine key={`${f.rule}-${f.months[0]}`} flag={f} />)}</div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[0.9rem] text-muted">{t('harvest.summary.noRecent')}</p>
        )}
      </div>
      <p className="mt-4 text-[0.85rem] text-muted">{t('harvest.detail.select')}</p>
    </Panel>
  )
}
