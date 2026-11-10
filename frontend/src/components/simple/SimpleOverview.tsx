// Panoramica, simple view: four cards in plain words, answer first — prices of the main origins,
// the year so far in trade, the three most important changes, three headlines. Same data and the
// same provenance as the full view (GET /api/overview): every figure carries its source chip.
// The data status appears only when something is wrong, as one line linking to Fonti.
import clsx from 'clsx'
import { ArrowRight, ExternalLink, Loader2, PenLine, WifiOff } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AiBadge, DemoBadge, TranslatedBadge } from '@/components/ui'
import type {
  BriefingBlock, BriefingBullet, NewsBlock, OverviewData, PriceTile, PricesBlock, QualityBlock, StatusBlock, TradeBlock,
} from '@/components/overview/types'
import { colorLabel } from '@/components/prices/utils'
import { fmtMonthSpan, prevSpan, type YtdFigure, type YtdLeaders } from '@/components/trade/ytd'
import { useI18n } from '@/i18n'
import { fmtDate, fmtNumber, fmtPct, fmtPeriod } from '@/lib/format'
import { pageUrl } from '@/lib/links'
import { useLabels } from '@/lib/meta'
import { inPeriod, ofPct, perKg, plainPriceLabel, plainText, plainVariety, shortSource, vsPeriod } from '@/lib/plain'
import type { Lang } from '@/lib/types'
import { useView } from '@/lib/view'
import { isMirror } from '@/lib/mirror'
import { FixValue } from '@/components/corrections/QuickFix'
import type { FigureRef } from '@/components/corrections/types'
import { WriteBox } from '@/components/corrections/WriteBox'
import { SourceChip } from './SourceChip'
import { isOldPeriod, monthName, Trend, useGapNote } from './bits'

