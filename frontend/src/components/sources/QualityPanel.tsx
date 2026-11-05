// Data-quality issues: what to double-check, in plain words, with the numbers behind each check
// and a link to the affected data. Nothing is ever corrected or hidden — only flagged.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertOctagon, AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, Info, Loader2, ShieldCheck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, EmptyState, ErrorBlock, Loading, Segmented } from '@/components/ui'
import { pickLang, useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtAgo, fmtDate, fmtDateTime, fmtNumber, fmtPct, fmtPeriod } from '@/lib/format'
import { isMirror } from '@/lib/mirror'
import type { Lang } from '@/lib/types'
import { asUtc } from './explain'
import type { QualityIssue, QualityIssues, QualityRunResult, Severity } from './types'

const VISIBLE = 6
type SevFilter = 'all' | Severity

export function QualityPanel({ onNotice }: { onNotice: (n: { tone: 'ok' | 'warn'; text: string }) => void }) {
  const { t, lang } = useI18n()
  const qc = useQueryClient()
  const [status, setStatus] = useState<'open' | 'resolved'>('open')
  const [sev, setSev] = useState<SevFilter>('all')
  const [showAll, setShowAll] = useState(false)

  const q = useQuery({
    queryKey: ['quality-issues', status],
    queryFn: () => api.get<QualityIssues>('/quality/issues', { status, limit: 1000 }),
  })
  const run = useMutation({
    mutationFn: () => api.post<QualityRunResult>('/quality/run'),
    onSuccess: (r) => {
      onNotice({ tone: 'ok', text: t('sources.q.rechecked', { n: r.open, new: r.new + r.reopened, res: r.resolved }) })
      qc.invalidateQueries({ queryKey: ['quality-issues'] })
      qc.invalidateQueries({ queryKey: ['quality-summary'] })
    },
    onError: (e) => onNotice({ tone: 'warn', text: e instanceof Error ? e.message : String(e) }),
  })

  const issues = useMemo(() => (q.data?.issues ?? []).filter((i) => sev === 'all' || i.severity === sev), [q.data, sev])
  const counts = q.data?.counts ?? { critical: 0, warning: 0, info: 0 }
  const total = q.data?.total ?? 0
  const shown = showAll ? issues : issues.slice(0, VISIBLE)

  const sevOptions: { value: SevFilter; label: string }[] = [
    { value: 'all', label: `${t('sources.q.all')} · ${fmtNumber(total, lang)}` },
    { value: 'critical', label: `${t('sources.q.sev.critical')} · ${fmtNumber(counts.critical, lang)}` },
    { value: 'warning', label: `${t('sources.q.sev.warning')} · ${fmtNumber(counts.warning, lang)}` },
    { value: 'info', label: `${t('sources.q.sev.info')} · ${fmtNumber(counts.info, lang)}` },
  ]

  return (
    <section id="qualita" className="panel scroll-mt-24" aria-labelledby="quality-title">
      <div className="flex flex-wrap items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-line-soft">
        <div className="max-w-3xl">
          <h2 id="quality-title" className="panel-title !text-[1.3rem] flex items-center gap-2"><ShieldCheck size={20} className="text-forest-700" />{t('sources.q.title')}</h2>
          <p className="mt-1 text-[0.92rem] text-muted leading-relaxed">{t('sources.q.subtitle')}</p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          {!isMirror() && (
            <button className="btn-secondary" onClick={() => run.mutate()} disabled={run.isPending}>
              {run.isPending ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
              {run.isPending ? t('sources.q.rechecking') : t('sources.q.recheck')}
            </button>
          )}
          <span className="text-[0.82rem] text-muted" title={fmtDateTime(asUtc(q.data?.last_check_at), lang)}>
            {q.data?.last_check_at ? t('sources.q.lastCheck', { t: fmtAgo(q.data.last_check_at, lang) }) : t('sources.q.neverChecked')}
          </span>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3 border-b border-line-soft bg-paper">
        <Segmented size="sm" value={sev} onChange={(v) => { setSev(v); setShowAll(false) }} options={sevOptions} />
        <Segmented size="sm" value={status} onChange={(v) => { setStatus(v); setShowAll(false) }}
          options={[{ value: 'open', label: t('sources.q.open') }, { value: 'resolved', label: t('sources.q.resolved') }]} />
      </div>

      {q.isLoading ? <Loading /> : q.error ? <div className="p-5"><ErrorBlock error={q.error} onRetry={() => q.refetch()} /></div> : issues.length === 0 ? (
        <EmptyState
          icon={<CheckCircle2 size={24} className="text-up" />}
          title={status === 'resolved' ? t('sources.q.emptyResolved') : sev !== 'all' ? t('sources.q.emptyFilter') : t('sources.q.empty')}
          hint={status === 'open' && sev === 'all' ? t('sources.q.emptyHint') : ' '}
        />
      ) : (
        <>
          <ul className="divide-y divide-line-soft">
            {shown.map((i) => <IssueItem key={i.id} issue={i} />)}
          </ul>
          {issues.length > VISIBLE && (
            <div className="px-6 py-3 border-t border-line-soft">
              <button className="btn-ghost !px-2" onClick={() => setShowAll((x) => !x)}>
                {showAll ? t('sources.q.showLess') : t('sources.q.showAll', { n: fmtNumber(issues.length, lang) })}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

const SEV_TONE = { critical: 'down', warning: 'warn', info: 'forest' } as const

function SevIcon({ s }: { s: Severity }) {
  if (s === 'critical') return <AlertOctagon size={22} className="text-down" />
  if (s === 'warning') return <AlertTriangle size={22} className="text-warn" />
  return <Info size={22} className="text-forest-600" />
}

function IssueItem({ issue }: { issue: QualityIssue }) {
  const { t, lang } = useI18n()
  const [open, setOpen] = useState(false)
  const d = issue.details
  const isKey = issue.type === 'missing' && Boolean(d.env_var)
  const typeLabel = t(`sources.q.type.${isKey ? 'missing_key' : issue.type}`)
  const message = pickLang(issue as unknown as Record<string, unknown>, 'message', lang)
  const toSource = issue.link?.startsWith('/fonti')
  const sourceName = issue.source?.name ?? (d.values as { source_name?: string }[] | undefined)?.map((v) => v.source_name).filter(Boolean).join(' · ')
  const numbers = issueNumbers(issue, t, lang)
  return (
    <li className={clsx('flex gap-4 px-6 py-4', issue.status === 'resolved' && 'opacity-75')}>
      <div className="pt-0.5 shrink-0"><SevIcon s={issue.severity} /></div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Badge tone={SEV_TONE[issue.severity]}>{t(`sources.q.sev.${issue.severity}`)}</Badge>
          <span className="text-[0.92rem] font-medium text-charcoal-soft">{typeLabel}</span>
          {sourceName && <span className="text-[0.88rem] text-muted">· {sourceName}</span>}
        </div>
        <p className="mt-1.5 text-[1rem] leading-relaxed text-charcoal">{message}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-[0.85rem] text-muted">
          <span title={fmtDateTime(asUtc(issue.detected_at), lang)}>{t('sources.q.detected', { t: fmtAgo(issue.detected_at, lang) })}</span>
          {issue.resolved_at && <span title={fmtDateTime(asUtc(issue.resolved_at), lang)}>{t('sources.q.resolvedAt', { t: fmtAgo(issue.resolved_at, lang) })}</span>}
          {numbers && (
            <button className="inline-flex items-center gap-1 text-forest-700 hover:text-forest-900" onClick={() => setOpen((x) => !x)} aria-expanded={open}>
              <ChevronDown size={14} className={clsx('transition-transform', open && 'rotate-180')} /> {t('sources.q.numbers')}
            </button>
          )}
          {issue.link && (
            <Link to={issue.link} className="link inline-flex items-center gap-1 font-medium">
              {toSource ? t('sources.q.goToSource') : t('sources.q.goTo')} <ArrowRight size={14} />
            </Link>
          )}
        </div>
        {open && numbers && (
          <div className="mt-2.5 rounded-sm border border-line-soft bg-paper px-4 py-3">
            {numbers.rows.length > 0 && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-[0.9rem] max-w-2xl">
                {numbers.rows.map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted">{k}</dt>
                    <dd className="num text-charcoal">{v}</dd>
                  </div>
                ))}
              </dl>
            )}
            {numbers.extra}
          </div>
        )}
      </div>
    </li>
  )
}

/** The figures behind a check, so every flag can be verified by eye. */
function issueNumbers(issue: QualityIssue, t: (k: string, v?: Record<string, string | number>) => string, lang: Lang):
  { rows: [string, string][]; extra: JSX.Element | null } | null {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const d = issue.details as Record<string, any>
  const n = (v: unknown, digits = 2) => (typeof v === 'number' ? fmtNumber(v, lang, digits) : '—')
  const rows: [string, string][] = []
  let extra: JSX.Element | null = null

  switch (issue.type) {
    case 'outlier':
      rows.push([t('sources.q.d.value'), `${n(d.value)} ${d.unit ?? ''}`], [t('sources.q.d.median'), `${n(d.median)} ${d.unit ?? ''}`],
        [t('sources.q.d.deviation'), fmtPct(d.deviation_pct, lang)])
      if (Array.isArray(d.window)) {
        extra = (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {d.window.map((w: { period: string; value: number }) => (
              <span key={w.period} className="num text-[0.8rem] border border-line-soft rounded-sm px-1.5 py-0.5 bg-paper">
                {fmtPeriod(w.period, lang)} · {n(w.value)}
              </span>
            ))}
            <span className="num text-[0.8rem] border border-warn/40 rounded-sm px-1.5 py-0.5 bg-[#FBF0DC] text-warn">
              {fmtPeriod(d.period, lang)} · {n(d.value)}
            </span>
          </div>
        )
      }
      break
    case 'discrepancy':
      for (const v of (d.values ?? []) as { source_name: string; value: number }[]) rows.push([v.source_name, `${n(v.value)} ${d.unit ?? ''}`])
      rows.push([t('sources.q.d.difference'), fmtPct(d.difference_pct, lang, 1, false)])
      break
    case 'stale':
      rows.push([t('sources.q.d.reference'), fmtDate(d.reference_date, lang)], [t('sources.q.d.age'), t('sources.q.d.days', { n: d.age_days })],
        [t('sources.q.d.expected'), t('sources.q.d.withinDays', { n: d.expected_max_age_days })])
      break
    case 'collection_failed':
      rows.push([t('sources.q.d.failures'), String(d.consecutive_failures ?? '—')])
      if (d.error) extra = <pre className="num mt-2 whitespace-pre-wrap break-words text-[0.78rem] text-charcoal-soft bg-paper border border-line-soft rounded-sm px-3 py-2 max-h-48 overflow-auto">{d.error}</pre>
      break
    case 'missing':
      if (Array.isArray(d.missing_periods)) rows.push([t('sources.q.d.missing'), d.missing_periods.map((p: string) => fmtPeriod(p, lang)).join(', ')])
      break
    case 'parse_warning':
      if (d.unit_value_usd_per_kg != null) {
        rows.push([t('sources.q.d.unitValue'), `${n(d.unit_value_usd_per_kg)} USD/kg`],
          [t('sources.q.d.range'), `${n(d.range_usd_per_kg?.[0])}–${n(d.range_usd_per_kg?.[1], 0)} USD/kg`])
      }
      rows.push([t('sources.q.d.tradeValue'), `${n(d.value, 0)} ${d.currency ?? ''}`], [t('sources.q.d.weight'), `${n(d.net_weight_kg, 0)} kg`])
      break
    default:
      return null
  }
  if (!rows.length && !extra) return null
  return { rows, extra }
}
