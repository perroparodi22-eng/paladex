// Profile · "2026 finora": the freshest period first. The country's own monthly customs figure for
// the year so far against THE SAME months of the year before (one source, never mixed); without
// one, what its partners declare month by month (one row per declaring country, never added up);
// without either, a plain note that the full years below are the newest figures.
import { CalendarClock, Info } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DemoBadge, FreshnessBadge, SourceLine, StatusBadge } from '@/components/ui'
import { BasisMarks, fmtT, fmtUsd, fmtUv, nameOf, YoY } from '@/components/trade/bits'
import type { TradeFlow } from '@/components/trade/types'
import { fmtMonthLong, fmtMonthSpan, prevSpan, type YtdFigure, type YtdSection } from '@/components/trade/ytd'
import { useI18n } from '@/i18n'
import { useLabels } from '@/lib/meta'

/** "2026 finora (gen–set)" / "2026 so far (Jan–Sep)"; a past year still being completed: "2026 (gen–nov)". */
export function useYtdTitle() {
  const { t, lang } = useI18n()
  return (f: Pick<YtdFigure, 'year' | 'month_from' | 'month_to' | 'is_current_year'>) =>
    t(f.is_current_year ? 'countries.ytd.title' : 'countries.ytd.titlePast', { y: f.year, m: fmtMonthSpan(f.month_from, f.month_to, lang) })
}

function ExcludedNote({ f }: { f: YtdFigure }) {
  const { t, lang } = useI18n()
  if (!f.excluded_months.length) return null
  const partial = f.excluded_months.filter((e) => e.reason === 'no_total').map((e) => fmtMonthLong(e.month, lang))
  const gap = f.excluded_months.filter((e) => e.reason === 'after_gap').map((e) => fmtMonthLong(e.month, lang))
  return (
    <div className="mt-1 text-[0.8rem] text-muted">
      {partial.length > 0 && <div>{t('countries.ytd.excludedPartial', { m: partial.join(', ') })}</div>}
      {gap.length > 0 && <div>{t('countries.ytd.excludedGap', { m: gap.join(', ') })}</div>}
    </div>
  )
}

