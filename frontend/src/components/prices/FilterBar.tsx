// Filter bar for /prezzi: price type (prominent), origins (chips), dimension selects and view toggles.
import clsx from 'clsx'
import { Info, RotateCcw } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Segmented } from '@/components/ui'
import { useI18n } from '@/i18n'
import { useLabels } from '@/lib/meta'
import { Chip, Field } from './bits'
import type { Ccy, FacetsResponse, Freq, MassUnit, PriceFilterState, PriceTypeKey, RangePreset } from './types'
import { CCYS, colorLabel, FREQS, PRICE_TYPE_ORDER, RANGES } from './utils'

const ORIGINS_COLLAPSED = 14

function FieldSelect({ label, value, onChange, disabled, children }: {
  label: string; value: string; onChange: (v: string) => void; disabled?: boolean; children: ReactNode
}) {
  return (
    <Field label={label}>
      <select className="field pr-8 disabled:bg-paper disabled:text-charcoal-soft" value={value} disabled={disabled}
        onChange={(e) => onChange(e.target.value)} aria-label={label}>
        {children}
      </select>
    </Field>
  )
}

export function PriceTypeSelector({ value, counts, onChange }: {
  value: PriceTypeKey | null
  counts: Record<string, number>
  onChange: (v: PriceTypeKey) => void
}) {
  const { t } = useI18n()
  const { priceType } = useLabels()
  return (
    <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2" role="tablist" aria-label={t('prices.type.label')}>
      {[...PRICE_TYPE_ORDER, ...((counts.other ?? 0) > 0 ? ['other' as const] : [])].map((k) => {
        const n = counts[k] ?? 0
        const active = k === value
        return (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={active}
            title={priceType(k)}
            onClick={() => onChange(k)}
            className={clsx(
              'flex flex-col items-start rounded-sm border px-3.5 py-2 text-left transition-colors min-w-0',
              active ? 'border-forest-800 bg-forest-800 text-ivory'
                : n ? 'border-line bg-white text-charcoal hover:border-forest-600' : 'border-dashed border-line bg-paper text-muted hover:border-forest-300',
            )}
          >
            <span className="font-serif text-[1.05rem] font-semibold leading-tight">{t(`prices.type.short.${k}`)}</span>
            <span className={clsx('text-[0.8rem] mt-0.5 leading-snug', active ? 'text-gold-light' : 'text-muted')}>
              {t(`prices.type.hint.${k}`)}{!n && <> · <span className="uppercase tracking-[0.06em] text-[0.72rem]">{t('prices.type.noData')}</span></>}
            </span>
          </button>
        )
      })}
    </div>
  )
}

