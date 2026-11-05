// Guided rule editor: pick what to watch (template or example), fill the conditions from lists of
// what actually has data, read the rule back in plain words and test it on today's data.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { FileText, Newspaper, Scale, Ship, TrendingUp, X } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Loading, Note, Panel, Segmented, Select } from '@/components/ui'
import { colorLabel } from '@/components/prices/utils'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import type { Lang } from '@/lib/types'
import { PreviewResult } from './PreviewResult'
import { ALERT_TYPES, type AlertRule, type AlertType, type Direction, type OptionsResponse, type PreviewResponse, type RuleParams } from './types'
import {
  defaultParams, errorText, fixPrice, fixTrade, num, paramsReady, parseKeywords, priceChoices, RELEVANCE_STEPS, str, strList,
  tradeChoices,
} from './utils'

const ICONS: Record<AlertType, ReactNode> = {
  price_change: <TrendingUp size={18} />, new_report: <FileText size={18} />, news_keyword: <Newspaper size={18} />,
  regulation: <Scale size={18} />, trade_change: <Ship size={18} />,
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const h = setTimeout(() => setV(value), ms)
    return () => clearTimeout(h)
  }, [value, ms])
  return v
}

type SetParams = (p: RuleParams) => void

function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={clsx('block min-w-0', className)}>
      <span className="label">{label}</span>
      {children}
    </label>
  )
}

function ThresholdInput({ value, onChange, label }: { value: number; onChange: (v: number) => void; label: string }) {
  return (
    <Field label={label}>
      <input type="number" min={0.5} max={1000} step={0.5} inputMode="decimal" className="field num" value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
    </Field>
  )
}

function DirectionField({ value, onChange }: { value: Direction; onChange: (d: Direction) => void }) {
  const { t } = useI18n()
  return (
    <div className="min-w-0">
      <span className="label">{t('alerts.f.direction')}</span>
      <Segmented value={value} onChange={onChange} size="sm"
        options={(['up', 'down', 'any'] as Direction[]).map((d) => ({ value: d, label: t(`alerts.dir.${d}`) }))} />
    </div>
  )
}

/** Countries as removable chips plus a list to add more (the countries that have data first). */
function CountryPicker({ selected, available, onChange, emptyLabel }: {
  selected: string[]; available: { iso3: string; count: number }[]; onChange: (v: string[]) => void; emptyLabel: string
}) {
  const { t } = useI18n()
  const { country } = useLabels()
  const rest = available.filter((c) => !selected.includes(c.iso3))
  return (
    <div className="min-w-0">
      <span className="label">{t('alerts.f.countries')}</span>
      <div className="flex flex-wrap items-center gap-2">
        {selected.length === 0 && <span className="text-sm text-muted">{emptyLabel}</span>}
        {selected.map((c) => (
          <button key={c} type="button" onClick={() => onChange(selected.filter((x) => x !== c))}
            className="inline-flex items-center gap-1 rounded-sm border border-forest-700 bg-forest-800 text-ivory px-2 py-0.5 text-sm"
            aria-label={t('alerts.f.remove', { x: country(c) })} title={t('alerts.f.remove', { x: country(c) })}>
            {country(c)} <X size={13} />
          </button>
        ))}
        {rest.length > 0 && (
          <Select aria-label={t('alerts.f.addCountry')} value="" className="min-w-[12rem] flex-1 sm:flex-none"
            onChange={(e) => e.target.value && onChange([...selected, e.target.value])}>
            <option value="">{t('alerts.f.addCountry')}</option>
            {rest.map((c) => <option key={c.iso3} value={c.iso3}>{country(c.iso3)} ({c.count})</option>)}
          </Select>
        )}
      </div>
    </div>
  )
}

function Checks({ items, selected, onChange }: {
  items: { key: string; label: string; hint?: string }[]; selected: string[]; onChange: (v: string[]) => void
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {items.map((it) => (
        <label key={it.key} className="flex items-start gap-2 text-[0.95rem] cursor-pointer">
          <input type="checkbox" className="mt-1 accent-forest-700" checked={selected.includes(it.key)}
            onChange={(e) => onChange(e.target.checked ? [...selected, it.key] : selected.filter((x) => x !== it.key))} />
          <span className="min-w-0 break-words">{it.label}{it.hint && <span className="text-muted text-sm"> · {it.hint}</span>}</span>
        </label>
      ))}
    </div>
  )
}

