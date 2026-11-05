// Wording for the landed-cost calculation in the UI language (keys in i18n/pages/quotes.ts).
import { useCallback } from 'react'
import { useI18n } from '@/i18n'
import { fmtDate } from '@/lib/format'
import type { Flag, Rate, Scenario, ScenarioCompact } from './types'
import { fmtPlain, fmtRate, fmtTons } from './utils'

type AnyScenario = Pick<Scenario, 'kind' | 'role' | 'rate'> & { quota?: ScenarioCompact['quota']; measure?: Scenario['measure'] }

export function useQuoteLabels() {
  const { t, lang } = useI18n()

  const rate = useCallback((r: Rate | null | undefined) => fmtRate(r, lang, t('quotes.duty.free')), [lang, t])

  /** "Entro il contingente 090881 (Mercosur)", "Dazio pieno paesi terzi", "Preferenza tariffaria" ... */
  const scenario = useCallback((s: AnyScenario, jurisdiction: 'EU' | 'US'): string => {
    const quota = s.quota ?? s.measure?.quota ?? null
    const geo = (s.measure?.extra?.geo_area as { description?: string; group?: boolean } | undefined) ?? undefined
    switch (s.kind) {
      case 'trq_in': {
        const base = t('quotes.scenario.trq_in', { order: quota?.order_number ?? '' })
        return geo?.group && geo.description ? `${base} · ${geo.description}` : base
      }
      case 'mfn':
        if (jurisdiction === 'US') return t('quotes.scenario.mfnUS')
        return s.role === 'out_of_quota' ? t('quotes.scenario.mfnOut') : t('quotes.scenario.mfnEU')
      case 'preference': {
        if (jurisdiction === 'US') {
          const codes = (s.measure?.extra?.program_codes as string[] | undefined)?.join(', ')
          const names = (s.measure?.extra?.program_names as string[] | undefined)?.join('; ')
          return codes ? t('quotes.scenario.programUS', { codes: names ? `${codes} – ${names}` : codes }) : t('quotes.scenario.preference')
        }
        return s.role === 'out_of_quota' ? t('quotes.scenario.preferenceOut') : t('quotes.scenario.preference')
      }
      case 'trq_out': return t('quotes.scenario.trq_out')
      case 'override': return t('quotes.scenario.override')
      case 'included': return t('quotes.scenario.included')
      case 'domestic': return t('quotes.scenario.domestic')
      case 'unknown': return t('quotes.scenario.unknown')
      default: return t('quotes.scenario.other')
    }
  }, [t])

  const flag = useCallback((f: Flag): string => {
    const p = f.params ?? {}
    const key = `quotes.flag.${f.code}`
    const vars: Record<string, string | number> = {}
    for (const [k, v] of Object.entries(p)) if (typeof v === 'string' || typeof v === 'number') vars[k] = v
    if (f.code === 'fx_missing') {
      vars.currencies = ((p.currencies as string[] | undefined) ?? []).join(', ')
      vars.date = fmtDate(p.date as string | undefined, lang)
    }
    if (f.code === 'quota_balance_below_quantity') vars.balance = fmtTons(p.balance_kg as number | undefined, lang)
    if (f.code === 'quota_unavailable') vars.reason = t(`quotes.quota.reason.${String(p.reason ?? 'exhausted')}`)
    if (f.code === 'duty_override') vars.pct = fmtPlain(p.pct as number | undefined, lang, 2)
    if (f.code === 'cost_no_quantity') vars.cost = t(`quotes.cost.${String(p.cost ?? 'other')}`).toLowerCase()
    if (f.code === 'us_antidumping') vars.case = (p.case_number as string | undefined) ?? t('quotes.duty.caseUnknown')
    if (f.code === 'duty_unavailable') return t(p.has_data ? 'quotes.flag.duty_unavailable' : 'quotes.flag.duty_unavailableNoData')
    if (!vars.order) vars.order = (p.order as string | undefined) ?? ''
    const s = t(key, vars)
    return s === key ? f.code : s
  }, [t, lang])

  return { rate, scenario, flag }
}
