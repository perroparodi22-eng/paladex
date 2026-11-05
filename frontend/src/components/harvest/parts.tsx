// Shared pieces of /raccolti: the reading guide (data vs estimates vs automatic assessments vs
// context), condition badges, flag explanations, the weather-collection note and the NASA citation.
import clsx from 'clsx'
import { AlertTriangle, BookOpen, CloudSun, Cpu, Database, Loader2, Sigma } from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge, Note, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtPeriod } from '@/lib/format'
import { CONDITION_COLORS, fmtFlagValues, fmtMonthRun } from './format'
import type { Condition, Flag, WeatherMeta } from './types'

/** The five kinds of content on the page, each with the mark used for it. */
export function ReadingGuide() {
  const { t } = useI18n()
  const items: { icon: ReactNode; title: string; hint: string; mark: ReactNode }[] = [
    { icon: <Database size={16} />, title: t('harvest.legend.data'), hint: t('harvest.legend.dataHint'),
      mark: <span className="inline-block h-3 w-5 rounded-[1px] bg-forest-600" /> },
    { icon: <Sigma size={16} />, title: t('harvest.legend.estimate'), hint: t('harvest.legend.estimateHint'),
      mark: <span className="inline-block h-3 w-5 rounded-[1px] border border-gold-dark bg-gold-light" /> },
    { icon: <CloudSun size={16} />, title: t('harvest.legend.weather'), hint: t('harvest.legend.weatherHint'),
      mark: <span className="num text-[0.78rem] text-charcoal-soft">+2,1 °C · 45%</span> },
    { icon: <Cpu size={16} />, title: t('harvest.legend.assessment'), hint: t('harvest.legend.assessmentHint'),
      mark: <AssessmentMark /> },
    { icon: <BookOpen size={16} />, title: t('harvest.legend.context'), hint: t('harvest.legend.contextHint'),
      mark: <Badge tone="outline">{t('harvest.table.contextShort')}</Badge> },
  ]
  return (
    <Panel title={t('harvest.legend.title')} bodyClassName="!py-4">
      <ul className="grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-5">
        {items.map((it) => (
          <li key={it.title} className="flex min-w-0 gap-2.5">
            <span className="mt-0.5 shrink-0 text-gold-dark">{it.icon}</span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2 font-medium text-charcoal">{it.title} {it.mark}</div>
              <p className="mt-0.5 text-[0.85rem] leading-snug text-muted">{it.hint}</p>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

/** The label every automatic assessment carries. */
export function AssessmentMark({ className }: { className?: string }) {
  const { t } = useI18n()
  return (
    <Badge tone="ai" className={className} title={t('harvest.legend.assessmentHint')}>
      <Cpu size={11} /> {t('harvest.legend.assessment')}
    </Badge>
  )
}

export function ConditionDot({ condition, hollow = false, size = 12 }: { condition: Condition; hollow?: boolean; size?: number }) {
  const c = CONDITION_COLORS[condition]
  return (
    <span aria-hidden className="inline-block shrink-0 rounded-full"
      style={{ width: size, height: size, background: hollow ? '#fff' : c, border: `2.5px solid ${c}` }} />
  )
}

export function ConditionBadge({ condition, recent = true }: { condition: Condition; recent?: boolean }) {
  const { t } = useI18n()
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[0.85rem] font-medium text-charcoal-soft">
      <ConditionDot condition={condition} hollow={!recent && condition !== 'normal' && condition !== 'no_data'} />
      {t(`harvest.cond.${condition}`)}
    </span>
  )
}

/** "Siccità da monitorare — Pioggia al 41% e 53% della normale in mar–apr 2026, mesi di fioritura." */
export function FlagLine({ flag }: { flag: Flag }) {
  const { t, lang } = useI18n()
  return (
    <div className="flex min-w-0 items-start gap-2">
      <span className="mt-1"><ConditionDot condition={flag.rule} hollow={!flag.recent} size={10} /></span>
      <div className="min-w-0 text-[0.86rem] leading-snug">
        <span className="font-medium text-charcoal">{t(`harvest.cond.${flag.rule}`)}</span>{' '}
        <span className="text-muted">({t(flag.recent ? 'harvest.cond.recent' : 'harvest.cond.earlier')})</span>
        <div className="text-charcoal-soft">
          {t(`harvest.flag.${flag.rule}`, { values: fmtFlagValues(flag, lang), months: fmtMonthRun(flag.months, lang) })}
          {flag.data_status === 'provisional' && <span className="text-muted"> {t('harvest.flag.provisional')}</span>}
        </div>
        {flag.exceptional_months.length > 0 && (
          <div className="mt-0.5 flex items-start gap-1 text-[0.8rem] text-warn">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            <span>{t('harvest.flag.exceptional', { months: flag.exceptional_months.map((m) => fmtPeriod(m, lang)).join(', ') })}</span>
          </div>
        )}
      </div>
    </div>
  )
}

/** What the page says when weather rows are missing (first run) or late; production is shown anyway. */
export function WeatherStatusNote({ meta, regionsWithData, regionsTotal }: { meta: WeatherMeta; regionsWithData: number; regionsTotal: number }) {
  const { t, lang } = useI18n()
  const c = meta.collection
  const when = fmtDate(c.last_run_at, lang)
  if (!meta.available) {
    const body = c.state === 'running' ? t('harvest.status.running')
      : c.state === 'failed' ? t('harvest.status.failed', { date: when })
        : c.state === 'offline' ? t('harvest.status.offline', { date: when })
          : t('harvest.status.never')
    return (
      <div role="status" className="flex items-start gap-3 rounded-sm border border-forest-100 bg-forest-50 px-4 py-3 text-forest-800">
        {c.state === 'running' ? <Loader2 size={18} className="mt-0.5 shrink-0 animate-spin" /> : <CloudSun size={18} className="mt-0.5 shrink-0" />}
        <div className="min-w-0">
          <div className="font-serif text-[1.05rem] font-semibold">{t('harvest.status.collectingTitle')}</div>
          <p className="mt-0.5 text-[0.92rem]">{body} {t('harvest.status.productionMeanwhile')}</p>
        </div>
      </div>
    )
  }
  const notes: string[] = []
  if (regionsWithData < regionsTotal) {
    notes.push(c.state === 'running' ? t('harvest.status.partial', { n: regionsWithData, total: regionsTotal })
      : t('harvest.status.someMissing', { n: regionsTotal - regionsWithData, total: regionsTotal }))
  }
  if (meta.behind_expected && meta.latest_period_label) notes.push(t('harvest.status.behind', { month: fmtPeriod(meta.latest_period_label, lang) }))
  if (!notes.length) return null
  return <Note tone="warn">{notes.join(' ')}</Note>
}

/** NASA POWER citation (requested by NASA) and the production credit. */
export function WeatherAttribution({ meta, className }: { meta: WeatherMeta; className?: string }) {
  const { t, lang } = useI18n()
  return (
    <div className={clsx('text-[0.8rem] leading-relaxed text-muted', className)}>
      <span className="font-medium text-charcoal-soft">{t('harvest.cite.title')}:</span>{' '}
      {t('harvest.cite.text', {
        versions: meta.api_versions.length ? meta.api_versions.join(', ') : '',
        date: meta.accessed_at ? fmtDate(meta.accessed_at, lang) : '—',
      })}{' '}
      <span className="text-charcoal-soft">{t('harvest.cite.required')}</span> <q lang="en" className="italic">{meta.citation}</q>{' '}
      <a className="link" href="https://power.larc.nasa.gov/" target="_blank" rel="noreferrer">power.larc.nasa.gov</a>.{' '}
      {t('harvest.cite.faostat')}
    </div>
  )
}
