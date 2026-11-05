// Market reference for a quote's origin and variety: three different price types in three separate
// blocks (EU customs unit value, price paid to US importers, Italian wholesale), never averaged or
// mixed, each row with its period, publication date and source.
import { ExternalLink } from 'lucide-react'
import { Badge, DemoBadge, Note } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtPeriod } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { colorLabel } from '@/components/prices/utils'
import type { MarketReference as MR, RefBlock, RefRow } from './types'
import { fmtPerKg, fmtPrice, fmtTons } from './utils'

const OLD_DAYS = 120

function Age({ r }: { r: RefRow }) {
  const { t, lang } = useI18n()
  if (r.age_days <= OLD_DAYS) return null
  const months = Math.round(r.age_days / 30.4)
  return <Badge tone="warn" title={t('quotes.ref.oldTitle', { date: fmtDate(r.period_end, lang) })}>{t('quotes.ref.old', { n: fmtNumber(months, lang) })}</Badge>
}

function Src({ r }: { r: RefRow }) {
  const { t, lang } = useI18n()
  return (
    <div className="text-[0.8rem] text-muted">
      {r.is_demo && <DemoBadge />} {r.source?.publisher ?? r.source?.name}
      {r.published_at && <> · {t('prov.published')} {fmtDate(r.published_at, lang)}</>}
      {r.source_url && (
        <> · <a href={r.source_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">{t('prov.original')} <ExternalLink size={11} /></a></>
      )}
    </div>
  )
}

function range(r: RefRow, lang: 'it' | 'en'): string {
  if (r.price_low !== null && r.price_high !== null && r.price_low !== r.price_high) {
    return `${fmtPrice(r.price_low, lang)}–${fmtPrice(r.price_high, lang)}`
  }
  return fmtPrice(r.price_value, lang)
}

function EuRows({ b }: { b: RefBlock }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  return (
    <table className="table-clean min-w-[560px]">
      <thead><tr><th>{t('quotes.ref.market')}</th><th>{t('prov.period')}</th><th className="text-right">€/kg (CIF)</th><th className="text-right">{t('quotes.ref.volume')}</th></tr></thead>
      <tbody>
        {b.rows.map((r) => (
          <tr key={r.id}>
            <td>{country(r.market_iso3)}<Src r={r} /></td>
            <td className="whitespace-nowrap">{fmtPeriod(r.period_label, lang)} <Age r={r} /></td>
            <td className="num text-right">{fmtPerKg(r.eur_per_kg ?? r.price_value, 'EUR', lang)}</td>
            <td className="num text-right">{fmtTons(r.volume_kg, lang)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function UsRows({ b }: { b: RefBlock }) {
  const { t, lang } = useI18n()
  const { variety } = useLabels()
  return (
    <table className="table-clean min-w-[680px]">
      <thead>
        <tr>
          <th>{t('quotes.ref.grade')}</th><th>{t('prov.period')}</th>
          <th className="text-right">{t('quotes.ref.published')} (USD/lb)</th>
          <th className="text-right">$/kg</th><th className="text-right">€/kg</th>
        </tr>
      </thead>
      <tbody>
        {b.rows.map((r) => (
          <tr key={r.id}>
            <td>
              {r.color_grade ? colorLabel(r.color_grade, t) : t('quotes.ref.noGrade')}
              {!r.variety_match && <div className="text-[0.8rem] text-muted">{variety(r.variety)}{r.variety_raw ? ` (${r.variety_raw})` : ''}</div>}
              <Src r={r} />
            </td>
            <td className="whitespace-nowrap">{fmtPeriod(r.period_label, lang)} <Age r={r} /></td>
            <td className="num text-right">{range(r, lang)}</td>
            <td className="num text-right">{fmtPerKg(r.usd_per_kg, 'USD', lang)}</td>
            <td className="num text-right" title={r.fx_date ? t('quotes.ref.fxTitle', { date: fmtDate(r.fx_date, lang) }) : undefined}>
              {fmtPerKg(r.eur_per_kg, 'EUR', lang)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ItRows({ b }: { b: RefBlock }) {
  const { t, lang } = useI18n()
  return (
    <table className="table-clean min-w-[640px]">
      <thead><tr><th>{t('quotes.ref.product')}</th><th>{t('prov.period')}</th><th className="text-right">€/kg</th><th>{t('quotes.ref.terms')}</th></tr></thead>
      <tbody>
        {b.rows.map((r) => (
          <tr key={r.id}>
            <td>{r.variety_raw ?? '—'}{r.market_location ? <span className="text-muted"> · {r.market_location}</span> : null}<Src r={r} /></td>
            <td className="whitespace-nowrap">{fmtPeriod(r.period_label, lang)} <Age r={r} /></td>
            <td className="num text-right">{range(r, lang)}</td>
            <td className="text-[0.84rem] text-muted">{r.terms}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Block({ b }: { b: RefBlock }) {
  const { t, lang } = useI18n()
  const empty = b.not_applicable ? t(`quotes.ref.${b.key}.na`)
    : b.key === 'it_wholesale' && b.variety_generic ? t('quotes.ref.it_wholesale.generic')
    : b.key === 'eu_import' ? t('quotes.ref.eu_import.none', { t: fmtTons(b.min_volume_kg ?? 10000, lang) })
    : t('ui.noData')
  return (
    <div className="min-w-0 rounded-sm border border-line bg-white">
      <div className="border-b border-line-soft px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="font-serif text-[1.02rem] font-semibold">{t(`quotes.ref.${b.key}.title`)}</h4>
          <Badge tone="outline">{t(`quotes.ref.${b.key}.type`)}</Badge>
        </div>
        <p className="mt-0.5 text-[0.84rem] text-muted">{t(`quotes.ref.${b.key}.what`)}</p>
        {b.key === 'us_importer' && b.variety_match === false && b.rows.length > 0 && (
          <p className="mt-1 text-[0.84rem] text-warn">{t('quotes.ref.us_importer.otherVarieties')}</p>
        )}
      </div>
      {b.rows.length === 0 ? (
        <p className="px-4 py-3 text-[0.9rem] text-muted">{empty}</p>
      ) : (
        <div className="relative overflow-x-auto">
          {b.key === 'eu_import' ? <EuRows b={b} /> : b.key === 'us_importer' ? <UsRows b={b} /> : <ItRows b={b} />}
        </div>
      )}
    </div>
  )
}

export function MarketReference({ market }: { market: MR }) {
  const { t } = useI18n()
  return (
    <div className="space-y-3">
      <Note>{t('quotes.ref.intro')}</Note>
      {market.blocks.map((b) => <Block key={b.key} b={b} />)}
    </div>
  )
}