function PriceFields({ p, set, o }: { p: RuleParams; set: SetParams; o: OptionsResponse }) {
  const { t } = useI18n()
  const { country, variety, priceType } = useLabels()
  if (!o.price.length) return <Note tone="warn">{t('alerts.f.noPrice')}</Note>
  const c = priceChoices(o.price, p)
  const fix = (patch: RuleParams) => set(fixPrice(o.price, { ...p, ...patch }))
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Field label={t('alerts.f.priceType')}>
          <select className="field" value={str(p.price_type) ?? ''} onChange={(e) => fix({ price_type: e.target.value })}>
            {c.types.map((k) => <option key={k} value={k}>{priceType(k)}</option>)}
          </select>
        </Field>
        <Field label={t('alerts.f.origin')}>
          <select className="field" value={str(p.origin) ?? ''} onChange={(e) => fix({ origin: e.target.value })}>
            {c.origins.map((k) => <option key={k} value={k}>{country(k)}</option>)}
          </select>
        </Field>
        <Field label={t('alerts.f.variety')}>
          <select className="field" value={str(p.variety) ?? ''} onChange={(e) => fix({ variety: e.target.value })}>
            {c.varieties.map((k) => <option key={k} value={k}>{variety(k)}</option>)}
          </select>
        </Field>
        <Field label={t('alerts.f.market')}>
          <select className="field" value={str(p.market) ?? ''} onChange={(e) => fix({ market: e.target.value || null })}>
            <option value="">{t('alerts.f.anyMarket')}</option>
            {c.markets.map((k) => <option key={k} value={k}>{country(k)}</option>)}
          </select>
        </Field>
        <Field label={t('alerts.f.color')}>
          <select className="field" value={str(p.color_grade) ?? ''} onChange={(e) => fix({ color_grade: e.target.value || null })}>
            <option value="">{t('alerts.f.anyColor')}</option>
            {c.colors.map((k) => <option key={k} value={k}>{colorLabel(k, t)}</option>)}
          </select>
        </Field>
        <ThresholdInput label={t('alerts.f.threshold')} value={num(p.threshold_pct, 5)} onChange={(v) => set({ ...p, threshold_pct: v })} />
      </div>
      <DirectionField value={(str(p.direction) as Direction) ?? 'up'} onChange={(d) => set({ ...p, direction: d })} />
      <p className="text-sm text-muted">{t('alerts.f.priceNote')}</p>
    </div>
  )
}

function ReportFields({ p, set, o }: { p: RuleParams; set: SetParams; o: OptionsResponse }) {
  const { t, lang } = useI18n()
  if (!o.report_sources.length) return <Note tone="warn">{t('alerts.f.noReports')}</Note>
  const items = o.report_sources.map((s) => ({
    key: s.key, label: lang === 'it' ? s.name : s.publisher || s.name,
    hint: s.reports === 1
      ? (s.latest_published_at ? t('alerts.f.reportOne', { d: fmtDate(s.latest_published_at, lang) }) : t('alerts.f.reportOneNoDate'))
      : s.latest_published_at ? t('alerts.f.reports', { n: s.reports, d: fmtDate(s.latest_published_at, lang) }) : t('alerts.f.reportsNoDate', { n: s.reports }),
  }))
  return (
    <div>
      <span className="label">{t('alerts.f.sources')}</span>
      <Checks items={items} selected={strList(p.source_keys)} onChange={(v) => set({ ...p, source_keys: v })} />
    </div>
  )
}

function NewsFields({ p, set, o }: { p: RuleParams; set: SetParams; o: OptionsResponse }) {
  const { t } = useI18n()
  const [text, setText] = useState(() => strList(p.keywords).join(', '))
  const rel = num(p.min_relevance, 0)
  return (
    <div className="flex flex-col gap-3">
      <Field label={t('alerts.f.keywords')}>
        <input type="text" className="field" value={text} placeholder={t('alerts.f.keywordsPh')}
          onChange={(e) => { setText(e.target.value); set({ ...p, keywords: parseKeywords(e.target.value) }) }} />
      </Field>
      <CountryPicker selected={strList(p.countries)} available={o.news.countries} emptyLabel={t('alerts.f.noCountries')}
        onChange={(v) => set({ ...p, countries: v })} />
      <div>
        <span className="label">{t('alerts.f.minRelevance')}</span>
        <Segmented size="sm" value={String(RELEVANCE_STEPS.includes(rel as 0) ? rel : 0)}
          onChange={(v) => set({ ...p, min_relevance: Number(v) })}
          options={RELEVANCE_STEPS.map((r) => ({ value: String(r), label: t(`alerts.f.relevance.${r}`) }))} />
      </div>
      <p className="text-sm text-muted">{t('alerts.f.newsNote')}</p>
    </div>
  )
}

