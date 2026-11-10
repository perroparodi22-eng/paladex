// Profile sections: prices (by price type, never mixed), news, regulations, curated context, and
// the explicit list of what is NOT available.
import { ArrowRight, BookOpen, CircleSlash, ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AiBadge, Badge, DemoBadge, Note, Panel, StatusBadge } from '@/components/ui'
import { colorLabel } from '@/components/prices/utils'
import { DataMissing, useProviderText } from '@/components/trade/bits'
import { pickLang, useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtPeriod } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import type { Lang } from '@/lib/types'
import { countryName } from './parts'
import type { CountryProfile, MissingItem, PriceRow } from './types'
import { isMappedUrl, pageUrl } from '@/lib/links'

// ---------------------------------------------------------------------------
// Prices
// ---------------------------------------------------------------------------

export function ProfilePrices({ p }: { p: CountryProfile }) {
  const { t, lang } = useI18n()
  const { priceType } = useLabels()
  const d = p.prices
  return (
    <Panel
      title={t('countries.prices.title')}
      eyebrow={t('countries.prices.eyebrow', { c: countryName(p.country, lang) })}
      actions={d.groups.some((g) => g.rows.some((r) => r.is_demo)) ? <DemoBadge /> : undefined}
    >
      {!d.available ? (
        <DataMissing providers={d.providers} fallback={t('countries.prices.fallback')} what={t('countries.missing.prices')} />
      ) : (
        <div className="flex flex-col gap-6">
          <Note>{t('countries.prices.never')}</Note>
          {d.groups.map((g) => (
            <section key={g.price_type}>
              <div className="flex flex-wrap items-baseline justify-between gap-2 mb-1.5">
                <h3 className="font-serif text-[1.05rem] font-semibold">{priceType(g.price_type)}</h3>
                <Link to={g.link} className="inline-flex items-center gap-1 text-sm text-forest-700 hover:text-forest-900">
                  {t('countries.prices.open')} <ArrowRight size={14} />
                </Link>
              </div>
              <div className="overflow-x-auto">
                <table className="table-clean">
                  <thead>
                    <tr>
                      <th>{t('countries.prices.col.variety')}</th>
                      <th>{t('countries.prices.col.market')}</th>
                      <th className="!text-right">{t('countries.prices.col.price')}</th>
                      <th className="!text-right">{t('countries.prices.col.usd')}</th>
                      <th>{t('countries.prices.col.period')}</th>
                      <th>{t('countries.prices.col.source')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.rows.map((r, i) => <PriceLine key={i} r={r} />)}
                  </tbody>
                </table>
              </div>
              {g.count > g.rows.length && <div className="mt-1 text-[0.82rem] text-muted">{g.count - g.rows.length === 1 ? t('countries.prices.moreOne') : t('countries.prices.more', { n: g.count - g.rows.length })}</div>}
            </section>
          ))}
        </div>
      )}
    </Panel>
  )
}

