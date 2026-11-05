// The rules behind the automatic assessments, exactly as the backend applies them.
import { Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtNumber } from '@/lib/format'
import { ConditionDot } from './parts'
import type { WeatherMeta } from './types'

const OPERATORS: Record<string, string> = { '<': '<', '>': '>', '>=': '≥', '<=': '≤' }

export function RulesPanel({ meta }: { meta: WeatherMeta }) {
  const { t, lang } = useI18n()
  const label = lang === 'it' ? meta.assessment_label_it : meta.assessment_label_en
  return (
    <Panel title={t('harvest.rules.title')} eyebrow={label} className="min-w-0">
      <ul className="flex flex-col gap-3">
        {meta.rules.map((r) => (
          <li key={r.key} className="flex gap-2.5">
            <span className="mt-1.5"><ConditionDot condition={r.key} /></span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                <span className="font-medium text-charcoal">{lang === 'it' ? r.label_it : r.label_en}</span>
                <span className="num text-[0.82rem] text-muted">
                  <span className="whitespace-nowrap">{t('harvest.rules.threshold')} {OPERATORS[r.operator] ?? r.operator} {fmtNumber(r.threshold, lang, r.unit === '%' ? 0 : 1)}{r.unit === '%' ? '%' : ` ${r.unit}`}</span>
                  {' · '}<span className="whitespace-nowrap">{t('harvest.rules.minMonths')} ≥ {r.min_months}</span>
                </span>
              </div>
              <p className="text-[0.9rem] text-charcoal-soft">{lang === 'it' ? r.rule_it : r.rule_en}</p>
              <p className="text-[0.85rem] text-muted">{t('harvest.rules.why')}: {lang === 'it' ? r.why_it : r.why_en}</p>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-3 border-t border-line-soft pt-3 text-[0.85rem] leading-relaxed text-muted">
        {lang === 'it' ? meta.rules_scope_it : meta.rules_scope_en}
      </p>
    </Panel>
  )
}