function RegulationFields({ p, set, o }: { p: RuleParams; set: SetParams; o: OptionsResponse }) {
  const { t } = useI18n()
  const juris = strList(p.jurisdictions)
  const jl = (k: string) => {
    const s = t(`alerts.j.${k}`)
    return s === `alerts.j.${k}` ? k : s
  }
  const dl = (k: string) => {
    const s = t(`alerts.doc.${k}`)
    return s === `alerts.doc.${k}` ? k : s
  }
  const types = new Map<string, number>()
  for (const d of o.regulation.doc_types) {
    if (!juris.length || juris.includes(d.jurisdiction)) types.set(d.key, (types.get(d.key) ?? 0) + d.count)
  }
  const hasTariffs = o.regulation.jurisdictions.some((j) => j.tariffs > 0 && (!juris.length || juris.includes(j.key)))
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <span className="label">{t('alerts.f.jurisdictions')}</span>
        <Checks selected={juris} onChange={(v) => set({ ...p, jurisdictions: v })}
          items={o.regulation.jurisdictions.map((j) => ({ key: j.key, label: jl(j.key), hint: t('alerts.f.docsCount', { n: j.count }) }))} />
        {!juris.length && <p className="text-sm text-muted mt-1">{t('alerts.f.anyJurisdiction')}</p>}
      </div>
      <div>
        <span className="label">{t('alerts.f.docTypes')}</span>
        <Checks selected={strList(p.doc_types)} onChange={(v) => set({ ...p, doc_types: v })}
          items={[...types.entries()].map(([k, n]) => ({ key: k, label: dl(k), hint: String(n) }))} />
        {!strList(p.doc_types).length && <p className="text-sm text-muted mt-1">{t('alerts.f.allTypes')}</p>}
      </div>
      <div className="md:col-span-2">
        <CountryPicker selected={strList(p.countries)} available={o.regulation.countries} emptyLabel={t('alerts.f.noCountriesReg')}
          onChange={(v) => set({ ...p, countries: v })} />
      </div>
      {hasTariffs && (
        <label className="md:col-span-2 flex items-start gap-2 text-[0.95rem] cursor-pointer">
          <input type="checkbox" className="mt-1 accent-forest-700" checked={p.include_tariffs !== false}
            onChange={(e) => set({ ...p, include_tariffs: e.target.checked })} />
          <span>{t('alerts.f.includeTariffs')}</span>
        </label>
      )}
    </div>
  )
}

function TradeFields({ p, set, o }: { p: RuleParams; set: SetParams; o: OptionsResponse }) {
  const { t } = useI18n()
  const { country } = useLabels()
  if (!o.trade.length) return <Note tone="warn">{t('alerts.f.noTrade')}</Note>
  const c = tradeChoices(o.trade, p)
  const fix = (patch: RuleParams) => set(fixTrade(o.trade, { ...p, ...patch }))
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Field label={t('alerts.f.reporter')}>
          <select className="field" value={str(p.reporter) ?? ''} onChange={(e) => fix({ reporter: e.target.value, partner: 'WLD' })}>
            {c.reporters.map((k) => <option key={k} value={k}>{country(k)}</option>)}
          </select>
        </Field>
        <Field label={t('alerts.f.partner')}>
          <select className="field" value={str(p.partner) ?? 'WLD'} onChange={(e) => fix({ partner: e.target.value })}>
            {c.partners.map((k) => <option key={k} value={k}>{k === 'WLD' ? t('alerts.f.partnerTotal') : country(k)}</option>)}
          </select>
        </Field>
        <ThresholdInput label={t('alerts.f.threshold')} value={num(p.threshold_pct, 20)} onChange={(v) => set({ ...p, threshold_pct: v })} />
      </div>
      <div className="flex flex-wrap gap-4">
        <div>
          <span className="label">{t('alerts.f.flow')}</span>
          <Segmented size="sm" value={(str(p.flow) as 'import' | 'export') ?? 'import'} onChange={(v) => fix({ flow: v, partner: 'WLD' })}
            options={c.flows.map((f) => ({ value: f, label: t(`alerts.flow.${f}`) }))} />
        </div>
        <div>
          <span className="label">{t('alerts.f.freq')}</span>
          <Segmented size="sm" value={(str(p.freq) as 'M' | 'A') ?? 'M'} onChange={(v) => set({ ...p, freq: v })}
            options={c.freqs.map((f) => ({ value: f, label: t(`alerts.freq.${f}`) }))} />
        </div>
        <DirectionField value={(str(p.direction) as Direction) ?? 'any'} onChange={(d) => set({ ...p, direction: d })} />
      </div>
    </div>
  )
}