export function SimpleCard({ title, sub, children, link, linkLabel, className, extra }: {
  title: ReactNode; sub?: ReactNode; children: ReactNode; link?: string; linkLabel?: string; className?: string; extra?: ReactNode
}) {
  return (
    <section className={clsx('panel flex min-w-0 flex-col', className)}>
      <div className="px-4 pb-2 pt-4 sm:px-6 sm:pt-5">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <h2 className="font-serif text-[1.4rem] font-semibold leading-tight text-forest-900 sm:text-[1.5rem]">{title}</h2>
          {extra}
        </div>
        {sub && <p className="mt-1 text-[0.98rem] leading-snug text-muted">{sub}</p>}
      </div>
      <div className="flex-1 px-4 pb-3 sm:px-6">{children}</div>
      {link && (
        <div className="border-t border-line-soft px-4 py-3 sm:px-6">
          <Link to={link} className="inline-flex items-center gap-1.5 text-[1rem] font-medium text-forest-700 hover:text-forest-900">
            {linkLabel} <ArrowRight size={16} />
          </Link>
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
// Data status: one line, only when something is wrong
// ---------------------------------------------------------------------------------------------
export function StatusLine({ status, quality }: { status: StatusBlock; quality: QualityBlock }) {
  const { t } = useI18n()
  const c = status.counts
  const late = c.aging + c.stale
  const critical = quality.by_severity.critical ?? 0
  const parts = [
    c.failed > 0 && t(c.failed === 1 ? 'simple.status.failed1' : 'simple.status.failed', { n: c.failed }),
    late > 0 && t(late === 1 ? 'simple.status.late1' : 'simple.status.late', { n: late }),
    critical > 0 && t(critical === 1 ? 'simple.status.critical1' : 'simple.status.critical', { n: critical }),
  ].filter(Boolean) as string[]
  const wrong = parts.length > 0 || status.offline
  if (!wrong && !status.collection_running) return null
  return (
    <div className="mb-5 space-y-1.5 text-[0.95rem]" data-status-line>
      {status.collection_running && (
        <p className="inline-flex items-center gap-2 text-forest-700"><Loader2 size={15} className="animate-spin" /> {t('overview.status.running')}</p>
      )}
      {status.offline && (
        <p className="flex items-start gap-2 text-warn"><WifiOff size={16} className="mt-0.5 shrink-0" /> {t('overview.status.offline')}</p>
      )}
      {parts.length > 0 && (
        <Link to={status.link} className="group flex items-start gap-2 text-charcoal-soft">
          <span className="mt-[0.45rem] inline-block h-2 w-2 shrink-0 rounded-full bg-warn" aria-hidden />
          <span>
            {t('simple.status.wrong', { list: parts.join(', ') })}{' '}
            <span className="whitespace-nowrap text-forest-700 underline decoration-gold/50 underline-offset-2 group-hover:decoration-gold">{t('simple.status.toSources')} →</span>
          </span>
        </Link>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
// 1. Prices of the main origins
// ---------------------------------------------------------------------------------------------
function eurOf(tile: PriceTile): number | null {
  return tile.eur_per_kg ?? (tile.currency === 'EUR' ? tile.price_per_kg : null)
}

function PriceRow({ tile, old }: { tile: PriceTile; old: boolean }) {
  const { t, lang } = useI18n()
  const { country, variety, priceType } = useLabels()
  const origin = tile.origin_iso3 ? country(tile.origin_iso3) : tile.origin_label || country(tile.market_iso3)
  const eur = eurOf(tile)
  const value = eur ?? tile.price_per_kg
  const cur = eur !== null ? 'EUR' : tile.currency
  const v = plainVariety(tile.variety, lang, variety)
  const color = tile.color_grade ? colorLabel(tile.color_grade, t) : null
  const what = [v && lang === 'it' ? v.toLowerCase() : v, color && lang === 'it' ? color.toLowerCase() : color].filter(Boolean).join(', ')
  const changeIn = tile.currency !== cur ? tile.currency : null
  const gapNote = useGapNote()
  const gap = tile.mom_pct == null ? gapNote(tile.mom_missing, tile.yoy_pct == null ? tile.yoy_missing : null) : null
  const technical = [priceType(tile.price_type), variety(tile.variety), color, tile.terms,
    `${fmtNumber(tile.price_value, lang, 2)} ${tile.currency}/${tile.unit}`].filter(Boolean).join(' · ')
  // the stored row behind this price: tapping the number opens "type the right one" (in the unit shown)
  const rowId = tile.row_id ?? tile.row_ids?.[0]
  const figure: FigureRef | null = rowId ? {
    table: 'price_observations', row_id: rowId, row_ids: tile.row_ids, value: tile.price_value, unit: tile.unit, currency: tile.currency,
    label: `${origin} · ${plainPriceLabel(tile, lang, country)}${what ? ` · ${what}` : ''} · ${fmtPeriod(tile.period_label, lang)}`,
    country_iso3: tile.origin_iso3, period_label: tile.period_label,
    shown: value !== null && value !== undefined ? { value, unit: 'kg', currency: cur } : null,
  } : null
  return (
    <li className="border-b border-line-soft py-3.5 last:border-0" data-price-row={tile.origin_iso3 ?? ''}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[1.15rem] font-semibold leading-snug text-charcoal">{origin}</div>
          <div className="text-[0.9rem] leading-snug text-muted">
            {plainPriceLabel(tile, lang, country)}{what && <> · {what}</>}
          </div>
        </div>
        <div className={clsx('shrink-0 whitespace-nowrap text-right tabular-nums font-semibold text-[1.5rem] leading-none', old ? 'text-muted' : 'text-charcoal')}>
          <FixValue figure={figure} correction={tile.correction}>
            <span>{fmtNumber(value, lang, 2)} <span className="text-[0.85rem]">{perKg(cur)}</span></span>
          </FixValue>
        </div>
      </div>
      {!old && (
        <div className="mt-1 text-[0.95rem]">
          <Trend month={tile.mom_pct} year={tile.yoy_pct} currency={changeIn}
            earlier={{ pct: tile.earlier_pct, period_label: tile.earlier_period_label }} />
          {gap && <span className="text-[0.88rem] text-muted" data-gap> · {gap}</span>}
        </div>
      )}
      {old && (
        <p className="mt-1 text-[0.92rem] text-warn">{t('simple.old', { p: fmtPeriod(tile.period_label, lang) })}</p>
      )}
      <SourceChip className="mt-2" p={{
        source: tile.source, period_label: tile.period_label, published_at: tile.published_at, collected_at: tile.collected_at,
        source_url: tile.source_url, data_status: tile.data_status, is_demo: tile.is_demo, technical,
        note: [
          eur === null && tile.currency !== 'EUR' ? t('simple.prices.noFx') : null,
          changeIn ? t('simple.prices.changeBasis', { cur: changeIn }) : null,
        ].filter(Boolean).join(' ') || null,
        correction: tile.correction,
      }} figure={figure} />
    </li>
  )
}

/** One series per origin: the backend's choice for that origin (its first tile). */
export function tilesByOrigin(items: PriceTile[]): PriceTile[] {
  const seen = new Set<string>()
  return items.filter((x) => {
    const k = x.origin_iso3 ?? x.origin_label ?? x.id
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

function PricesCard({ block, today }: { block: PricesBlock; today: string }) {
  const { t } = useI18n()
  const tiles = tilesByOrigin(block.items)
  const isOld = (x: PriceTile) => x.freshness.status === 'stale' || isOldPeriod(x.period_end, x.frequency, today)
  const current = tiles.filter((x) => !isOld(x))
  const old = tiles.filter(isOld)
  return (
    <SimpleCard title={t('simple.prices.title')} sub={t('simple.prices.sub')} link={block.link} linkLabel={t('simple.prices.all')}
      extra={tiles.some((x) => x.is_demo) ? <DemoBadge /> : undefined}>
      {tiles.length === 0 ? (
        <p className="py-2 text-[1rem] text-muted">{t('simple.prices.none')}</p>
      ) : (
        <>
          <ul>{current.map((x) => <PriceRow key={x.id} tile={x} old={false} />)}</ul>
          {old.length > 0 && (
            <>
              <h3 className="mt-3 font-sans text-[0.95rem] font-semibold text-charcoal-soft">{t('simple.prices.oldTitle')}</h3>
              <ul>{old.map((x) => <PriceRow key={x.id} tile={x} old />)}</ul>
            </>
          )}
          {block.mixed_price_types && <p className="mt-2 text-[0.88rem] text-warn">{t('simple.prices.mixed')}</p>}
        </>
      )}
    </SimpleCard>
  )
}

// ---------------------------------------------------------------------------------------------
// 2. The year so far (monthly customs data)
// ---------------------------------------------------------------------------------------------
export function tonnes(kg: number | null | undefined, lang: Lang): string {
  if (kg === null || kg === undefined) return '—'
  const t = kg / 1000
  return `${fmtNumber(t, lang, t < 10 ? 1 : 0)} ${lang === 'it' ? 'tonnellate' : 'tonnes'}`
}

function usdMillions(v: number | null | undefined, lang: Lang): string {
  if (v === null || v === undefined) return '—'
  return lang === 'it' ? `${fmtNumber(v / 1e6, lang, 1)} milioni di dollari` : `$${fmtNumber(v / 1e6, lang, 1)} million`
}

function YtdRow({ r, flow }: { r: YtdFigure; flow: 'import' | 'export' }) {
  const { t, lang } = useI18n()
  const byValue = r.net_weight_kg === null && r.usd_value !== null
  const amount = byValue ? usdMillions(r.usd_value, lang) : tonnes(r.net_weight_kg, lang)
  const to = monthName(r.month_to, lang)
  // Italian "da gennaio ad agosto" (before a vowel), "da gennaio a settembre"
  const span = t('simple.ytd.span', { from: monthName(r.month_from, lang), to, a: /^[aeiou]/i.test(to) ? 'ad' : 'a' })
  const pct = byValue ? r.change_value_pct : r.change_volume_pct
  return (
    <li className="border-b border-line-soft py-3 last:border-0" data-ytd-row={r.iso3}>
      <p className="text-[1.05rem] leading-snug text-charcoal">
        <Link to={r.link ?? `/paesi/${r.iso3}`} className="font-semibold hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2">{r.name ?? r.iso3}</Link>
        {': '}
        {t(`simple.ytd.${flow === 'export' ? 'exported' : 'imported'}${byValue ? 'Value' : ''}`, { amount, span: r.month_from === r.month_to ? t('simple.ytd.inMonth', { m: monthName(r.month_to, lang) }) : span })}
        {r.comparable && pct !== null ? (
          <> <Trend month={null} year={null} pct={pct} label={t('simple.ytd.vsSame', { y: r.prev_year })} /></>
        ) : (
          <span className="text-muted"> ({t('simple.ytd.noCompare', { y: r.prev_year })})</span>
        )}
      </p>
      <SourceChip className="mt-1.5" p={{
        source: r.source, period_text: `${fmtMonthSpan(r.month_from, r.month_to, lang)} ${r.year}`, published_at: r.published_at,
        collected_at: r.collected_at, source_url: r.source_url, data_status: r.data_status, is_demo: r.is_demo,
        technical: [
          t(flow === 'export' ? 'simple.ytd.techExp' : 'simple.ytd.techImp'),
          r.net_weight_kg !== null ? `${fmtNumber(r.net_weight_kg / 1000, lang, 0)} t` : null,
          r.usd_value !== null ? `${fmtNumber(r.usd_value, lang, 0)} USD` : null,
          r.comparable ? `${t('simple.ytd.vs')} ${prevSpan(r, lang)}` : null,
        ].filter(Boolean).join(' · '),
        correction: r.correction,
      }} />
    </li>
  )
}

function YtdSide({ side, flow, title }: { side: YtdLeaders | undefined; flow: 'import' | 'export'; title: string }) {
  const { t } = useI18n()
  return (
    <div className="min-w-0">
      <h3 className="mt-2 font-sans text-[1.05rem] font-semibold text-forest-800">{title}</h3>
      {side && side.rows.length ? (
        <ul>{side.rows.slice(0, 3).map((r) => <YtdRow key={r.iso3} r={r} flow={flow} />)}</ul>
      ) : (
        <p className="py-2 text-[0.98rem] text-muted">{t('simple.ytd.noneSide')}</p>
      )}
    </div>
  )
}

function YtdCard({ block }: { block: TradeBlock }) {
  const { t } = useI18n()
  const ytd = block.ytd ?? null
  const year = ytd?.exporters?.year ?? ytd?.importers?.year
  return (
    <SimpleCard
      title={year ? t('simple.ytd.title', { y: year }) : t('simple.ytd.titleNoYear')}
      sub={year ? t('simple.ytd.sub', { py: year - 1 }) : undefined}
      link={block.link} linkLabel={t('simple.ytd.all')}
      extra={ytd?.exporters?.is_demo || ytd?.importers?.is_demo ? <DemoBadge /> : undefined}
    >
      {!ytd || year === undefined ? (
        <p className="py-2 text-[1rem] text-muted">{t('simple.ytd.none')}</p>
      ) : (
        <>
          <YtdSide side={ytd.exporters} flow="export" title={t('simple.ytd.exporters')} />
          <YtdSide side={ytd.importers} flow="import" title={t('simple.ytd.importers')} />
          <p className="mt-2 text-[0.88rem] leading-snug text-muted">{t('simple.ytd.note')}</p>
        </>
      )}
    </SimpleCard>
  )
}

// ---------------------------------------------------------------------------------------------
// 3. The three most important changes, in plain words
// ---------------------------------------------------------------------------------------------
type Bullet = BriefingBullet & {
  origin_iso3?: string | null; market_iso3?: string | null; variety?: string | null; terms?: string | null
  price_type?: string | null; value_per_kg?: number | null; currency?: string | null
  flow?: 'import' | 'export' | null; reporter_iso3?: string | null; partner_iso3?: string | null
  net_weight_kg?: number | null; prev_period_label?: string | null
}

/** The first price change, the first trade change, the first new report, then the next of each:
 * a mix of what moved, at most `n`. News headlines have their own card. */
export function pickChanges(bullets: BriefingBullet[], n = 3): BriefingBullet[] {
  const by = (k: string) => bullets.filter((b) => b.kind === k)
  const queues = [by('price'), by('trade'), by('report'), bullets.filter((b) => !['price', 'trade', 'report', 'news'].includes(b.kind))]
  const out: BriefingBullet[] = []
  for (let i = 0; out.length < n && queues.some((q) => q.length > i); i++) {
    for (const q of queues) if (q[i] && out.length < n) out.push(q[i])
  }
  return out
}

export function usePlainBullet() {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  return (b: Bullet): string => {
    const pct = b.change_pct
    if (b.kind === 'price' && b.origin_iso3 && b.price_type && b.value_per_kg != null && b.currency && pct != null && b.period_label) {
      const v = plainVariety(b.variety, lang, variety)
      const pctText = fmtPct(Math.abs(pct), lang, 1, false)
      return t(pct >= 0 ? 'simple.change.priceUp' : 'simple.change.priceDown', {
        origin: country(b.origin_iso3),
        variety: v ? (lang === 'it' ? v.toLowerCase() : v) : '',
        what: plainPriceLabel({ price_type: b.price_type, market_iso3: b.market_iso3, origin_iso3: b.origin_iso3, terms: b.terms }, lang, country),
        of: ofPct(pctText, lang), pct: pctText,
        value: `${fmtNumber(b.value_per_kg, lang, 2)} ${perKg(b.currency)}`,
        period: fmtPeriod(b.period_label, lang),
      }).replace(', :', ':')
    }
    if (b.kind === 'trade' && b.reporter_iso3 && b.flow && b.net_weight_kg != null && pct != null && b.period_label) {
      const world = !b.partner_iso3 || b.partner_iso3 === 'WLD'
      const key = `simple.change.${b.flow === 'import' ? 'imp' : 'exp'}${world ? 'World' : ''}`
      return t(key, {
        rep: country(b.reporter_iso3), par: b.partner_iso3 ? country(b.partner_iso3) : '',
        when: inPeriod(b.period_label, lang), amount: tonnes(b.net_weight_kg, lang),
        pct: fmtPct(pct, lang), vs: b.prev_period_label ? vsPeriod(b.prev_period_label, lang) : '',
      }).replace(' ()', '')
    }
    return plainText(b.text, lang)
  }
}

function ChangesCard({ b }: { b: BriefingBlock }) {
  const { t } = useI18n()
  const { setView } = useView()
  const plain = usePlainBullet()
  const items = pickChanges(b.bullets) as Bullet[]
  return (
    <SimpleCard title={t('simple.changes.title')} sub={b.is_ai ? t('simple.changes.subAi') : t('simple.changes.sub')}
      extra={b.is_ai ? <AiBadge /> : undefined}>
      {items.length === 0 ? (
        <p className="py-2 text-[1rem] text-muted">{b.empty_message ?? t('simple.changes.none')}</p>
      ) : (
        <ol className="list-none">
          {items.map((x, i) => (
            <li key={i} className="grid grid-cols-[1.8rem_minmax(0,1fr)] gap-x-2 border-b border-line-soft py-3.5 last:border-0" data-change={x.kind}>
              <span className="tabular-nums pt-[0.05rem] text-[1.2rem] font-semibold text-gold-dark">{i + 1}</span>
              <div className="min-w-0">
                <p className="text-[1.05rem] leading-snug text-charcoal">{plain(x)}</p>
                <SourceChip className="mt-1.5" p={{
                  source: x.source ?? (x.publisher ? { key: '', name: x.publisher, publisher: x.publisher, reliability: '', homepage: null } : null),
                  period_label: x.period_label, published_at: x.date, source_url: x.url, data_status: x.data_status,
                  is_demo: x.is_demo, technical: x.text,
                }} />
              </div>
            </li>
          ))}
        </ol>
      )}
      {b.bullets.length > items.length && (
        <p className="pt-2 text-[0.92rem] text-muted">
          {t('simple.changes.more', { n: b.bullets.length - items.length })}{' '}
          <button type="button" className="link" onClick={() => setView('full')}>{t('simple.toFull')}</button>
        </p>
      )}
    </SimpleCard>
  )
}

// ---------------------------------------------------------------------------------------------
// 4. Three headlines
// ---------------------------------------------------------------------------------------------
function NewsCard({ block }: { block: NewsBlock }) {
  const { t, lang } = useI18n()
  const items = block.items.slice(0, 3)
  return (
    <SimpleCard title={t('simple.news.title')} sub={t('simple.news.sub', { d: block.window_days })} link={block.link} linkLabel={t('simple.news.all')}>
      {items.length === 0 ? (
        <p className="py-2 text-[1rem] text-muted">{t('simple.news.none')}</p>
      ) : (
        <ul>
          {items.map((n) => (
            <li key={n.id} className="border-b border-line-soft py-3.5 last:border-0" data-news={n.id}>
              <a href={pageUrl(n.url) ?? undefined} target="_blank" rel="noreferrer"
                className="font-serif text-[1.15rem] font-semibold leading-snug text-charcoal hover:text-forest-800 hover:underline decoration-gold/60 underline-offset-2">
                {n.title}
              </a>
              {n.summary && <p className="mt-1 line-clamp-2 text-[0.98rem] leading-snug text-charcoal-soft">{n.summary}</p>}
              <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.9rem] text-muted">
                {n.is_demo && <DemoBadge />}
                <span className="font-medium text-charcoal-soft" title={n.publisher || n.source?.publisher || undefined}>
                  {n.publisher ? shortSource({ key: '', name: n.publisher, publisher: n.publisher }, lang) : shortSource(n.source, lang)}
                </span>
                <span aria-hidden>·</span>
                <span>{fmtDate(n.published_at ?? n.collected_at, lang, { day: 'numeric', month: 'long', year: 'numeric' })}</span>
                {n.summary_is_ai ? <AiBadge /> : n.title_is_ai && <TranslatedBadge model={n.ai_model} />}
                <a href={pageUrl(n.url) ?? undefined} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1">
                  {t('simple.news.read')} <ExternalLink size={13} />
                </a>
              </div>
            </li>
          ))}
        </ul>
      )}
    </SimpleCard>
  )
}

export function SimpleOverview({ d, firstLaunch }: { d: OverviewData; firstLaunch?: ReactNode }) {
  const { t } = useI18n()
  const { setView } = useView()
  return (
    <div data-view="simple">
      <StatusLine status={d.status} quality={d.quality} />
      {firstLaunch}
      <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-2 xl:gap-6">
        <PricesCard block={d.prices} today={d.today} />
        <YtdCard block={d.trade} />
        <ChangesCard b={d.briefing} />
        <NewsCard block={d.news} />
        {!isMirror() && (
          <SimpleCard title={t('corrections.box.title')} sub={t('corrections.box.sub')} className="xl:col-span-2" extra={<PenLine size={22} className="text-gold-dark" aria-hidden />}>
            <div className="pb-2" id="scrivi"><WriteBox /></div>
          </SimpleCard>
        )}
      </div>
      <p className="mt-6 text-[0.98rem] text-muted">
        {t('simple.overview.fullHint')}{' '}
        <button type="button" className="link" onClick={() => setView('full')}>{t('simple.toFull')}</button>
      </p>
    </div>
  )
}
