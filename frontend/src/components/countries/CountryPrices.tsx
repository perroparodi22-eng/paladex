// The country's honey prices on its own page, in the simple view (owner's request, 11 Nov 2026:
// "when I choose the country I also get the prices there, and I can change them"). One short list
// per kind of price, in euro per kilo, newest first; each number is fixed by tapping it
// (components/corrections/QuickFix.tsx). Kinds of price are never mixed; an old figure says so.
import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { FixValue } from '@/components/corrections/QuickFix'
import type { FigureRef } from '@/components/corrections/types'
import { colorLabel } from '@/components/prices/utils'
import { isOldPeriod } from '@/components/simple/bits'
import { SourceChip } from '@/components/simple/SourceChip'
import { useI18n } from '@/i18n'
import { fmtNumber, fmtPeriod } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { perKg, PLAIN_PRICE_TYPE_HINT, PLAIN_PRICE_TYPE_TITLE, plainPriceLabel, plainVariety, plainWhere } from '@/lib/plain'
import { countryName } from './parts'
import type { CountryProfile, PriceRow } from './types'

/** Rows shown per kind of price before "all the prices". */
export const SIMPLE_PRICE_ROWS = 4

/** The stored row behind a price of the country page: what a person fixes by tapping the number.
 * `shown`: the figure on screen when it is not the row's own unit (euro per kilo). */
export function priceFigure(r: PriceRow, label: string, iso3: string, shown?: FigureRef['shown']): FigureRef | null {
  if (!r.row_id || r.is_demo) return null
  return {
    table: 'price_observations', row_id: r.row_id, value: r.price_value, unit: r.unit, currency: r.currency,
    label, country_iso3: iso3, period_label: r.period_label, shown,
  }
}

/** Where a price is observed, in order of interest for an importer selling in Italy and the US. */
const MARKET_PREF = ['ITA', 'EU27', 'EXTRA_EU', 'USA', 'DEU', 'GBR', 'ESP', 'FRA', 'JPN', 'CHE']

/** The rows of one kind of price for the short list: one line per market and product (the newest;
 * the backend lists newest first), FAO's copy of a Eurostat producer price left out, current
 * figures before old ones, the markets that matter most first. */