/** A short default name, e.g. "Argentina millefiori +5%" (the owner can change it). */
export function suggestName(type: AlertType, p: RuleParams, fns: {
  t: (k: string, v?: Record<string, string | number>) => string; country: (c: string) => string; variety: (v: string) => string; lang: Lang
}, o?: OptionsResponse): string {
  const { t, country, variety } = fns
  const sign = (d: unknown) => (d === 'down' ? '−' : d === 'any' ? '±' : '+')
  switch (type) {
    case 'price_change':
      return `${country(str(p.origin) ?? '')} ${variety(str(p.variety) ?? '').toLowerCase()} ${sign(p.direction)}${num(p.threshold_pct, 5)}%`
    case 'new_report': {
      const names = strList(p.source_keys).map((k) => o?.report_sources.find((s) => s.key === k)?.name ?? k)
      return `${t('alerts.tpl.new_report.title')}: ${names.join(', ')}`.slice(0, 200)
    }
    case 'news_keyword': {
      const parts = [...strList(p.keywords).slice(0, 3), ...strList(p.countries).slice(0, 2).map(country)]
      return `${t('alerts.tpl.news_keyword.title')}: ${parts.join(', ')}`.slice(0, 200)
    }
    case 'regulation': {
      const j = strList(p.jurisdictions).map((k) => t(`alerts.j.${k}`))
      return `${t('alerts.tpl.regulation.title')}${j.length ? ` (${j.join(', ')})` : ''}`
    }
    case 'trade_change': {
      const partner = str(p.partner) && p.partner !== 'WLD' ? ` · ${country(p.partner as string)}` : ''
      return `${t(`alerts.flow.${str(p.flow) ?? 'import'}`)} ${country(str(p.reporter) ?? '')}${partner} ${sign(p.direction)}${num(p.threshold_pct, 20)}%`
    }
  }
}

