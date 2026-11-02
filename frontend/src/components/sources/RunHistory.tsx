// Expandable list of the latest collection runs for one source, in plain language,
// with the technical error text kept behind "Dettagli tecnici".
import { useQuery } from '@tanstack/react-query'
import { Badge, ErrorBlock, Loading } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDateTime, fmtNumber } from '@/lib/format'
import { runExplanationKey, runTone } from './explain'
import type { CollectionRunInfo, SourceRuns } from './types'

export function RunHistory({ sourceKey }: { sourceKey: string }) {
  const { t } = useI18n()
  const q = useQuery({
    queryKey: ['source-runs', sourceKey],
    queryFn: () => api.get<SourceRuns>(`/sources/${encodeURIComponent(sourceKey)}/runs`, { limit: 15 }),
  })
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
  const runs = q.data?.runs ?? []
  return (
    <div>
      <h3 className="eyebrow mb-2">{t('sources.runs.title')}</h3>
      {runs.length === 0 ? (
        <p className="text-muted text-[0.95rem]">{t('sources.runs.empty')}</p>
      ) : (
        <ol className="divide-y divide-line-soft border border-line-soft rounded-sm bg-white">
          {runs.map((r) => <RunItem key={r.id} run={r} />)}
        </ol>
      )}
    </div>
  )
}

function RunItem({ run }: { run: CollectionRunInfo }) {
  const { t, lang } = useI18n()
  const hasTech = Boolean(run.error) || (run.warnings?.length ?? 0) > 0
  const trigger = t(`sources.runs.trigger.${run.trigger}`)
  return (
    <li className="px-4 py-3 grid gap-x-5 gap-y-1 grid-cols-1 md:grid-cols-[11.5rem_minmax(0,1fr)_auto] items-start">
      <div className="text-[0.92rem]">
        <div className="num text-charcoal">{fmtDateTime(run.started_at, lang)}</div>
        <div className="text-[0.8rem] text-muted">{trigger.startsWith('sources.') ? run.trigger : trigger}</div>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={runTone(run.status)}>{t(`status.${run.status}`)}</Badge>
          <span className="text-[0.95rem] text-charcoal-soft">{t(runExplanationKey(run.status, run.error))}</span>
        </div>
        {hasTech && (
          <details className="mt-1.5 group">
            <summary className="cursor-pointer text-[0.82rem] text-muted hover:text-charcoal-soft select-none">
              {t('sources.runs.technical')}
              {run.warnings?.length ? ` · ${t('sources.runs.warnings', { n: run.warnings.length })}` : ''}
            </summary>
            <div className="mt-1.5 space-y-1.5">
              {run.error && (
                <pre className="num whitespace-pre-wrap break-words text-[0.78rem] leading-relaxed text-charcoal-soft bg-paper border border-line-soft rounded-sm px-3 py-2 max-h-56 overflow-auto">{run.error}</pre>
              )}
              {run.warnings && run.warnings.length > 0 && (
                <ul className="num text-[0.78rem] text-charcoal-soft bg-paper border border-line-soft rounded-sm px-3 py-2 max-h-56 overflow-auto list-disc pl-6">
                  {run.warnings.map((w, i) => <li key={i} className="break-words">{w}</li>)}
                </ul>
              )}
            </div>
          </details>
        )}
      </div>
      <div className="text-[0.85rem] text-muted md:text-right whitespace-nowrap">
        {run.status !== 'offline' && run.status !== 'skipped' && (
          <>
            <div className="num">{t('sources.runs.newRevised', { n: fmtNumber(run.items_new, lang), r: fmtNumber(run.items_revised, lang) })}</div>
            <div className="num text-[0.78rem]">{t('sources.runs.seen', { n: fmtNumber(run.items_seen, lang) })}</div>
          </>
        )}
      </div>
    </li>
  )
}
