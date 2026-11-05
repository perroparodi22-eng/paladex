// /fonti — "Fonti e qualità dei dati": written for a non-technical reader. Which sources feed the
// app, how current each one is, what went wrong (in plain words), what to double-check, demo data.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { DemoPanel } from '@/components/sources/DemoPanel'
import { QualityPanel } from '@/components/sources/QualityPanel'
import { SourceGroups, type RowState } from '@/components/sources/SourceGroups'
import { SourcesSummary } from '@/components/sources/SourcesSummary'
import type { ApiKeyInfo, QualityIssues, QualitySummary, SourcesList } from '@/components/sources/types'
import { Notice } from '@/components/sources/widgets'
import { ErrorBlock, Loading, PageHeader } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { isMirror } from '@/lib/mirror'
import type { CollectState, SourceInfo } from '@/lib/types'

type NoticeT = { tone: 'ok' | 'warn'; text: string } | null

export default function Sources() {
  const { t } = useI18n()
  const qc = useQueryClient()
  const location = useLocation()
  const [notice, setNotice] = useState<NoticeT>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [highlighted, setHighlighted] = useState<string | null>(null)

  const collect = useQuery({
    queryKey: ['collect-status'],
    queryFn: () => api.get<CollectState>('/collect/status'),
    refetchInterval: (query) => (query.state.data?.running ? 3000 : 30000),
  })
  const running = collect.data?.running ?? false
  const sources = useQuery({
    queryKey: ['sources'],
    queryFn: () => api.get<SourcesList>('/sources'),
    refetchInterval: running ? 5000 : 60000,
  })
  const summary = useQuery({
    queryKey: ['quality-summary'],
    queryFn: () => api.get<QualitySummary>('/quality/summary'),
    refetchInterval: running ? 5000 : 60000,
  })
  const keys = useQuery({ queryKey: ['quality-keys'], queryFn: () => api.get<{ keys: ApiKeyInfo[] }>('/quality/keys'), staleTime: 5 * 60_000 })
  const failures = useQuery({
    queryKey: ['quality-issues', 'collection_failed'],
    queryFn: () => api.get<QualityIssues>('/quality/issues', { status: 'open', type: 'collection_failed' }),
  })

  // When a collection finishes, refresh everything on this page (new runs, freshness, quality).
  const [wasRunning, setWasRunning] = useState(false)
  useEffect(() => {
    if (wasRunning && !running) {
      qc.invalidateQueries({ queryKey: ['sources'] })
      qc.invalidateQueries({ queryKey: ['quality-summary'] })
      qc.invalidateQueries({ queryKey: ['quality-issues'] })
      qc.invalidateQueries({ queryKey: ['source-runs'] })
    }
    setWasRunning(running)
  }, [running, wasRunning, qc])

  const startCollect = useMutation({
    mutationFn: (keys: string[] | null) => api.post<{ started: boolean }>('/collect', keys ? { keys } : {}),
    onSuccess: (r, keysArg) => {
      if (!r.started) setNotice({ tone: 'warn', text: t('sources.row.busy') })
      else if (keysArg?.length === 1) {
        const name = sources.data?.sources.find((s) => s.key === keysArg[0])?.name ?? keysArg[0]
        setNotice({ tone: 'ok', text: t('sources.row.startedOk', { name }) })
      }
      qc.invalidateQueries({ queryKey: ['collect-status'] })
    },
    onError: (e) => setNotice({ tone: 'warn', text: e instanceof Error ? e.message : String(e) }),
  })
  const toggle = useMutation({
    mutationFn: ({ s, enabled }: { s: SourceInfo; enabled: boolean }) => api.put<SourceInfo>(`/sources/${encodeURIComponent(s.key)}`, { enabled }),
    onSuccess: (_r, { s, enabled }) => {
      setNotice({ tone: 'ok', text: t(enabled ? 'sources.row.toggledOn' : 'sources.row.toggledOff', { name: s.name }) })
      qc.invalidateQueries({ queryKey: ['sources'] })
      qc.invalidateQueries({ queryKey: ['quality-summary'] })
    },
    onError: (e) => setNotice({ tone: 'warn', text: e instanceof Error ? e.message : String(e) }),
  })

  // Deep links such as /fonti#usda_honey (from data-quality issues and search) mark the row,
  // reveal it if its group is collapsed, then scroll to it once rendered.
  const list = sources.data?.sources
  useEffect(() => {
    const key = decodeURIComponent(location.hash.replace(/^#/, ''))
    if (!key || !list) return
    if (list.some((s) => s.key === key)) setHighlighted(key)
    else document.getElementById(key)?.scrollIntoView({ block: 'start' })
  }, [location.hash, location.key, list])
  useEffect(() => {
    if (highlighted) document.getElementById(`src-${highlighted}`)?.scrollIntoView({ block: 'start' })
  }, [highlighted, location.key])

  const toggleExpanded = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const lastErrors = useMemo(() => {
    const m = new Map<string, string>()
    for (const i of failures.data?.issues ?? []) {
      const key = i.details.source_key as string | undefined
      if (key) m.set(key, String(i.details.error ?? ''))
    }
    return m
  }, [failures.data])

  const rowState: RowState = {
    expanded,
    toggleExpanded,
    highlighted,
    runningKeys: collect.data?.keys ?? null,
    collectRunning: running,
    pendingKey: startCollect.isPending ? (startCollect.variables?.[0] ?? null) : null,
    onUpdate: (s) => startCollect.mutate([s.key]),
    onToggle: (s, enabled) => toggle.mutate({ s, enabled }),
    keyInfo: (attr) => keys.data?.keys.find((k) => k.setting === attr),
    lastError: (key) => lastErrors.get(key),
  }

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={t('sources.eyebrow')} title={t('sources.title')} subtitle={t('sources.subtitle')} />
      <Notice notice={notice} onClose={() => setNotice(null)} />

      {summary.isLoading || sources.isLoading ? <Loading /> : summary.error || sources.error ? (
        <ErrorBlock error={summary.error ?? sources.error} onRetry={() => { summary.refetch(); sources.refetch() }} />
      ) : summary.data && list ? (
        <SourcesSummary
          summary={summary.data}
          sources={list}
          collect={collect.data}
          onUpdateAll={() => startCollect.mutate(null)}
          starting={startCollect.isPending}
        />
      ) : null}

      <QualityPanel onNotice={setNotice} />

      {list && <SourceGroups sources={list} state={rowState} />}

      {summary.data && !isMirror() && <DemoPanel demo={summary.data.demo} onNotice={setNotice} />}
    </div>
  )
}
