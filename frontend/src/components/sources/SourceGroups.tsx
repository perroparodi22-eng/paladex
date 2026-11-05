// Sources grouped by category (Prezzi, Commercio, Produzione, Notizie, Normative, Cambi...).
// Each row: who publishes it, what it provides, newest published data, last check, actions.
import clsx from 'clsx'
import { useState } from 'react'
import { ChevronDown, ExternalLink, Loader2, RefreshCw } from 'lucide-react'
import { Badge, FreshnessBadge, ReliabilityBadge } from '@/components/ui'
import { expectedUpdate, useI18n } from '@/i18n'
import { fmtAgo, fmtDate, fmtDateTime, fmtNumber, fmtPeriod } from '@/lib/format'
import { isMirror } from '@/lib/mirror'
import type { Lang, SourceInfo } from '@/lib/types'
import { asUtc, errorKey, runTone } from './explain'
import { KeyHelp } from './KeyHelp'
import { RunHistory } from './RunHistory'
import type { ApiKeyInfo } from './types'
import { Switch } from './widgets'

const GROUP_ORDER = ['prices', 'trade', 'production', 'reports', 'news', 'regulation', 'weather', 'fx', 'quotes', 'other']
const COUNT_KEYS = ['prices', 'trade', 'production', 'news', 'reports', 'regulations'] as const

export function groupOf(s: SourceInfo): string {
  return GROUP_ORDER.includes(s.category) ? s.category : 'other'
}

export interface RowState {
  expanded: Set<string>
  toggleExpanded: (key: string) => void
  highlighted: string | null
  runningKeys: string[] | null   // keys of the collection in progress (null = all)
  collectRunning: boolean
  pendingKey: string | null
  onUpdate: (s: SourceInfo) => void
  onToggle: (s: SourceInfo, enabled: boolean) => void
  keyInfo: (attr: string) => ApiKeyInfo | undefined
  lastError: (key: string) => string | undefined   // technical text of the latest failure, if known
}

const GROUP_VISIBLE = 6

/** "2026-09" -> "set 2026"; "2026-10-30" (daily data) -> "30 ott 2026"; others unchanged. */
function periodText(label: string, lang: Lang): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(label) ? fmtDate(label, lang) : fmtPeriod(label, lang)
}

export function SourceGroups({ sources, state }: { sources: SourceInfo[]; state: RowState }) {
  const groups = GROUP_ORDER.map((g) => ({ g, items: sources.filter((s) => groupOf(s) === g) })).filter((x) => x.items.length)
  return (
    <div id="fonti-elenco" className="space-y-6 scroll-mt-24">
      {groups.map(({ g, items }) => <SourceGroup key={g} group={g} items={items} state={state} />)}
    </div>
  )
}