function OwnFigure({ f, flow }: { f: YtdFigure; flow: TradeFlow }) {
  const { t, lang } = useI18n()
  const title = useYtdTitle()
  const prev = f.previous
  const vs = prevSpan(f, lang)
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="font-serif text-[1.08rem] font-semibold text-charcoal">{title(f)}</span>
        <span className="text-[0.8rem] text-muted">{t(flow === 'export' ? 'countries.ytd.ownExp' : 'countries.ytd.ownImp')}</span>
      </div>
      <div className="mt-2 grid gap-x-8 gap-y-3 sm:grid-cols-3">
        <div className="min-w-0">
          <div className="eyebrow">{t('countries.ytd.volume')}</div>
          <div className="num text-[1.5rem] leading-tight text-charcoal">
            {fmtT(f.net_weight_kg, lang)}<span className="text-muted text-[0.6em] ml-1">t</span>
            <BasisMarks summedPartners={f.summed_from_partners} partners={f.partners_count} />
          </div>
          {prev && (
            <div className="text-[0.85rem] text-muted">
              <YoY pct={f.change_volume_pct} /> {t('countries.ytd.vs', { p: vs })}
              {prev.net_weight_kg !== null && <span className="num"> ({fmtT(prev.net_weight_kg, lang)} t)</span>}
            </div>
          )}
        </div>
        <div className="min-w-0">
          <div className="eyebrow">{t('countries.ytd.value')}</div>
          <div className="num text-[1.5rem] leading-tight text-charcoal">{fmtUsd(f.usd_value, lang)}</div>
          {prev && (
            <div className="text-[0.85rem] text-muted">
              <YoY pct={f.change_value_pct} /> {t('countries.ytd.vs', { p: vs })}
              {prev.usd_value !== null && <span className="num"> ({fmtUsd(prev.usd_value, lang)})</span>}
            </div>
          )}
        </div>
        <div className="min-w-0">
          <div className="eyebrow">{t('trade.leaders.col.uv')}</div>
          <div className="num text-[1.5rem] leading-tight text-charcoal">{fmtUv(f.unit_value_usd_per_kg, lang)}</div>
          {prev && f.unit_value_usd_per_kg !== null && (
            <div className="text-[0.85rem] text-muted"><YoY pct={f.change_unit_value_pct} /> {t('countries.ytd.vs', { p: vs })}</div>
          )}
        </div>
      </div>
      {!prev && (
        <div className="mt-2 text-[0.85rem] text-muted">
          {t('countries.ytd.noCompare', { p: vs })}
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {f.data_status && !['published', 'live', 'demo'].includes(f.data_status) && <StatusBadge status={f.data_status} />}
        <SourceLine p={{ source: f.source, published_at: f.published_at, source_url: f.source_url, is_demo: f.is_demo }} />
        {f.freshness && <FreshnessBadge status={f.freshness.status} ageDays={f.freshness.age_days} />}
      </div>
      <div className="mt-1 text-[0.8rem] text-muted">
        {prev ? t('countries.ytd.rule', { m: fmtMonthSpan(f.month_from, f.month_to, lang), y: f.year, py: f.prev_year })
          : t('countries.ytd.ruleNoPrev')}
      </div>
      <ExcludedNote f={f} />
    </div>
  )
}

function MirrorTable({ s, flow, name }: { s: NonNullable<YtdSection['mirror']>; flow: TradeFlow; name: string }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const year = s.rows[0]?.year
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="font-serif text-[1.08rem] font-semibold text-charcoal">{t('countries.ytd.mirrorTitle', { y: year ?? '' })}</span>
        <span className="text-[0.8rem] text-muted max-w-2xl">{t(flow === 'export' ? 'countries.ytd.mirrorHintExp' : 'countries.ytd.mirrorHintImp', { c: name })}</span>
      </div>
      <div className="relative overflow-x-auto mt-2">
        <table className="w-full min-w-[24rem] text-[0.92rem]">
          <thead>
            <tr className="border-b border-line text-left text-[0.7rem] uppercase tracking-wider text-muted">
              <th className="py-1.5 px-2 font-medium">{t('countries.trade.col.declaredBy')}</th>
              <th className="py-1.5 px-2 font-medium">{t('countries.ytd.col.months')}</th>
              <th className="py-1.5 px-2 font-medium text-right">t</th>
              <th className="py-1.5 px-2 font-medium text-right">{t('countries.ytd.col.change')}</th>
              <th className="py-1.5 px-2 font-medium">{t('prov.source')}</th>
            </tr>
          </thead>
          <tbody>
            {s.rows.map((r) => (
              <tr key={r.iso3} className="border-b border-line-soft last:border-0">
                <td className="py-1.5 px-2">
                  {r.link ? <Link to={r.link} className="hover:text-forest-800 hover:underline decoration-gold/50 underline-offset-2">{nameOf(r, lang, country)}</Link> : nameOf(r, lang, country)}
                </td>
                <td className="py-1.5 px-2 num whitespace-nowrap">{fmtMonthSpan(r.month_from, r.month_to, lang)} {r.year}</td>
                <td className="py-1.5 px-2 num text-right">{fmtT(r.net_weight_kg, lang)}</td>
                <td className="py-1.5 px-2 text-right" title={r.comparable ? t('countries.ytd.vs', { p: prevSpan(r, lang) }) : t('countries.ytd.noCompareShort')}>
                  {r.comparable ? <YoY pct={r.change_volume_pct} /> : <span className="text-muted text-[0.8rem]">{t('countries.ytd.noCompareShort')}</span>}
                </td>
                <td className="py-1.5 px-2 text-[0.82rem] text-muted">
                  {r.is_demo && <span className="mr-1"><DemoBadge /></span>}{r.source?.publisher || r.source?.name}
                  {r.data_status && !['published', 'live', 'demo'].includes(r.data_status) && <span className="ml-1.5"><StatusBadge status={r.data_status} /></span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-1 text-[0.8rem] text-muted">
        {t('countries.ytd.mirrorRule')}
        {s.count > s.rows.length && <> {t('countries.ytd.mirrorMore', { n: s.count - s.rows.length })}</>}
      </div>
    </div>
  )
}

/** The block at the top of the trade panel, for one flow. */
export function ProfileYtd({ s, flow, name, today }: { s: YtdSection | undefined; flow: TradeFlow; name: string; today: string }) {
  const { t, lang } = useI18n()
  if (!s) return null
  const year = Number(today.slice(0, 4)) || new Date().getFullYear()
  if (s.own) {
    return (
      <section className="rounded-sm border border-forest-100 bg-forest-50/40 px-4 py-3" data-ytd="own">
        <OwnFigure f={s.own} flow={flow} />
      </section>
    )
  }
  if (s.mirror && s.mirror.rows.length) {
    return (
      <section className="rounded-sm border border-dashed border-gold-light/70 bg-gold-pale/20 px-4 py-3" data-ytd="mirror">
        <div className="mb-2 flex items-start gap-2 text-[0.85rem] text-muted">
          <Info size={15} className="mt-[2px] shrink-0 text-gold" />
          <span>{t('countries.ytd.noOwn', { y: year })}</span>
        </div>
        <MirrorTable s={s.mirror} flow={flow} name={name} />
      </section>
    )
  }
  const note = s.status === 'stale' ? t('countries.ytd.stale', { m: fmtMonthLong(s.last_month, lang), y: year })
    : s.status === 'full_year' ? t('countries.ytd.fullYear')
      : s.status === 'incomplete' ? t('countries.ytd.incomplete', { y: year })
        : t('countries.ytd.none', { y: year })
  return (
    <div className="flex items-start gap-2 rounded-sm border border-line-soft bg-paper px-3 py-2 text-[0.85rem] text-muted" data-ytd="none">
      <CalendarClock size={15} className="mt-[2px] shrink-0 text-gold" />
      <span>{note}</span>
    </div>
  )
}