function PriceLine({ r }: { r: PriceRow }) {
  const { t, lang } = useI18n()
  const { variety, country } = useLabels()
  const range = r.price_low !== null && r.price_high !== null && r.price_low !== r.price_high
    ? `${fmtNumber(r.price_low, lang, 2)}–${fmtNumber(r.price_high, lang, 2)}` : null
  return (
    <tr>
      <td>
        {variety(r.variety)}
        {r.organic && <span className="ml-1.5"><Badge tone="forest">{t('countries.prices.organic')}</Badge></span>}
        {r.color_grade && <div className="text-[0.78rem] text-muted">{colorLabel(r.color_grade, t)}</div>}
      </td>
      <td className="text-[0.9rem]">
        {r.market_iso3 ? country(r.market_iso3) : '—'}
        {(r.market_location || r.terms) && <div className="text-[0.78rem] text-muted">{[r.market_location, r.terms].filter(Boolean).join(' · ')}</div>}
      </td>
      <td className="num text-right whitespace-nowrap">
        {fmtNumber(r.price_value, lang, 2)} <span className="text-muted text-[0.8em]">{r.currency}/{r.unit}</span>
        {range && <div className="text-[0.75rem] text-muted">{range}</div>}
      </td>
      <td className="num text-right">{r.usd_per_kg !== null ? fmtNumber(r.usd_per_kg, lang, 2) : '—'}</td>
      <td className="num whitespace-nowrap">{fmtPeriod(r.period_label, lang)}</td>
      <td className="text-[0.85rem] text-muted">
        <div className="flex flex-wrap items-center gap-1.5">
          {r.is_demo ? <DemoBadge /> : r.data_status && r.data_status !== 'published' && <StatusBadge status={r.data_status} />}
          <span>{r.source?.publisher || r.source?.name}</span>
          {r.source_url && <a className="link inline-flex" href={pageUrl(r.source_url) ?? undefined} target="_blank" rel="noreferrer" title={isMappedUrl(r.source_url) ? t('prov.exactAddress', { url: r.source_url }) : t('prov.original')}><ExternalLink size={12} /></a>}
        </div>
        {r.published_at && <div className="text-[0.75rem]">{t('prov.published')} {fmtDate(r.published_at, lang)}</div>}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// News & regulations
// ---------------------------------------------------------------------------

/** One news line: headline (AI translation when one exists, labelled), outlet, date, language. */
function NewsLine({ n, strong = false }: { n: CountryProfile['news']['items'][number]; strong?: boolean }) {
  const { t, lang } = useI18n()
  const sameLang = Boolean(n.language) && n.language!.slice(0, 2) === lang
  const translated = sameLang ? null : (lang === 'it' ? n.title_it : n.title_en)
  const isAi = Boolean(translated) && translated!.trim() !== n.title.trim()
  const topics = (n.topic_labels?.[lang] ?? []).slice(0, 2)
  return (
    <li className="py-2.5" data-country-news={n.id}>
      <a href={pageUrl(n.url) ?? undefined} target="_blank" rel="noreferrer"
        title={isAi ? n.title : undefined} lang={isAi ? lang : n.language ?? undefined}
        className={strong
          ? 'font-serif text-[1.08rem] font-semibold leading-snug text-charcoal hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2'
          : 'text-[0.97rem] leading-snug text-charcoal hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2'}>
        {translated || n.title}
      </a>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8rem] text-muted">
        {n.is_demo && <DemoBadge />}
        {isAi && <AiBadge />}
        <span className="text-charcoal-soft">{n.publisher || n.source?.publisher || n.source?.name}</span>
        {n.published_at && <span>· {fmtDate(n.published_at, lang)}</span>}
        {n.language && !sameLang && <span className="uppercase">· {n.language.slice(0, 2)}</span>}
        {topics.length > 0 && <span className="text-forest-800">· {topics.join(', ')}</span>}
        {n.duplicate_count > 0 && <span>· {n.duplicate_count === 1 ? t('countries.news.duplicatesOne') : t('countries.news.duplicates', { n: n.duplicate_count })}</span>}
      </div>
    </li>
  )
}

/** News about the country. First the one or two trade stories that matter most (exports, imports,
 *  prices, duties: chosen by the backend, `news.highlights`), then the latest articles. `compact`
 *  (simple view) shows the highlights only, or the two latest when there is no trade story. */
/** Days after which the newest article is no longer "recent news" and the panel says its date. */
const OLD_NEWS_DAYS = 120

/** "luglio 2022" when the newest article is older than OLD_NEWS_DAYS, else null. */
export function oldNewsMonth(latestAt: string | null | undefined, today: string | null | undefined, lang: Lang): string | null {
  if (!latestAt) return null
  const now = today ? new Date(`${today.slice(0, 10)}T12:00:00Z`) : new Date()
  const then = new Date(`${latestAt.slice(0, 10)}T12:00:00Z`)
  if (Number.isNaN(then.getTime()) || (now.getTime() - then.getTime()) / 86_400_000 <= OLD_NEWS_DAYS) return null
  return fmtDate(latestAt.slice(0, 10), lang, { month: 'long', year: 'numeric' })
}

export function ProfileNews({ p, compact = false, className }: { p: CountryProfile; compact?: boolean; className?: string }) {
  const { t, lang } = useI18n()
  const d = p.news
  const oldMonth = oldNewsMonth(d.latest_at, p.today, lang)
  const top = d.highlights ?? []
  const topIds = new Set(top.map((n) => n.id))
  const rest = d.items.filter((n) => !topIds.has(n.id))
  const latest = compact ? (top.length ? [] : rest.slice(0, 2)) : rest
  if (compact && !d.available) return null
  return (
    <Panel
      title={t('countries.news.title')}
      eyebrow={d.count_30d ? t('countries.news.count', { n: d.count_30d }) : t('countries.news.eyebrow')}
      className={className ?? 'min-w-0'}
      actions={d.items.some((i) => i.is_demo) ? <DemoBadge /> : undefined}
      footer={<Link to={d.link} className="link">{t('countries.news.all')} →</Link>}
    >
      {!d.available ? (
        <DataMissing compact providers={d.providers} fallback={t('countries.news.fallback')} what={t('countries.missing.news')} />
      ) : (
        <div className="-my-2">
          {/* never old news shown as current: when the newest article is months or years old, say so first */}
          {oldMonth && (
            <div className="pb-1 pt-2" data-country-news-old><Note>{t('countries.news.old', { m: oldMonth })}</Note></div>
          )}
          {top.length > 0 && (
            <div data-country-news-top>
              <div className="eyebrow pt-2">{t('countries.news.top')}</div>
              <ul className="flex flex-col divide-y divide-line-soft">
                {top.map((n) => <NewsLine key={n.id} n={n} strong />)}
              </ul>
            </div>
          )}
          {latest.length > 0 && (
            <div className={top.length > 0 ? 'mt-1 border-t border-line pt-1' : undefined}>
              {top.length > 0 && <div className="eyebrow pt-2">{t('countries.news.latest')}</div>}
              <ul className="flex flex-col divide-y divide-line-soft">
                {latest.map((n) => <NewsLine key={n.id} n={n} />)}
              </ul>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}

export function ProfileRegulations({ p }: { p: CountryProfile }) {
  const { t, lang } = useI18n()
  const d = p.regulations
  return (
    <Panel title={t('countries.reg.title')} eyebrow={t('countries.reg.eyebrow')} className="min-w-0"
      actions={d.items.some((i) => i.is_demo) ? <DemoBadge /> : undefined}>
      {!d.available ? (
        <DataMissing compact providers={d.providers} fallback={t('countries.reg.fallback')} what={t('countries.missing.regulations')} />
      ) : (
        <ul className="flex flex-col divide-y divide-line-soft -my-2">
          {d.items.map((r) => {
            const summary = pickLang(r as unknown as Record<string, unknown>, 'summary', lang)
            return (
              <li key={r.id} className="py-2.5">
                <a href={pageUrl(r.url) ?? undefined} target="_blank" rel="noreferrer" className="text-[0.95rem] leading-snug text-charcoal hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2">
                  {r.title}
                </a>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8rem] text-muted">
                  {r.is_demo && <DemoBadge />}
                  <Badge tone="outline">{r.jurisdiction}</Badge>
                  <span>{r.doc_type}</span>
                  <span className="num">· {r.reference}</span>
                  {r.published_at && <span>· {fmtDate(r.published_at, lang)}</span>}
                  {r.effective_date && <span>· {t('countries.reg.effective', { d: fmtDate(r.effective_date, lang) })}</span>}
                  <span>· {t(`countries.reg.match.${r.match}`)}</span>
                </div>
                {summary && (
                  <p className="mt-1 text-[0.85rem] text-charcoal-soft leading-snug">
                    {r.summary_is_ai && <span className="mr-1.5"><AiBadge /></span>}{summary}
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Context (curated background — never presented as collected data)
// ---------------------------------------------------------------------------

const MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTHS_IT = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic']
const SEASON_WORDS_IT: [RegExp, string][] = [
  [/\byear-round\b/gi, 'tutto l’anno'], [/\bpeaks?\b/gi, 'picco'], [/\bregion-dependent\b/gi, 'secondo la regione'],
]

/** The curated harvest season is written in English ("Apr–Sep", "year-round, peaks Sep–Mar"):
 * in Italian, month names and the few words used are translated ("apr–set", "tutto l’anno, picco set–mar"). */
export function harvestSeason(text: string, lang: 'it' | 'en'): string {
  if (lang === 'en') return text
  let out = text.replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/g, (m) => MONTHS_IT[MONTHS_EN.indexOf(m)])
  for (const [re, it] of SEASON_WORDS_IT) out = out.replace(re, it)
  return out
}

export function ProfileContext({ p }: { p: CountryProfile }) {
  const { t, lang } = useI18n()
  const { variety } = useLabels()
  const c = p.context
  const notes = lang === 'it' ? c.notes_it ?? c.notes_en : c.notes_en ?? c.notes_it
  const harvestText = lang === 'it' ? c.harvest_it : c.harvest_en
  const harvest = harvestText ?? (c.harvest ? harvestSeason(c.harvest, lang) : null)
  return (
    <Panel title={t('countries.ctx.title')} className="min-w-0">
      <div className="mb-3 flex items-start gap-2 rounded-sm border border-dashed border-line px-2.5 py-1.5 text-[0.8rem] text-muted"
        title={lang === 'it' ? c.label_it : c.label_en}>
        <BookOpen size={14} className="mt-[2px] shrink-0" />
        <span>{t('countries.ctx.badge')}</span>
      </div>
      {!c.available ? (
        <p className="text-muted text-[0.92rem]">{t('countries.ctx.none')}</p>
      ) : (
        <div className="flex flex-col gap-3 text-[0.94rem]">
          {notes && <p className="text-charcoal-soft leading-relaxed">{notes}</p>}
          {c.varieties.length > 0 && (
            <div>
              <div className="eyebrow mb-1">{t('countries.ctx.varieties')}</div>
              <div className="flex flex-wrap gap-1.5">
                {c.varieties.map((v) => <span key={v} className="rounded-sm border border-line bg-ivory/60 px-2 py-0.5 text-[0.85rem]">{variety(v)}</span>)}
              </div>
            </div>
          )}
          {harvest && (
            <div>
              <div className="eyebrow mb-0.5">{t('countries.ctx.harvest')}</div>
              <div className="text-charcoal-soft">{harvest}</div>
            </div>
          )}
          {c.refs.length > 0 && (
            <div>
              <div className="eyebrow mb-0.5">{t('countries.ctx.refs')}</div>
              {c.refs.map((u) => <a key={u} href={pageUrl(u) ?? undefined} target="_blank" rel="noreferrer" className="link block truncate text-[0.85rem]">{u}</a>)}
            </div>
          )}
          <p className="text-[0.78rem] text-muted border-t border-line-soft pt-2">{lang === 'it' ? c.label_it : c.label_en}</p>
        </div>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// What is missing
// ---------------------------------------------------------------------------

const FALLBACK_KEY: Record<MissingItem['key'], string> = {
  production: 'countries.prod.fallback', exports: 'countries.trade.fallback', imports: 'countries.trade.fallback',
  prices: 'countries.prices.fallback', news: 'countries.news.fallback', regulations: 'countries.reg.fallback',
  context: 'countries.missing.ctxFrom',
}

export function ProfileMissing({ p }: { p: CountryProfile }) {
  const { t } = useI18n()
  const providerText = useProviderText()
  if (p.missing.length === 0) return null
  return (
    <section className="panel mb-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 pt-3">
        <h2 className="panel-title">{t('countries.missing.title')}</h2>
        <span className="text-[0.82rem] text-muted">{t('countries.missing.never')}</span>
      </div>
      <ul className="grid gap-x-8 gap-y-2.5 px-5 pt-2.5 pb-4 md:grid-cols-2 2xl:grid-cols-3">
        {p.missing.map((m) => (
          <li key={m.key} className="flex gap-2.5 min-w-0">
            <CircleSlash size={15} className="mt-[3px] shrink-0 text-muted" />
            <div className="min-w-0">
              <div className="text-[0.95rem] text-charcoal">
                {t(`countries.missing.${m.key}`)}
                {m.partial_alternative && <span className="ml-1.5 text-[0.8rem] text-gold-dark">({t('countries.missing.partial')})</span>}
              </div>
              <div className="text-[0.8rem] text-muted">
                {m.key === 'context' ? t(FALLBACK_KEY.context)
                  : t('countries.missing.from', { s: providerText(m.providers, t(FALLBACK_KEY[m.key]), 3) })}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