export function RuleEditor({ rule, options, optionsLoading, onDone }: {
  rule?: AlertRule | null
  options: OptionsResponse | undefined
  optionsLoading?: boolean
  onDone: () => void
}) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  const qc = useQueryClient()
  const [type, setType] = useState<AlertType | null>(rule?.alert_type ?? null)
  const [params, setParams] = useState<RuleParams>(rule?.params ?? {})
  const [name, setName] = useState(rule?.name ?? '')
  const [nameTouched, setNameTouched] = useState(Boolean(rule))
  const [formKey, setFormKey] = useState(0)          // remounts the fields when a template / example is picked

  const fns = useMemo(() => ({ t, country, variety, lang }), [t, country, variety, lang])
  useEffect(() => {
    if (!nameTouched && type) setName(suggestName(type, params, fns, options))
  }, [type, params, nameTouched, fns, options])

  const choose = (k: AlertType, p?: RuleParams, n?: string) => {
    setType(k)
    setParams(p ?? defaultParams(k, options))
    if (n) { setName(n); setNameTouched(true) } else setNameTouched(false)
    setFormKey((x) => x + 1)
  }

  const ready = type !== null && paramsReady(type, params)
  const debounced = useDebounced(params, 450)
  const preview = useQuery({
    queryKey: ['alerts', 'preview', type, debounced],
    queryFn: () => api.post<PreviewResponse>('/alerts/preview', { alert_type: type, params: debounced }),
    enabled: type !== null && paramsReady(type, debounced),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })

  const save = useMutation({
    mutationFn: () => (rule
      ? api.put(`/alerts/rules/${rule.id}`, { name: name.trim(), params })
      : api.post('/alerts/rules', { name: name.trim(), alert_type: type, params, enabled: true })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alerts'] })
      onDone()
    },
  })

  const pvData = preview.data && preview.data.alert_type === type ? preview.data : undefined
  const changed = rule ? JSON.stringify(params) !== JSON.stringify(rule.params) : false

  return (
    <Panel className="mb-6" eyebrow={t('alerts.title')} title={rule ? t('alerts.editor.titleEdit') : t('alerts.editor.titleNew')}
      actions={<button type="button" className="btn-ghost !px-2" onClick={onDone} aria-label={t('ui.close')}><X size={18} /></button>}>
      {optionsLoading && !options ? <Loading label={t('alerts.editor.loadingOptions')} /> : (
        <div className="flex flex-col gap-6">
          <section>
            <h3 className="text-[1.05rem] font-semibold mb-2">{t('alerts.editor.step1')}</h3>
            {rule ? (
              <p className="text-sm text-muted">{t(`alerts.tpl.${rule.alert_type}.title`)} — {t('alerts.editor.typeFixed')}</p>
            ) : (
              <>
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
                  {ALERT_TYPES.map((k) => (
                    <button key={k} type="button" onClick={() => choose(k)} aria-pressed={type === k}
                      className={clsx('text-left rounded-sm border p-3 transition-colors min-w-0',
                        type === k ? 'border-forest-700 bg-forest-50' : 'border-line bg-white hover:border-forest-600')}>
                      <div className="flex items-center gap-2 font-medium text-forest-800">{ICONS[k]} {t(`alerts.tpl.${k}.title`)}</div>
                      <div className="text-sm text-muted mt-1">{t(`alerts.tpl.${k}.hint`)}</div>
                    </button>
                  ))}
                </div>
                {(options?.examples.length ?? 0) > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-muted">{t('alerts.editor.examples')}</span>
                    {options!.examples.map((ex) => (
                      <button key={ex.name} type="button" className="btn-secondary !px-2.5 !py-1 text-sm"
                        onClick={() => choose(ex.alert_type, { ...ex.params }, ex.name)}>
                        {ex.name}
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </section>

          {type && options && (
            <section key={formKey}>
              <h3 className="text-[1.05rem] font-semibold mb-2">{t('alerts.editor.step2')}</h3>
              {type === 'price_change' && <PriceFields p={params} set={setParams} o={options} />}
              {type === 'new_report' && <ReportFields p={params} set={setParams} o={options} />}
              {type === 'news_keyword' && <NewsFields p={params} set={setParams} o={options} />}
              {type === 'regulation' && <RegulationFields p={params} set={setParams} o={options} />}
              {type === 'trade_change' && <TradeFields p={params} set={setParams} o={options} />}
              {type === 'news_keyword' && !ready && <p className="text-sm text-warn mt-2">{t('alerts.f.required')}</p>}
            </section>
          )}

          {type && (
            <section>
              <h3 className="text-[1.05rem] font-semibold mb-2">{t('alerts.editor.step3')}</h3>
              <Field label={t('alerts.editor.name')} className="max-w-2xl">
                <input type="text" className="field" maxLength={200} value={name}
                  onChange={(e) => { setName(e.target.value); setNameTouched(true) }} />
              </Field>
              <div className="grid gap-4 mt-4 lg:grid-cols-2 items-start">
                <div className="border border-forest-100 bg-forest-50 rounded-sm p-3 min-w-0">
                  <div className="eyebrow mb-1">{t('alerts.editor.describes')}</div>
                  <p className="text-[0.95rem] text-forest-800 break-words">
                    {pvData ? (lang === 'it' ? pvData.description_it : pvData.description_en) : '…'}
                  </p>
                  {rule && changed && <p className="text-sm text-muted mt-2">{t('alerts.editor.restartNote')}</p>}
                </div>
                <div className="border border-line rounded-sm p-3 min-w-0">
                  <div className="eyebrow mb-1">{t('alerts.pv.title')}</div>
                  <p className="text-sm text-muted mb-2">{t('alerts.pv.hint')}</p>
                  {preview.error ? <Note tone="warn">{errorText(preview.error, lang)}</Note>
                    : pvData ? <PreviewResult pv={pvData} compact />
                    : ready ? <Loading label={t('alerts.pv.loading')} /> : null}
                </div>
              </div>
              {save.error && <div className="mt-3"><Note tone="warn">{errorText(save.error, lang)}</Note></div>}
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" className="btn-primary" disabled={!ready || !name.trim() || save.isPending} onClick={() => save.mutate()}>
                  {save.isPending ? t('alerts.editor.saving') : rule ? t('alerts.editor.saveEdit') : t('alerts.editor.save')}
                </button>
                <button type="button" className="btn-secondary" onClick={onDone}>{t('ui.cancel')}</button>
              </div>
            </section>
          )}
        </div>
      )}
    </Panel>
  )
}