export function pickCountryPrices(rows: PriceRow[], today: string): PriceRow[] {
  const eurostat = rows.filter((r) => r.source?.key === 'eurostat_honey_prices').map((r) => r.period_label ?? '')
  const seen = new Set<string>()
  const list = rows.filter((r) => {
    if (r.source?.key === 'faostat' && r.price_type === 'producer' && eurostat.some((y) => y >= (r.period_label ?? ''))) return false
    const k = `${r.market_iso3}|${r.variety}|${r.color_grade}|${r.organic}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
  const rank = (r: PriceRow) => {
    const i = MARKET_PREF.indexOf(r.market_iso3 ?? '')
    return i < 0 ? MARKET_PREF.length : i
  }
  const old = (r: PriceRow) => Number(isOldPeriod(r.period_end, r.frequency, today))
  return list.map((r, i) => ({ r, i })).sort((a, b) => old(a.r) - old(b.r) || rank(a.r) - rank(b.r) || a.i - b.i).map((x) => x.r)
}

function Row({ r, p }: { r: PriceRow; p: CountryProfile }) {
  const { t, lang } = useI18n()
  const { country, variety, priceType } = useLabels()
  const iso3 = p.country.iso3
  const eur = r.eur_per_kg ?? (r.currency === 'EUR' ? r.price_per_kg : null)
  const value = eur ?? r.price_per_kg
  const cur = eur !== null ? 'EUR' : r.currency
  const v = plainVariety(r.variety, lang, variety)
  const color = r.color_grade ? colorLabel(r.color_grade, t) : null
  const what = [v, color].filter(Boolean).join(', ')
  const where = plainWhere({ price_type: r.price_type, market_iso3: r.market_iso3, origin_iso3: iso3, terms: r.terms }, lang, country)
  const period = fmtPeriod(r.period_label, lang)
  const old = isOldPeriod(r.period_end, r.frequency, p.today)
  const figure = priceFigure(r,
    `${countryName(p.country, lang)} · ${plainPriceLabel({ price_type: r.price_type, market_iso3: r.market_iso3, origin_iso3: iso3, terms: r.terms }, lang, country)}${what ? ` · ${what}` : ''} · ${period}`,
    iso3, { value, unit: 'kg', currency: cur })
  const technical = [priceType(r.price_type), variety(r.variety), color, r.terms,
    `${fmtNumber(r.price_value, lang, 2)} ${r.currency}/${r.unit}`].filter(Boolean).join(' · ')
  return (
    <li className="border-b border-line-soft py-3 last:border-0" data-country-price={r.row_id ?? ''}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[1.02rem] font-medium leading-snug text-charcoal first-letter:uppercase">{what || t('countries.pricesSimple.allHoney')}</div>
          {where && <div className="text-[0.9rem] leading-snug text-muted">{where}</div>}
        </div>
        <div className={`shrink-0 whitespace-nowrap text-right tabular-nums font-semibold text-[1.35rem] leading-none ${old ? 'text-muted' : 'text-charcoal'}`}>
          <FixValue figure={figure} correction={r.correction}>
            <span>{fmtNumber(value, lang, 2)} <span className="text-[0.85rem]">{perKg(cur)}</span></span>
          </FixValue>
          <div className="mt-1 text-[0.85rem] font-normal text-muted">{period}</div>
        </div>
      </div>
      {old && <p className="mt-0.5 text-[0.9rem] text-warn">{t('simple.old', { p: period })}</p>}
      <SourceChip className="mt-1.5" p={{
        source: r.source, period_label: r.period_label, published_at: r.published_at, collected_at: r.collected_at,
        source_url: r.source_url, data_status: r.data_status, is_demo: r.is_demo, technical, correction: r.correction,
      }} />
    </li>
  )
}

export function CountryPricesSimple({ p, className }: { p: CountryProfile; className?: string }) {
  const { t, lang } = useI18n()
  const d = p.prices
  return (
    <section className={`panel ${className ?? ''}`} data-country-prices>
      <div className="px-4 pb-1 pt-4 sm:px-6">
        <h2 className="font-serif text-[1.35rem] font-semibold leading-tight text-forest-900">{t('countries.pricesSimple.title')}</h2>
        <p className="mt-0.5 text-[0.95rem] text-muted">{t(d.available ? 'countries.pricesSimple.sub' : 'countries.pricesSimple.none')}</p>
      </div>
      {d.available && (
        <div className="grid gap-x-8 gap-y-2 px-4 pb-3 sm:px-6 xl:grid-cols-2">
          {d.groups.map((g) => {
            const picked = pickCountryPrices(g.rows, p.today)
            const shown = picked.slice(0, SIMPLE_PRICE_ROWS)
            // further series on the Prezzi page (a repeated or older line of a market shown here is not "one more")
            const more = (g.count - g.rows.length) + (picked.length - shown.length)
            return (
              <div key={g.price_type} className="min-w-0 pt-2" data-price-group={g.price_type}>
                <h3 className="font-serif text-[1.08rem] font-semibold text-charcoal">{PLAIN_PRICE_TYPE_TITLE[g.price_type]?.[lang] ?? g.price_type}</h3>
                {PLAIN_PRICE_TYPE_HINT[g.price_type]?.[lang] && <p className="text-[0.86rem] leading-snug text-muted">{PLAIN_PRICE_TYPE_HINT[g.price_type][lang]}</p>}
                <ul>{shown.map((r, i) => <Row key={r.row_id ?? i} r={r} p={p} />)}</ul>
                {more > 0 && (
                  <Link to={g.link} className="mt-1 inline-flex items-center gap-1 text-[0.92rem] text-forest-700 underline decoration-gold/50 underline-offset-2 hover:decoration-gold">
                    {t(more === 1 ? 'countries.pricesSimple.more1' : 'countries.pricesSimple.more', { n: more })} <ArrowRight size={14} />
                  </Link>
                )}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