function SourceGroup({ group, items, state }: { group: string; items: SourceInfo[]; state: RowState }) {
  const { t } = useI18n()
  const [showAll, setShowAll] = useState(false)
  const hiddenHasFocus = items.slice(GROUP_VISIBLE).some((s) => s.key === state.highlighted)
  const all = showAll || hiddenHasFocus || items.length <= GROUP_VISIBLE + 1
  const visible = all ? items : items.slice(0, GROUP_VISIBLE)
  const desc = t(`sources.group.${group}.desc`)
  return (
    <section className="panel" aria-labelledby={`grp-${group}`}>
      <div className="panel-head !py-3.5">
        <div>
          <h2 id={`grp-${group}`} className="panel-title !text-[1.2rem]">{t(`sources.group.${group}`)}</h2>
          {desc && <p className="text-[0.9rem] text-muted mt-0.5">{desc}</p>}
        </div>
        <span className="text-sm text-muted whitespace-nowrap">
          {items.length === 1 ? t('sources.group.countOne') : t('sources.group.count', { n: items.length })}
        </span>
      </div>
      <div className={clsx(group === 'quotes' ? 'hidden' : 'hidden xl:grid', 'grid-cols-[minmax(0,2.3fr)_minmax(0,1fr)_minmax(0,1fr)_12rem] gap-x-6 px-5 py-2 bg-paper border-b border-line-soft eyebrow !text-[0.68rem]')}>
        <span>{t('sources.col.source')}</span>
        <span>{t('sources.col.latest')}</span>
        <span>{t('sources.col.check')}</span>
        <span>{t('sources.col.actions')}</span>
      </div>
      <ul className="divide-y divide-line-soft">
        {visible.map((s) => <SourceRow key={s.key} s={s} state={state} />)}
      </ul>
      {items.length > visible.length || (showAll && items.length > GROUP_VISIBLE + 1) ? (
        <div className="px-5 py-2.5 border-t border-line-soft">
          <button className="btn-ghost !px-2 !py-1.5" onClick={() => setShowAll((x) => !x)} aria-expanded={all}>
            <ChevronDown size={16} className={clsx('transition-transform', all && 'rotate-180')} />
            {all ? t('sources.group.showLess') : t('sources.group.showAll', { n: items.length })}
          </button>
        </div>
      ) : null}
    </section>
  )
}

