// The list of quotes: key columns, the landed cost (€/kg) of each and its status. From 1280 px a
// table; below (tablet with the sidebar, phone) one card per quote, so the landed cost is always
// visible without scrolling sideways. The page itself never scrolls sideways.
import clsx from 'clsx'
import { AlertTriangle } from 'lucide-react'
import { Badge, DemoBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { useQuoteLabels } from './labels'
import type { LandedCompact, Quote, QuoteListItem } from './types'
import { DRUM_KG, fmtPerKg, fmtPrice, fmtTons, MAX_COMPARE, STATUS_TONE } from './utils'

/** Landed cost per kg in EUR: one figure, or the range of the duty alternatives (never one chosen silently). */
export function LandedCell({ landed, compact = false, align = 'right' }: { landed: LandedCompact; compact?: boolean; align?: 'left' | 'right' }) {
  const { t, lang } = useI18n()
  const labels = useQuoteLabels()
  const h = landed.headline
  const missing = h.missing.length > 0
  const warn = h.warnings.length > 0
  const extraDuty = h.warnings.some((w) => w === 'us_antidumping' || w === 'us_additional_duty_review')
  const quotaOut = h.warnings.includes('quota_unavailable')
  if (h.eur_per_kg_min === null || h.eur_per_kg_max === null) {
    return (
      <div className={align === 'right' ? 'text-right' : 'text-left'}>
        <span className="text-muted" title={t('quotes.list.notComputable')}>{t('quotes.list.notComputableShort')}</span>
        {!compact && <div className="text-[0.78rem] text-muted">{reasonOf(landed, t)}</div>}
      </div>
    )
  }
  const range = h.alternatives && Math.abs(h.eur_per_kg_max - h.eur_per_kg_min) > 1e-9
  const avail = landed.scenarios.filter((s) => s.available && s.total_per_kg)
  return (
    <div className={align === 'right' ? 'text-right' : 'text-left'}>
      <div className="num whitespace-nowrap text-[1.02rem] text-charcoal">
        {range ? <>{fmtPerKg(h.eur_per_kg_min, 'EUR', lang)} – {fmtPerKg(h.eur_per_kg_max, 'EUR', lang)}</> : fmtPerKg(h.eur_per_kg_max, 'EUR', lang)}
        {(missing || warn) && (
          <AlertTriangle size={14} className={clsx('mb-0.5 ml-1 inline', warn ? 'text-down' : 'text-warn')}
            aria-label={extraDuty ? t('quotes.list.warning') : missing ? t('quotes.list.incomplete') : t('quotes.list.toVerify')} />
        )}
      </div>
      {!compact && (
        <div className="text-[0.78rem] leading-snug text-muted">
          {range
            ? avail.map((s) => `${t(`quotes.scenarioShort.${s.kind}`)} ${labels.rate(s.rate)}`).join(' / ')
            : t(`quotes.dest.short.${landed.destination}`)}
          {extraDuty && <span className="block text-down">{t('quotes.list.warning')}</span>}
          {quotaOut && <span className="block text-down">{t('quotes.list.quotaOut')}</span>}
          {missing && <span className="block text-warn">{t('quotes.list.incomplete')}</span>}
        </div>
      )}
    </div>
  )
}

function reasonOf(landed: LandedCompact, t: (k: string, v?: Record<string, string | number>) => string): string {
  if (landed.fx.missing.length) return t('quotes.list.reasonFx', { ccy: landed.fx.missing.join(', ') })
  if (landed.headline.missing.includes('duty_unavailable')) return t('quotes.list.reasonDuty')
  return t('quotes.list.reasonOther')
}

export function StatusChip({ q }: { q: Pick<Quote, 'status' | 'days_to_expiry'> }) {
  const { t } = useI18n()
  const label = q.status === 'expiring' && q.days_to_expiry !== null
    ? (q.days_to_expiry === 0 ? t('quotes.status.expiringToday') : t('quotes.status.expiringIn', { n: q.days_to_expiry }))
    : t(`quotes.status.${q.status}`)
  return <Badge tone={STATUS_TONE[q.status]}>{label}</Badge>
}

export function QuotePrice({ q }: { q: Pick<Quote, 'price' | 'price_unit' | 'price_per_kg' | 'currency'> }) {
  const { lang } = useI18n()
  return (
    <>
      <span className="num whitespace-nowrap">{fmtPrice(q.price, lang)} {q.currency}/{q.price_unit === 'lb' ? 'lb' : 'kg'}</span>
      {q.price_unit === 'lb' && (
        <span className="num block whitespace-nowrap text-[0.78rem] text-muted">= {fmtPrice(Math.round(q.price_per_kg * 1e4) / 1e4, lang)} {q.currency}/kg</span>
      )}
    </>
  )
}

/** Tablet and phone layout (under 1280 px): one card per quote, landed cost visible without scrolling. */
export function QuoteCards({ items, selected, onToggle, onOpen }: {
  items: QuoteListItem[]
  selected: number[]
  onToggle: (id: number) => void
  onOpen: (id: number) => void
}) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  const full = selected.length >= MAX_COMPARE
  return (
    <ul className="divide-y divide-line-soft xl:hidden">
      {items.map((q) => {
        const isSel = selected.includes(q.id)
        return (
          <li key={q.id} className={clsx('flex gap-3 px-4 py-3', isSel && 'bg-forest-50/70')}>
            <input type="checkbox" className="mt-1 h-[20px] w-[20px] shrink-0 accent-forest-700" checked={isSel}
              disabled={!isSel && full} onChange={() => onToggle(q.id)}
              aria-label={t('quotes.list.selectOne', { name: q.supplier_name })} />
            <div className="min-w-0 flex-1 cursor-pointer" onClick={() => onOpen(q.id)}>
              <span className="flex items-start justify-between gap-2">
                <button type="button" className="min-w-0 break-words text-left font-medium text-charcoal"
                  onClick={(e) => { e.stopPropagation(); onOpen(q.id) }}>{q.supplier_name}</button>
                <StatusChip q={q} />
              </span>
              <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[0.86rem] text-muted">
                {q.is_demo && <DemoBadge />}
                <span>{country(q.origin_iso3)} · {variety(q.variety)}</span>
              </span>
              <span className="mt-1 block text-[0.88rem] text-charcoal-soft">
                <QuotePrice q={q} />
                <span className="text-muted">
                  {' · '}{q.incoterm ?? t('quotes.notGiven')}{q.incoterm_place ? ` ${q.incoterm_place}` : ''}
                  {q.quantity_kg ? <> · <span className="num">{fmtTons(q.quantity_kg, lang)}</span></> : null}
                </span>
              </span>
              <div className="mt-1.5 rounded-sm border border-line-soft bg-paper/70 px-2.5 py-1.5">
                <div className="eyebrow">{t('quotes.list.landed')}</div>
                <LandedCell landed={q.landed} align="left" />
              </div>
              <span className="mt-1 block text-[0.8rem] text-muted">
                {q.valid_until ? t('quotes.list.until', { date: fmtDate(q.valid_until, lang) }) : t('quotes.list.noExpiry')}
              </span>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export function QuoteTable({ items, selected, onToggle, onOpen }: {
  items: QuoteListItem[]
  selected: number[]
  onToggle: (id: number) => void
  onOpen: (id: number) => void
}) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  const full = selected.length >= MAX_COMPARE
  return (
    <div className="relative hidden overflow-x-auto xl:block">
      <table className="table-clean min-w-[940px]">
        <thead>
          <tr>
            <th className="w-10"><span className="sr-only">{t('quotes.list.select')}</span></th>
            <th>{t('quotes.list.supplier')}</th>
            <th>{t('quotes.list.origin')}</th>
            <th className="text-right">{t('quotes.list.priceIncoterm')}</th>
            <th className="text-right">{t('quotes.list.quantity')}</th>
            <th className="text-right">{t('quotes.list.landed')}</th>
            <th>{t('quotes.list.expiry')}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((q) => {
            const isSel = selected.includes(q.id)
            const drums = q.quantity_kg ? q.quantity_kg / DRUM_KG : null
            return (
              <tr key={q.id} className={clsx('cursor-pointer', isSel && 'bg-forest-50/70', q.status === 'archived' && 'text-muted')}
                onClick={() => onOpen(q.id)}>
                <td onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" className="h-[18px] w-[18px] accent-forest-700" checked={isSel}
                    disabled={!isSel && full} onChange={() => onToggle(q.id)}
                    aria-label={t('quotes.list.selectOne', { name: q.supplier_name })}
                    title={!isSel && full ? t('quotes.compare.max', { n: MAX_COMPARE }) : t('quotes.list.selectHint')} />
                </td>
                <td className="min-w-[11rem]">
                  <button type="button" className="text-left font-medium text-charcoal hover:text-forest-700"
                    onClick={(e) => { e.stopPropagation(); onOpen(q.id) }}>
                    {q.supplier_name}
                  </button>
                  <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[0.8rem] text-muted">
                    {q.is_demo && <DemoBadge />}
                    <span>{t('quotes.list.received', { date: fmtDate(q.date_received, lang) })}</span>
                  </div>
                </td>
                <td>
                  <div>{country(q.origin_iso3)}</div>
                  <div className="text-[0.84rem] text-muted">{variety(q.variety)}{q.variety_note ? ` · ${q.variety_note}` : ''}</div>
                </td>
                <td className="text-right">
                  <QuotePrice q={q} />
                  <div className="text-[0.82rem] text-muted">
                    {q.incoterm ? <span className="num text-charcoal-soft">{q.incoterm}</span> : t('quotes.notGiven')}
                    {q.incoterm_place ? ` ${q.incoterm_place}` : ''}
                  </div>
                </td>
                <td className="text-right">
                  {q.quantity_kg ? (
                    <>
                      <span className="num whitespace-nowrap">{fmtTons(q.quantity_kg, lang)}</span>
                      {drums !== null && (
                        <div className="num whitespace-nowrap text-[0.78rem] text-muted">
                          {t('quotes.list.drums', { n: fmtNumber(drums, lang, Number.isInteger(drums) ? 0 : 1) })}
                        </div>
                      )}
                    </>
                  ) : <span className="text-muted">—</span>}
                </td>
                <td><LandedCell landed={q.landed} /></td>
                <td>
                  <StatusChip q={q} />
                  <div className="mt-1 text-[0.8rem] text-muted">
                    {q.valid_until ? t('quotes.list.until', { date: fmtDate(q.valid_until, lang) }) : t('quotes.list.noExpiry')}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
