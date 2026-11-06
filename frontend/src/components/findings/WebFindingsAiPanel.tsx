// Sources page: the optional weekly AI web search of "Altre fonti (non ufficiali)". Off by default;
// shows the switch, the cap on searches, an honest cost estimate (with the prices used and their date)
// and the usage of the latest runs. Never in the read-only online copy (it changes a setting).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Globe2 } from 'lucide-react'
import { Badge, Note, Panel } from '@/components/ui'
import { Switch } from '@/components/sources/widgets'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate, fmtNumber } from '@/lib/format'
import { isMirror } from '@/lib/mirror'
import type { Lang } from '@/lib/types'
import type { AiRun, AiStatus } from './types'

const CAPS = [5, 10, 20, 40, 60, 100]

function usd(v: number | undefined, lang: Lang, digits = 2): string {
  return v === undefined ? '—' : `${fmtNumber(v, lang, digits)} $`
}

export function WebFindingsAiPanel({ onNotice }: { onNotice?: (n: { tone: 'ok' | 'warn'; text: string }) => void }) {
  const q = useQuery({
    queryKey: ['findings-ai'],
    queryFn: () => api.get<AiStatus>('/findings/ai'),
    enabled: !isMirror(),
  })
  if (isMirror() || !q.data) return null
  return <WebFindingsAiBody s={q.data} onNotice={onNotice} />
}

export function WebFindingsAiBody({ s, onNotice }: { s: AiStatus; onNotice?: (n: { tone: 'ok' | 'warn'; text: string }) => void }) {
  const { t, lang } = useI18n()
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: (body: { enabled?: boolean; max_searches?: number }) => api.put<AiStatus>('/findings/ai', body),
    onSuccess: (r) => { qc.setQueryData(['findings-ai'], r); onNotice?.({ tone: 'ok', text: t('findings.ai.saved') }) },
    onError: (e) => onNotice?.({ tone: 'warn', text: e instanceof Error ? e.message : String(e) }),
  })
  const e = s.estimate
  const caps = CAPS.includes(s.max_searches) ? CAPS : [...CAPS, s.max_searches].sort((a, b) => a - b)
  const blocked = s.unavailable !== null
  return (
    <Panel
      title={<span className="inline-flex items-center gap-2"><Globe2 size={17} className="text-gold-dark" />{t('findings.ai.title')}</span>}
      eyebrow={t('findings.ai.eyebrow')}
      actions={<Badge tone={s.enabled ? 'forest' : 'outline'}>{s.enabled ? t('findings.ai.on') : t('findings.ai.off')}</Badge>}
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] items-start text-[0.92rem] text-charcoal-soft">
        <div className="space-y-2.5">
          <p className="leading-relaxed">{t('findings.ai.what')}</p>
          <p className="text-[0.85rem] text-muted">{t('findings.ai.private')}</p>
          <p className="text-[0.85rem] text-muted">{t('findings.ai.onlyAnthropic')}</p>
          {s.unavailable === 'no_key' && <Note tone="warn">{t('findings.ai.noKey')}</Note>}
          {s.unavailable === 'provider_not_supported' && <Note tone="warn">{t('findings.ai.openai')}</Note>}
          {s.enabled_by === 'env' && <p className="text-[0.85rem] text-muted">{t('findings.ai.envOn')}</p>}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3 pt-1">
            <Switch
              checked={s.enabled}
              label={t('findings.ai.switch')}
              disabled={save.isPending || (blocked && !s.enabled)}
              onChange={(v) => save.mutate({ enabled: v })}
            />
            <label className="inline-flex items-center gap-2">
              <span>{t('findings.ai.cap')}</span>
              <select className="field !w-auto !py-1" value={s.max_searches} disabled={save.isPending}
                onChange={(ev) => save.mutate({ max_searches: Number(ev.target.value) })}>
                {caps.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          </div>
          <p className="text-[0.82rem] text-muted">{t('findings.ai.capHint', { n: s.searches_per_country })}</p>
        </div>
        <div className="rounded-sm border border-line-soft bg-paper px-4 py-3.5 space-y-2">
          <div className="eyebrow">{t('findings.ai.costTitle')}</div>
          {e.known ? (
            <>
              <div className="num text-charcoal">{t('findings.ai.costRun', { usd: usd(e.per_run_usd, lang), n: e.max_searches })}</div>
              <div className="num text-charcoal">{t('findings.ai.costMonth', { usd: usd(e.per_month_usd, lang) })}</div>
              <p className="text-[0.8rem] text-muted">
                {t('findings.ai.prices', {
                  d: fmtDate(e.prices_checked_on, lang), ws: usd(e.web_search_usd_per_1000, lang, 0), m: e.model_label ?? e.model,
                  in: usd(e.input_usd_per_mtok, lang), out: usd(e.output_usd_per_mtok, lang),
                })}
                {e.long_context && <> {t('findings.ai.pricesLong', {
                  n: fmtNumber(e.long_context.over, lang), in: usd(e.long_context.input, lang), out: usd(e.long_context.output, lang),
                })}</>}
              </p>
              <p className="text-[0.8rem] text-muted">
                {t('findings.ai.assume', {
                  in: fmtNumber(e.assumed_input_tokens_per_search, lang), out: fmtNumber(e.assumed_output_tokens_per_search, lang),
                  r: fmtNumber(e.runs_per_month, lang, 2),
                })}{' '}
                <a href={e.prices_source} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">
                  {t('findings.ai.pricesSource')} <ExternalLink size={11} />
                </a>
              </p>
            </>
          ) : <p className="text-[0.85rem]">{t('findings.ai.costUnknown', { m: e.model })}</p>}
          <div className="eyebrow pt-1">{t('findings.ai.runs')}</div>
          {s.runs.length === 0 ? <p className="text-[0.82rem] text-muted">{t('findings.ai.noRuns')}</p> : (
            <ul className="space-y-1 text-[0.82rem]">
              {s.runs.map((r) => <RunLine key={r.at} r={r} />)}
            </ul>
          )}
        </div>
      </div>
    </Panel>
  )
}

function RunLine({ r }: { r: AiRun }) {
  const { t, lang } = useI18n()
  const d = fmtDate(r.at, lang)
  if (r.skipped) {
    return <li className="text-muted">{t('findings.ai.runSkipped', { d, why: r.skipped === 'no_key' ? t('findings.ai.noKey') : t('findings.ai.openai') })}</li>
  }
  return (
    <li>
      <span className="num">{t('findings.ai.runLine', {
        d, s: r.searches ?? 0, c: r.cost_known === false ? '—' : usd(r.cost_usd, lang, 3), k: r.countries?.length ?? 0,
        ok: r.stored ?? 0, p: r.proposed ?? 0,
      })}</span>
      {r.error && <div className="text-down">{t('findings.ai.runError', { e: r.error })}</div>}
    </li>
  )
}