function SourceRow({ s, state }: { s: SourceInfo; state: RowState }) {
  const { t, lang } = useI18n()
  const manual = s.kind === 'manual'
  const expanded = state.expanded.has(s.key)
  const isRunning = state.collectRunning && (state.runningKeys === null || state.runningKeys.includes(s.key))
  const counts = COUNT_KEYS.filter((k) => (s.counts?.[k] ?? 0) > 0).map((k) => t(`sources.row.counts.${k}`, { n: fmtNumber(s.counts[k], lang) }))
  const keyInfo = s.requires_key ? state.keyInfo(s.requires_key) : undefined
  const optional = keyInfo?.sources.find((x) => x.key === s.key)?.optional ?? false
  const lastError = state.lastError(s.key)

  return (
    <li id={`src-${s.key}`} className={clsx('scroll-mt-24', state.highlighted === s.key ? 'bg-gold-pale/25 shadow-[inset_3px_0_0_#A8873A]' : !s.enabled && 'bg-paper/70')}>
      <div className="grid gap-x-6 gap-y-3 px-5 py-3.5 grid-cols-2 xl:grid-cols-[minmax(0,2.3fr)_minmax(0,1fr)_minmax(0,1fr)_12rem] items-start">
        {/* who / what */}
        <div className="col-span-2 xl:col-span-1 min-w-0">
          <div className={clsx('font-semibold text-[1.05rem] leading-snug', s.enabled ? 'text-charcoal' : 'text-muted')}>
            {s.name}
            {s.homepage && (
              <a href={s.homepage} target="_blank" rel="noreferrer" className="ml-1.5 inline-block align-[-1px] text-muted hover:text-forest-700"
                title={t('sources.row.homepage')} aria-label={`${t('sources.row.homepage')}: ${s.name}`}>
                <ExternalLink size={14} />
              </a>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.88rem] text-muted">
            {s.publisher && <span>{s.publisher}</span>}
            <ReliabilityBadge reliability={s.reliability} />
            {!s.enabled && <Badge tone="outline">{t('sources.row.disabled')}</Badge>}
          </div>
          <div className="mt-1 text-[0.86rem] text-muted leading-snug">
              {expectedUpdate(s, lang) && (
              <>{t('sources.row.expected')}: <span className="text-charcoal-soft">{expectedUpdate(s, lang)}</span>
                {(counts.length > 0 || (s.freshness.status === 'never' && !manual)) && <span className="mx-1.5">·</span>}</>
            )}
            {counts.length ? <span className="num">{counts.join(' · ')}</span>
              : s.freshness.status === 'never' && !manual ? <span>{t('sources.row.counts.none')}</span> : null}
          </div>
        </div>

        {/* newest published data */}
        <div className="min-w-0">
          <div className="eyebrow mb-1 xl:hidden">{t('sources.col.latest')}</div>
          {s.latest_published_at ? (
            <div className="num text-[1rem] text-charcoal">{fmtDate(s.latest_published_at, lang)}</div>
          ) : (
            <div className="text-[0.95rem] text-muted">{manual ? '—' : t('sources.row.noData')}</div>
          )}
          {s.latest_period_label && (
            <div className="text-[0.86rem] text-muted">{t('sources.row.period')}: <span className="text-charcoal-soft">{periodText(s.latest_period_label, lang)}</span></div>
          )}
          {!manual && s.freshness.status !== 'never' && <div className="mt-1.5"><FreshnessBadge status={s.freshness.status} ageDays={s.freshness.age_days} /></div>}
        </div>

        {/* last check */}
        <div className="min-w-0">
          <div className="eyebrow mb-1 xl:hidden">{t('sources.col.check')}</div>
          {manual ? <div className="text-muted">—</div> : isRunning ? (
            <div className="flex items-center gap-1.5 text-forest-800 text-[0.95rem]"><Loader2 size={15} className="animate-spin" /> {t('sources.row.updating')}</div>
          ) : s.last_run_at ? (
            <>
              <div className="text-[1rem] text-charcoal" title={fmtDateTime(asUtc(s.last_run_at), lang)}>{fmtAgo(s.last_run_at, lang)}</div>
              {s.last_run_status && <div className="mt-1.5"><Badge tone={runTone(s.last_run_status)}>{t(`status.${s.last_run_status}`)}</Badge></div>}
              {s.last_run_status === 'failed' && lastError !== undefined && (
                <p className="mt-1.5 text-[0.86rem] leading-snug text-down">{t(errorKey(lastError))}</p>
              )}
            </>
          ) : (
            <div className="text-[0.95rem] text-muted">{t('sources.row.neverChecked')}</div>
          )}
        </div>

        {/* actions (not in the read-only online copy) */}
        {!manual && !isMirror() && (
          <div className="col-span-2 xl:col-span-1 flex flex-wrap items-center gap-x-5 gap-y-2.5">
            <button
              className="btn-secondary !py-1.5 !px-3 justify-center xl:w-full"
              onClick={() => state.onUpdate(s)}
              disabled={!s.enabled || state.collectRunning || state.pendingKey === s.key}
            >
              <RefreshCw size={15} className={clsx(isRunning && 'animate-spin')} />
              {isRunning ? t('sources.row.updating') : t('sources.row.updateNow')}
            </button>
            <div className="flex items-center justify-between gap-4 xl:w-full">
              <Switch checked={s.enabled} onChange={(v) => state.onToggle(s, v)} label={s.enabled ? t('sources.row.enabled') : t('sources.row.disabled')} />
              <button
                className="inline-flex items-center gap-1 text-sm text-forest-700 hover:text-forest-900"
                onClick={() => state.toggleExpanded(s.key)}
                aria-expanded={expanded}
                aria-controls={`runs-${s.key}`}
              >
                <ChevronDown size={16} className={clsx('transition-transform', expanded && 'rotate-180')} />
                {t('sources.row.history')}
              </button>
            </div>
          </div>
        )}
      </div>

      {((s.key_missing && !isMirror()) || !s.enabled || expanded) && (
        <div className="px-5 pb-5 space-y-4">
          {!s.enabled && <p className="text-[0.9rem] text-muted">{t('sources.row.disabledNote')}</p>}
          {s.key_missing && s.requires_key && s.enabled && !isMirror() && <KeyHelp info={keyInfo} settingAttr={s.requires_key} optional={optional} defaultOpen={state.highlighted === s.key} />}
          {expanded && <div id={`runs-${s.key}`}><RunHistory sourceKey={s.key} /></div>}
        </div>
      )}
    </li>
  )
}
