// Suggested questions, previous questions, AI status (and how to enable it) and the daily AI briefing.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { MessageSquareText, RefreshCw, Sparkles, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AiBadge, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate, fmtDateTime } from '@/lib/format'
import { HowToEnableBox } from './AnswerView'
import type { AssistantStatus, BriefingResponse, HistoryItem, RegenerateResponse } from './types'

export const SUGGESTION_KEYS = ['q1', 'q2', 'q3', 'q4', 'q5', 'q6', 'q7', 'q8'] as const

export function Suggestions({ onPick, disabled, compact = false }: { onPick: (q: string) => void; disabled?: boolean; compact?: boolean }) {
  const { t } = useI18n()
  return (
    <ul className={clsx('grid gap-2', !compact && 'sm:grid-cols-2')}>
      {SUGGESTION_KEYS.map((k) => {
        const q = t(`assistant.suggest.${k}`)
        return (
          <li key={k} className="min-w-0">
            <button type="button" onClick={() => onPick(q)} disabled={disabled}
              className="flex w-full items-start gap-2 rounded-sm border border-line bg-white px-3 py-2 text-left text-[0.92rem] leading-snug text-charcoal-soft transition-colors hover:border-forest-600 hover:bg-forest-50 hover:text-forest-900 disabled:opacity-50">
              <MessageSquareText size={15} className="mt-[0.2rem] shrink-0 text-gold-dark" />
              <span className="min-w-0 break-words">{q}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

export function HistoryPanel({ items, onOpen, onClear, busy }: {
  items: HistoryItem[]; onOpen: (id: string) => void; onClear: () => void; busy?: boolean
}) {
  const { t, lang } = useI18n()
  return (
    <Panel title={t('assistant.history.title')} bodyClassName="p-0"
      footer={items.length > 0 ? (
        <button type="button" className="inline-flex items-center gap-1.5 hover:text-down disabled:opacity-50" onClick={onClear} disabled={busy}>
          <Trash2 size={13} /> {t('assistant.history.clear')}
        </button>
      ) : undefined}>
      {items.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted">{t('assistant.history.empty')}</p>
      ) : (
        <ul className="max-h-[22rem] divide-y divide-line-soft overflow-y-auto">
          {items.map((h) => (
            <li key={h.id}>
              <button type="button" onClick={() => onOpen(h.id)}
                className="block w-full px-5 py-2.5 text-left hover:bg-ivory/60">
                <span className="line-clamp-2 break-words text-[0.92rem] text-charcoal">{h.question}</span>
                <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[0.75rem] text-muted">
                  <span>{fmtDateTime(h.asked_at, lang)}</span>
                  <span>· {h.facts ? t('assistant.history.facts', { n: h.facts }) : t('assistant.history.noFacts')}</span>
                  {h.ai_used && <AiBadge label={t('assistant.history.ai')} />}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

export function AiStatusPanel({ status }: { status: AssistantStatus }) {
  const { t, lang } = useI18n()
  return (
    <Panel>
      <div className="flex items-start gap-2.5">
        <Sparkles size={18} className={clsx('mt-0.5 shrink-0', status.llm_enabled ? 'text-[#4B3F7A]' : 'text-muted')} />
        <div className="min-w-0 space-y-2 text-[0.9rem] text-charcoal-soft">
          <div className="font-medium text-charcoal">{status.llm_enabled ? t('assistant.ai.on') : t('assistant.ai.off')}</div>
          {status.llm_enabled
            ? <p>{t('assistant.ai.onText', { provider: status.provider ?? '', model: status.model ?? '' })}</p>
            : (
              <>
                <p>{t('assistant.ai.offText')}</p>
                {status.key_missing && <p className="text-warn">{t('assistant.ai.keyMissing')}</p>}
                <HowToEnableBox how={status.how_to_enable[lang]} title={t('assistant.ai.howTo')} />
              </>
            )}
        </div>
      </div>
    </Panel>
  )
}

export function BriefingPanel({ status, briefing }: { status: AssistantStatus; briefing: BriefingResponse | undefined }) {
  const { t, lang } = useI18n()
  const qc = useQueryClient()
  const [message, setMessage] = useState<string | null>(null)
  const regen = useMutation({
    mutationFn: () => api.post<RegenerateResponse>('/assistant/briefing/regenerate', {}),
    onSuccess: (r) => {
      const mine = r.results[lang]
      setMessage(mine?.status === 'generated' ? t('assistant.briefing.done')
        : t('assistant.briefing.notDone', { reason: t(`assistant.briefing.reason.${mine?.status ?? 'error'}`) }))
      qc.invalidateQueries({ queryKey: ['assistant'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
    },
    onError: () => setMessage(t('assistant.briefing.notDone', { reason: t('assistant.briefing.reason.error') })),
  })
  const stored = briefing?.briefing
  const time = (iso: string) => fmtDate(iso, lang, { hour: '2-digit', minute: '2-digit' })
  return (
    <Panel title={t('assistant.briefing.title')}>
      <div className="space-y-2.5 text-[0.9rem] text-charcoal-soft">
        {!status.llm_enabled ? (
          <p>{t('assistant.briefing.off')}</p>
        ) : stored ? (
          <p>{t('assistant.briefing.aiStored', { date: fmtDate(stored.generated_at, lang), time: time(stored.generated_at), model: stored.generator, n: stored.bullets.length })}</p>
        ) : (
          <p>{t('assistant.briefing.aiNone', { time: status.briefing.schedule })}</p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {status.llm_enabled && (
            <button type="button" className="btn-secondary !py-1.5 text-sm" onClick={() => regen.mutate()} disabled={regen.isPending}>
              <RefreshCw size={14} className={clsx(regen.isPending && 'animate-spin')} />
              {regen.isPending ? t('assistant.briefing.running') : stored ? t('assistant.briefing.regenerate') : t('assistant.briefing.generate')}
            </button>
          )}
          <Link to="/" className="text-sm text-forest-700 hover:text-forest-900">{t('assistant.briefing.open')} →</Link>
        </div>
        {message && <p className="text-[0.82rem] text-muted">{message}</p>}
      </div>
    </Panel>
  )
}
