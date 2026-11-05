// /assistente — questions about the honey market answered from the local database only.
// Each answer lists its facts with source, date, period and status; with an AI provider configured
// the text is written by the AI (post-checked on the server) and its analysis is badged as AI.
// Works from 390 px (phone) to desktop: one column, then the side panels on the right (lg).
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AnswerView } from '@/components/assistant/AnswerView'
import { AskBox, isAboutOffers } from '@/components/assistant/AskBox'
import { AiStatusPanel, BriefingPanel, HistoryPanel, Suggestions } from '@/components/assistant/SidePanels'
import type { Answer, AssistantStatus, BriefingResponse, HistoryResponse } from '@/components/assistant/types'
import { ErrorBlock, Loading, PageHeader, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDateTime } from '@/lib/format'

export interface Turn {
  key: string
  question: string
  pending: boolean
  answer?: Answer
  error?: string
  fromHistory?: boolean
  quoteIds?: number[]
}

export function TurnView({ turn, aiEnabled, onRetry, onRemove }: {
  turn: Turn; aiEnabled: boolean; onRetry: () => void; onRemove: () => void
}) {
  const { t, lang } = useI18n()
  const when = turn.answer?.asked_at
  return (
    <article className="min-w-0 space-y-2" aria-busy={turn.pending}>
      <div className="flex items-start justify-between gap-3 border-l-2 border-gold bg-ivory/60 px-3 py-2 sm:px-4">
        <div className="min-w-0">
          <div className="eyebrow">
            {t('assistant.turn.question')}
            {when && ` · ${fmtDateTime(when, lang)}`}
            {turn.fromHistory && ` · ${t('assistant.turn.fromHistory')}`}
          </div>
          <p className="mt-0.5 break-words font-serif text-[1.12rem] font-semibold leading-snug text-charcoal">{turn.question}</p>
        </div>
        {!turn.pending && (
          <button type="button" onClick={onRemove} className="mt-0.5 shrink-0 text-muted hover:text-charcoal"
            title={t('assistant.turn.remove')} aria-label={t('assistant.turn.remove')}>
            <X size={16} />
          </button>
        )}
      </div>
      <div className="panel p-4 sm:p-5">
        {turn.pending ? <Loading label={aiEnabled ? t('assistant.ask.pendingAi') : t('assistant.ask.pending')} />
          : turn.error ? <ErrorBlock error={new Error(`${t('assistant.ask.error')} ${turn.error}`)} onRetry={onRetry} />
            : turn.answer ? <AnswerView answer={turn.answer} /> : null}
      </div>
    </article>
  )
}

export default function Assistant() {
  const { t, lang } = useI18n()
  const qc = useQueryClient()
  const status = useQuery({ queryKey: ['assistant', 'status'], queryFn: () => api.get<AssistantStatus>('/assistant/status') })
  const history = useQuery({ queryKey: ['assistant', 'history'], queryFn: () => api.get<HistoryResponse>('/assistant/history') })
  const aiEnabled = Boolean(status.data?.llm_enabled)
  const briefing = useQuery({
    queryKey: ['assistant', 'briefing', lang],
    queryFn: () => api.get<BriefingResponse>('/assistant/briefing', { lang }),
    enabled: aiEnabled,
  })
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [quoteIds, setQuoteIds] = useState<number[]>([])
  const [clearing, setClearing] = useState(false)
  const pending = turns.some((x) => x.pending)
  const lastRef = useRef<HTMLDivElement>(null)

  const update = (key: string, patch: Partial<Turn>) =>
    setTurns((ts) => ts.map((x) => (x.key === key ? { ...x, ...patch } : x)))

  const send = (key: string, question: string, ids: number[]) => {
    api.post<Answer>('/assistant/ask', { question, lang, quote_ids: ids.length ? ids : undefined })
      .then((answer) => update(key, { answer, pending: false, error: undefined }))
      .catch((e: unknown) => update(key, { error: e instanceof Error ? e.message : String(e), pending: false }))
      .finally(() => qc.invalidateQueries({ queryKey: ['assistant', 'history'] }))
  }

  const ask = (text: string) => {
    const question = text.trim()
    if (!question || pending) return
    const ids = isAboutOffers(question) ? quoteIds : []
    const key = `${Date.now()}-${turns.length}`
    setTurns((ts) => [...ts, { key, question, pending: true, quoteIds: ids }])
    setDraft('')
    setQuoteIds([])
    send(key, question, ids)
  }

  const retry = (turn: Turn) => {
    update(turn.key, { pending: true, error: undefined })
    send(turn.key, turn.question, turn.quoteIds ?? [])
  }

  const openHistory = (id: string) => {
    const key = `h-${id}-${Date.now()}`
    api.get<Answer>(`/assistant/history/${id}`).then((answer) =>
      setTurns((ts) => [...ts, { key, question: answer.question, pending: false, answer, fromHistory: true }]))
      .catch(() => qc.invalidateQueries({ queryKey: ['assistant', 'history'] }))
  }

  const clearHistory = () => {
    if (!window.confirm(t('assistant.history.confirm'))) return
    setClearing(true)
    api.del('/assistant/history').finally(() => {
      setClearing(false)
      qc.invalidateQueries({ queryKey: ['assistant'] })
    })
  }

  // /assistente?q=... asks the question once (links from other pages).
  const [params, setParams] = useSearchParams()
  const linked = useRef(false)
  useEffect(() => {
    const q = params.get('q')
    if (q && !linked.current) {
      linked.current = true
      ask(q)
      setParams({}, { replace: true })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (turns.length) lastRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [turns.length])

  return (
    <div className="min-w-0">
      <PageHeader eyebrow={t('assistant.eyebrow')} title={t('assistant.title')} subtitle={t('assistant.subtitle')} />

      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_20rem] xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-5">
          {turns.length === 0 && (
            <Panel>
              <h2 className="font-serif text-[1.3rem] font-semibold">{t('assistant.welcome.title')}</h2>
              <p className="mb-4 mt-1 max-w-3xl text-[0.95rem] text-muted">{t('assistant.welcome.text')}</p>
              <div className="eyebrow mb-2">{t('assistant.suggest.title')}</div>
              <Suggestions onPick={ask} disabled={pending} />
            </Panel>
          )}
          {turns.map((turn, i) => (
            <div key={turn.key} ref={i === turns.length - 1 ? lastRef : undefined} className="min-w-0 scroll-mt-24">
              <TurnView turn={turn} aiEnabled={aiEnabled} onRetry={() => retry(turn)}
                onRemove={() => setTurns((ts) => ts.filter((x) => x.key !== turn.key))} />
            </div>
          ))}
          <AskBox value={draft} onChange={setDraft} onSubmit={() => ask(draft)} pending={pending} aiEnabled={aiEnabled}
            quoteIds={quoteIds} onQuoteIds={setQuoteIds} />
        </div>

        <aside className="min-w-0 space-y-5">
          {status.isLoading ? <Loading /> : status.error ? <ErrorBlock error={status.error} onRetry={() => status.refetch()} />
            : status.data && <AiStatusPanel status={status.data} />}
          {turns.length > 0 && (
            <Panel title={t('assistant.suggest.title')}>
              <Suggestions compact onPick={ask} disabled={pending} />
            </Panel>
          )}
          <HistoryPanel items={history.data?.items ?? []} onOpen={openHistory} onClear={clearHistory} busy={clearing} />
          {status.data && <BriefingPanel status={status.data} briefing={briefing.data} />}
        </aside>
      </div>
    </div>
  )
}
