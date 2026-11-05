// Landed cost of one quote: one card per duty alternative (in quota / out of quota ...), per kg,
// per 300 kg drum, per 20 t container and for the quoted quantity, in EUR and USD.
import clsx from 'clsx'
import { AlertTriangle, Info } from 'lucide-react'
import { Badge, Note } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtNumber } from '@/lib/format'
import { useQuoteLabels } from './labels'
import type { Flag, Landed, Scenario } from './types'
import { fmtAmount, fmtPerKg, fmtTons } from './utils'

function Figure({ label, eur, usd, digits }: { label: string; eur: number | null; usd: number | null; digits: number }) {
  const { lang } = useI18n()
  return (
    <div className="min-w-0">
      <div className="text-[0.78rem] text-muted">{label}</div>
      <div className="num text-[0.98rem] text-charcoal">{fmtAmount(eur, 'EUR', lang, digits)}</div>
      <div className="num text-[0.82rem] text-muted">{fmtAmount(usd, 'USD', lang, digits)}</div>
    </div>
  )
}

function ScenarioCard({ s, landed, best }: { s: Scenario; landed: Landed; best: boolean }) {
  const { t, lang } = useI18n()
  const labels = useQuoteLabels()
  const a = landed.assumptions
  const tot = s.total
  const roleKey = s.role === 'in_quota' ? 'inQuota' : s.role === 'out_of_quota' ? 'outQuota' : 'applicable'
  return (
    <div className={clsx('panel min-w-0 p-4', !s.available && 'border-dashed bg-paper')}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="eyebrow">{t(`quotes.summary.role.${roleKey}`)}</span>
        {!s.available ? <Badge tone="down">{t(`quotes.quota.reason.${s.unavailable_reason ?? 'exhausted'}`)}</Badge>
          : best && landed.headline.alternatives ? <Badge tone="forest">{t('quotes.summary.lowest')}</Badge> : null}
      </div>
      <div className="mt-1 text-[0.95rem] leading-snug text-charcoal-soft">
        {labels.scenario(s, landed.jurisdiction)}
        <span className="num ml-1 text-charcoal">{s.kind === 'domestic' || s.kind === 'included' || s.kind === 'unknown' ? '' : labels.rate(s.rate)}</span>
      </div>
      {!s.available ? (
        <p className="mt-3 text-[0.9rem] text-muted">{t('quotes.summary.unavailable')}</p>
      ) : !tot ? (
        <p className="mt-3 text-[0.9rem] text-muted">{t('quotes.summary.noTotal')}</p>
      ) : (
        <>
          <div className="mt-2">
            <span className="num text-[1.75rem] leading-tight text-charcoal">{fmtPerKg(tot.per_kg.eur, 'EUR', lang)}</span>
            <span className="ml-1 text-muted">/kg</span>
            <div className="num text-[0.95rem] text-charcoal-soft">{fmtPerKg(tot.per_kg.usd, 'USD', lang)} /kg</div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 border-t border-line-soft pt-3 sm:grid-cols-3">
            <Figure label={t('quotes.summary.perDrum', { kg: fmtNumber(a.drum_kg, lang) })} eur={tot.per_drum.eur} usd={tot.per_drum.usd} digits={2} />
            <Figure label={t('quotes.summary.perContainer', { t: fmtTons(a.container_kg, lang) })} eur={tot.per_container.eur} usd={tot.per_container.usd} digits={0} />
            {tot.quantity && a.quantity_kg ? (
              <Figure label={t('quotes.summary.perQuantity', { t: fmtTons(a.quantity_kg, lang) })} eur={tot.quantity.eur} usd={tot.quantity.usd} digits={0} />
            ) : (
              <div className="min-w-0 text-[0.78rem] text-muted">{t('quotes.summary.noQuantity')}</div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export function LandedSummary({ landed }: { landed: Landed }) {
  const { t } = useI18n()
  const avail = landed.scenarios.filter((s) => s.available && s.total && s.total.per_kg.eur !== null)
  const lowest = avail.length ? avail.reduce((m, s) => ((s.total!.per_kg.eur ?? Infinity) < (m.total!.per_kg.eur ?? Infinity) ? s : m)) : null
  const ordered = [...landed.scenarios].sort((a, b) => Number(b.available) - Number(a.available))
  const missing = landed.flags.filter((f) => f.kind === 'missing')
  const warnings = landed.flags.filter((f) => f.kind === 'warning')
  return (
    <div className="space-y-3">
      <div className={clsx('grid gap-3', ordered.length > 1 && 'md:grid-cols-2', ordered.length > 2 && 'xl:grid-cols-3')}>
        {ordered.map((s) => <ScenarioCard key={s.key} s={s} landed={landed} best={lowest?.key === s.key} />)}
      </div>
      {landed.headline.alternatives && (
        <Note><span>{t('quotes.summary.alternativesNote')}</span></Note>
      )}
      {missing.length > 0 && <FlagNote flags={missing} title={t('quotes.summary.incompleteTitle')} tone="warn" />}
      {warnings.length > 0 && <FlagNote flags={warnings} title={t('quotes.summary.warningsTitle')} tone="danger" />}
      {missing.length === 0 && (
        <p className="text-[0.85rem] text-muted">{t('quotes.summary.complete')}</p>
      )}
    </div>
  )
}

export function FlagNote({ flags, title, tone }: { flags: Flag[]; title: string; tone: 'warn' | 'danger' | 'info' }) {
  const labels = useQuoteLabels()
  return (
    <div className={clsx('rounded-sm border px-3 py-2.5 text-[0.9rem]', {
      'border-[#EED9B0] bg-[#FBF5E8] text-[#7A5414]': tone === 'warn',
      'border-[#EBCDC6] bg-[#FBF1EE] text-[#7E2C20]': tone === 'danger',
      'border-forest-100 bg-forest-50 text-forest-800': tone === 'info',
    })}>
      <div className="flex items-center gap-2 font-medium">
        {tone === 'info' ? <Info size={16} className="shrink-0" /> : <AlertTriangle size={16} className="shrink-0" />}
        {title}
      </div>
      <ul className="mt-1 list-disc space-y-0.5 pl-6">
        {flags.map((f, i) => <li key={`${f.code}-${i}`}>{labels.flag(f)}</li>)}
      </ul>
    </div>
  )
}
