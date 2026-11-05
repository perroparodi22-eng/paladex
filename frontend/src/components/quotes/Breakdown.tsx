// Line-by-line landed cost: what the price includes, what is added, the customs value, the duty of
// each alternative and the destination costs, each with its amount per kg and its source and date.
import clsx from 'clsx'
import { ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import { DemoBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber } from '@/lib/format'
import { legalLabel } from '@/components/regulations/format'
import { useQuoteLabels } from './labels'
import type { Landed, Line } from './types'
import { fmtAmount, fmtPerKg, fmtPlain, fmtPrice, fmtTons } from './utils'
import { pageUrl } from '@/lib/links'

type T = (k: string, v?: Record<string, string | number>) => string

function basisText(line: Line, t: T, lang: 'it' | 'en'): string {
  const i = line.input ?? {}
  const basis = i.basis as string | undefined
  const qty = i.quantity_kg as number | undefined
  if (basis === 'per_container') {
    const n = (i.containers as number | undefined) ?? 1
    return qty ? t('quotes.line.perContainerQty', { n, qty: fmtTons(qty, lang) })
      : t('quotes.line.perContainerNoQty', { t: fmtTons((i.container_kg as number | undefined) ?? 20000, lang) })
  }
  if (basis === 'per_kg') return t('quotes.line.perKg')
  if (basis === 'total') return qty ? t('quotes.line.totalQty', { qty: fmtTons(qty, lang) }) : t('quotes.line.totalNoQty')
  return ''
}

function inputText(line: Line, t: T, lang: 'it' | 'en', incoterm: string | null): ReactNode {
  const i = line.input ?? {}
  if (line.key === 'goods') {
    const unit = i.unit === 'lb' ? 'lb' : 'kg'
    return (
      <>
        <span className="num">{fmtPrice(i.amount as number, lang)} {String(i.currency)}/{unit}</span>
        {unit === 'lb' && <span className="num"> = {fmtPrice(Math.round((i.per_kg_original as number) * 1e4) / 1e4, lang)} {String(i.currency)}/kg</span>}
        {i.incoterm ? <> · {String(i.incoterm)}{i.place ? ` ${String(i.place)}` : ''}</> : <> · {t('quotes.line.noIncoterm')}</>}
      </>
    )
  }
  if (line.status === 'included') {
    return (
      <>
        {t('quotes.line.included', { incoterm: incoterm ?? '' })}
        {line.key === 'freight' && i.amount !== undefined && <> · {t('quotes.line.enteredNotAdded', { v: `${fmtPlain(i.amount as number, lang)} ${String(i.currency ?? '')}` })}</>}
        {line.key === 'insurance' && i.pct !== undefined && <> · {t('quotes.line.enteredNotAdded', { v: `${fmtPlain(i.pct as number, lang)} %` })}</>}
      </>
    )
  }
  if (line.status === 'missing') return <span className="text-warn">{t(line.key === 'insurance' ? 'quotes.line.missingF' : 'quotes.line.missing')}</span>
  if (line.key === 'insurance') return t('quotes.line.insurancePct', { pct: fmtPlain(i.pct as number, lang, 3) })
  if (line.key === 'customs_value') return t(`quotes.line.customsBasis.${String(i.basis)}`)
  if (i.basis === 'pct_goods') return t('quotes.line.pctGoods', { pct: fmtPlain(i.amount as number, lang, 3) })
  const amount = `${fmtPlain(i.amount as number, lang)} ${String(i.currency ?? '')}`
  const extra = line.status === 'not_computable' ? <span className="text-warn"> · {t('quotes.line.needsQuantity')}</span> : null
  return <><span className="num">{amount}</span> {basisText(line, t, lang)}{extra}{i.note ? <span className="text-muted"> · {String(i.note)}</span> : null}</>
}

function FxSource({ line }: { line: Line }) {
  const { t, lang } = useI18n()
  if (!line.fx) return null
  if (line.fx.missing) return <div className="text-warn">{t('quotes.line.fxMissing', { ccy: line.fx.currency })}</div>
  return (
    <div className="num">
      {t('quotes.line.fx', { rate: fmtPlain(line.fx.per_eur ?? null, lang, 4), ccy: line.fx.currency, date: fmtDate(line.fx.rate_date, lang) })}
    </div>
  )
}

function Money({ v, ccy, muted }: { v: number | null | undefined; ccy: 'EUR' | 'USD'; muted?: boolean }) {
  const { lang } = useI18n()
  return <span className={clsx('num whitespace-nowrap', muted ? 'text-muted' : 'text-charcoal')}>{fmtPerKg(v, ccy, lang)}</span>
}

function Row({ label, detail, eur, usd, source, strong, tone }: {
  label: ReactNode; detail?: ReactNode; eur: ReactNode; usd: ReactNode; source?: ReactNode; strong?: boolean; tone?: 'sub' | 'total'
}) {
  return (
    <tr className={clsx(tone === 'sub' && 'bg-paper/70', tone === 'total' && 'bg-forest-50/80')}>
      <td className={clsx('min-w-[15rem]', strong && 'font-medium text-charcoal')}>
        <div>{label}</div>
        {detail && <div className="text-[0.84rem] text-muted">{detail}</div>}
      </td>
      <td className="text-right">{eur}</td>
      <td className="text-right">{usd}</td>
      <td className="min-w-[13rem] text-[0.82rem] text-muted">{source}</td>
    </tr>
  )
}

export function Breakdown({ landed }: { landed: Landed }) {
  const { t, lang } = useI18n()
  const labels = useQuoteLabels()
  const label = (l: Line) => {
    if (l.key === 'goods') return t('quotes.line.goods')
    if (l.key === 'customs_value') return t('quotes.line.customsValue')
    if (['freight', 'insurance'].includes(l.key)) return t(`quotes.line.${l.key}`)
    return t(`quotes.cost.${l.key}`)
  }
  const value = (l: Line, ccy: 'eur' | 'usd') => {
    if (l.status === 'missing') return <span className="text-warn">—</span>
    if (l.status === 'not_computable') return <span className="text-warn">—</span>
    return <Money v={l.per_kg?.[ccy]} ccy={ccy === 'eur' ? 'EUR' : 'USD'} muted={l.status === 'included'} />
  }
  const source = (l: Line) => (
    <>
      {l.source?.kind === 'quote' && <div>{t('quotes.line.fromQuote', { date: fmtDate(l.source.date, lang) })}</div>}
      {l.key === 'customs_value' && <div>{t('quotes.line.sumAbove')}</div>}
      <FxSource line={l} />
    </>
  )
  const scen = landed.scenarios
  return (
    <div className="relative overflow-x-auto rounded-sm border border-line bg-white">
      <table className="table-clean min-w-[720px]">
        <thead>
          <tr>
            <th>{t('quotes.breakdown.item')}</th>
            <th className="text-right">€/kg</th>
            <th className="text-right">$/kg</th>
            <th>{t('quotes.breakdown.source')}</th>
          </tr>
        </thead>
        <tbody>
          {landed.lines.map((l, i) => (
            <Row key={`${l.key}-${i}`} label={label(l)} detail={inputText(l, t, lang, landed.incoterm)}
              eur={value(l, 'eur')} usd={value(l, 'usd')} source={source(l)}
              strong={l.key === 'customs_value'} tone={l.key === 'customs_value' ? 'sub' : undefined} />
          ))}
          {scen.map((s) => {
            const m = s.measure
            const legal = m ? legalLabel(m) : null
            return (
              <Row key={`duty-${s.key}`}
                label={<>{t('quotes.line.duty')}: {labels.scenario(s, landed.jurisdiction)}</>}
                detail={
                  <>
                    {!['domestic', 'included', 'unknown'].includes(s.kind) && <span className="num">{labels.rate(s.rate)}</span>}
                    {s.stack.length > 0 && <> + {s.stack.map((x) => labels.rate(x)).join(' + ')}</>}
                    {!s.available && <span className="text-down"> · {t(`quotes.quota.reason.${s.unavailable_reason ?? 'exhausted'}`)}</span>}
                    {s.kind === 'unknown' && <span className="text-warn">{t('quotes.line.dutyUnknown')}</span>}
                  </>
                }
                eur={s.duty ? <Money v={s.duty.eur} ccy="EUR" muted={!s.available} /> : <span className="text-warn">—</span>}
                usd={s.duty ? <Money v={s.duty.usd} ccy="USD" muted={!s.available} /> : <span className="text-warn">—</span>}
                source={m ? (
                  <>
                    {m.is_demo && <DemoBadge />}
                    <div>{m.source?.publisher ?? m.source?.name ?? t('quotes.duty.official')}</div>
                    {m.as_of && <div>{t('quotes.line.checked', { date: fmtDate(m.as_of, lang) })}</div>}
                    {m.legal_url && legal && (
                      <a href={pageUrl(m.legal_url) ?? undefined} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">
                        {legal} <ExternalLink size={11} />
                      </a>
                    )}
                  </>
                ) : s.kind === 'override' ? t('quotes.line.overrideSource') : s.kind === 'included' ? t('quotes.line.fromQuoteShort') : null}
              />
            )
          })}
          {landed.after_duty.map((l, i) => (
            <Row key={`after-${l.key}-${i}`} label={label(l)} detail={inputText(l, t, lang, landed.incoterm)}
              eur={value(l, 'eur')} usd={value(l, 'usd')} source={source(l)} />
          ))}
          {scen.filter((s) => s.available).map((s) => (
            <Row key={`total-${s.key}`} tone="total" strong
              label={scen.filter((x) => x.available).length > 1
                ? t('quotes.line.totalFor', { what: labels.scenario(s, landed.jurisdiction) })
                : t('quotes.line.total')}
              detail={s.total ? t('quotes.line.totalDetail', {
                drum: fmtAmount(s.total.per_drum.eur, 'EUR', lang, 2),
                kg: fmtNumber(landed.assumptions.drum_kg, lang),
              }) : t('quotes.summary.noTotal')}
              eur={s.total ? <Money v={s.total.per_kg.eur} ccy="EUR" /> : <span className="text-warn">—</span>}
              usd={s.total ? <Money v={s.total.per_kg.usd} ccy="USD" /> : <span className="text-warn">—</span>}
              source={landed.headline.complete ? t('quotes.line.totalComplete') : <span className="text-warn">{t('quotes.line.totalIncomplete')}</span>}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}