export function FilterBar({ facets, typeCounts, state, update, reset, hasDimFilters }: {
  facets: FacetsResponse | undefined
  typeCounts: Record<string, number>
  state: PriceFilterState
  update: (p: Partial<PriceFilterState>) => void
  reset: () => void
  hasDimFilters: boolean
}) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  const [showAllOrigins, setShowAllOrigins] = useState(false)

  const origins = facets?.origins ?? []
  // keep selected origins visible even when collapsed
  const shown = showAllOrigins ? origins : origins.filter((o, i) => i < ORIGINS_COLLAPSED || state.origins.includes(o.key))
  const hidden = origins.length - shown.length
  const toggleOrigin = (k: string) =>
    update({ origins: state.origins.includes(k) ? state.origins.filter((x) => x !== k) : [...state.origins, k] })

  const countryName = (o: { key: string; name_it: string | null; name_en: string | null }) =>
    o.key === '_none' ? t('prices.originUnknown') : (lang === 'it' ? o.name_it : o.name_en) || country(o.key)

  const singleOrAll = (n: number, selected: string) => n <= 1 && !selected

  return (
    <section className="panel mb-5">
      <div className="px-5 pt-4 pb-4 border-b border-line-soft">
        <div className="eyebrow mb-2">{t('prices.type.label')}</div>
        <PriceTypeSelector value={state.type} counts={typeCounts} onChange={(k) => update({ type: k })} />
        {state.type && (
          <p className="mt-3 flex items-start gap-2 text-[0.95rem] text-charcoal-soft max-w-4xl">
            <Info size={17} className="mt-[3px] shrink-0 text-gold" />
            <span>{t(`prices.type.explain.${state.type}`)}</span>
          </p>
        )}
      </div>

      {origins.length > 0 && (
        <div className="px-5 py-3.5 border-b border-line-soft">
          <div className="eyebrow mb-2">{t('prices.f.origins')}</div>
          <div className="flex flex-wrap gap-1.5">
            <Chip active={state.origins.length === 0} onClick={() => update({ origins: [] })}>{t('prices.f.allOrigins')}</Chip>
            {shown.map((o) => (
              <Chip key={o.key} active={state.origins.includes(o.key)} onClick={() => toggleOrigin(o.key)}>
                {countryName(o)}
              </Chip>
            ))}
            {hidden > 0 && (
              <button type="button" className="btn-ghost !px-2 !py-1 text-[0.92rem]" onClick={() => setShowAllOrigins(true)}>
                {t('prices.f.moreOrigins', { n: hidden })}
              </button>
            )}
            {showAllOrigins && origins.length > ORIGINS_COLLAPSED && (
              <button type="button" className="btn-ghost !px-2 !py-1 text-[0.92rem]" onClick={() => setShowAllOrigins(false)}>
                {t('prices.f.fewerOrigins')}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="px-5 py-3.5 grid gap-x-4 gap-y-3 grid-cols-2 xl:grid-cols-4">
        <FieldSelect label={t('prices.f.variety')} value={state.variety} onChange={(v) => update({ variety: v })}
          disabled={singleOrAll(facets?.varieties.length ?? 0, state.variety)}>
          <option value="">{t('prices.f.allVarieties')}</option>
          {(facets?.varieties ?? []).map((v) => <option key={v.key} value={v.key}>{variety(v.key)}</option>)}
        </FieldSelect>
        <FieldSelect label={t('prices.f.market')} value={state.market} onChange={(v) => update({ market: v })}
          disabled={singleOrAll(facets?.markets.length ?? 0, state.market)}>
          <option value="">{(facets?.markets.length ?? 0) === 1 ? countryName(facets!.markets[0]) : t('prices.f.allMarkets')}</option>
          {(facets?.markets.length ?? 0) > 1 && facets!.markets.map((m) => <option key={m.key} value={m.key}>{countryName(m)}</option>)}
        </FieldSelect>
        <FieldSelect label={t('prices.f.source')} value={state.source} onChange={(v) => update({ source: v })}
          disabled={singleOrAll(facets?.sources.length ?? 0, state.source)}>
          <option value="">{(facets?.sources.length ?? 0) === 1 ? (facets!.sources[0].publisher || facets!.sources[0].name) : t('prices.f.allSources')}</option>
          {(facets?.sources.length ?? 0) > 1 && facets!.sources.map((s) => <option key={s.key} value={s.key}>{s.publisher || s.name}</option>)}
        </FieldSelect>
        <FieldSelect label={t('prices.f.colour')} value={state.color} onChange={(v) => update({ color: v })}
          disabled={singleOrAll(facets?.color_grades.length ?? 0, state.color)}>
          <option value="">{(facets?.color_grades.length ?? 0) === 1 ? colorLabel(facets!.color_grades[0].key, t) : t('prices.f.allColours')}</option>
          {(facets?.color_grades.length ?? 0) > 1 && facets!.color_grades.map((c) => <option key={c.key} value={c.key}>{colorLabel(c.key, t)}</option>)}
        </FieldSelect>
      </div>

      <div className="px-5 pb-4 pt-1 flex flex-wrap items-end gap-x-6 gap-y-3">
        <Field label={t('prices.f.currency')}>
          <Segmented<Ccy> size="sm" value={state.ccy} onChange={(v) => update({ ccy: v })} options={CCYS.map((c) => ({ value: c, label: c }))} />
        </Field>
        <Field label={t('prices.f.unit')}>
          <Segmented<MassUnit> size="sm" value={state.unit} onChange={(v) => update({ unit: v })}
            options={(['kg', 'lb'] as MassUnit[]).map((u) => ({ value: u, label: t(`prices.f.unit.${u}`) }))} />
        </Field>
        <Field label={t('prices.f.range')}>
          <Segmented<RangePreset> size="sm" value={state.range} onChange={(v) => update({ range: v })}
            options={RANGES.map((r) => ({ value: r, label: t(`prices.f.range.${r}`) }))} />
        </Field>
        <Field label={t('prices.f.freq')}>
          <Segmented<Freq> size="sm" value={state.freq} onChange={(v) => update({ freq: v })}
            options={FREQS.map((f) => ({ value: f, label: t(`prices.f.freq.${f}`) }))} />
        </Field>
        {hasDimFilters && (
          <button type="button" className="btn-ghost !py-1.5 ml-auto" onClick={reset}>
            <RotateCcw size={15} /> {t('prices.f.reset')}
          </button>
        )}
        <p className="basis-full text-[0.82rem] text-muted">{t('prices.howToRead')}</p>
      </div>
    </section>
  )
}
