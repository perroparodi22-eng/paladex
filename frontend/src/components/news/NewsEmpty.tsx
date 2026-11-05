// Honest empty states for /notizie: nothing collected yet (feeds fill it on the next update),
// or nothing matching the current filters.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Loader2, Newspaper, RefreshCw, SearchX } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Note } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtAgo } from '@/lib/format'
import { isMirror } from '@/lib/mirror'
import type { CollectState, SourceInfo } from '@/lib/types'
import { utc } from './bits'
import type { NewsListResponse } from './types'

export function NoNewsYet({ updated, newsSources }: { updated: NewsListResponse['updated']; newsSources: SourceInfo[] }) {
  const { t, lang } = useI18n()
  const qc = useQueryClient()
  const [notice, setNotice] = useState<{ tone: 'info' | 'warn'; text: string } | null>(null)
  const collect = useQuery({
    queryKey: ['collect-status'],
    queryFn: () => api.get<CollectState>('/collect/status'),
    refetchInterval: (query) => (query.state.data?.running ? 3000 : 30000),
  })
  const running = collect.data?.running ?? false
  const keys = newsSources.filter((s) => s.enabled).map((s) => s.key)

  const start = useMutation({
    mutationFn: () => api.post<{ started: boolean }>('/collect', { keys }),
    onSuccess: (r) => {
      setNotice(r.started ? { tone: 'info', text: t('news.empty.none.started') } : { tone: 'warn', text: t('news.empty.none.busy') })
      qc.invalidateQueries({ queryKey: ['collect-status'] })
    },
    onError: (e) => setNotice({ tone: 'warn', text: e instanceof Error ? e.message : String(e) }),
  })

  const total = updated.sources_total || newsSources.length
  return (
    <section className="panel">
      <div className="flex flex-col items-center px-8 py-14 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full border border-gold-light/60 bg-gold-pale/60 text-gold-dark">
          <Newspaper size={26} />
        </div>
        <h2 className="mt-5 font-serif text-[1.6rem] font-semibold text-charcoal">{t('news.empty.none.title')}</h2>
        <p className="mt-3 max-w-2xl text-[1.02rem] leading-relaxed text-charcoal-soft">{t('news.empty.none.body', { n: total })}</p>
        <p className="mt-2 max-w-2xl text-[1.02rem] leading-relaxed text-charcoal-soft">
          {updated.last_checked_at
            ? t('news.empty.none.checked', { ago: fmtAgo(utc(updated.last_checked_at), lang) })
            : t('news.empty.none.never')}
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          {keys.length > 0 && !isMirror() && (
            <button type="button" className="btn-primary" onClick={() => start.mutate()} disabled={running || start.isPending}>
              {running || start.isPending ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
              {running ? t('news.empty.none.updating') : t('news.empty.none.update')}
            </button>
          )}
          <Link to="/fonti" className="btn-secondary">
            {t('news.empty.none.sources')} <ArrowRight size={16} />
          </Link>
        </div>
        {notice && <div className="mt-5 max-w-xl text-left"><Note tone={notice.tone}>{notice.text}</Note></div>}
      </div>
    </section>
  )
}

export function FilteredEmpty({ relevantOnly, hidden, onShowHidden, onReset, hasFilters }: {
  relevantOnly: boolean; hidden: number; onShowHidden: () => void; onReset: () => void; hasFilters: boolean
}) {
  const { t } = useI18n()
  return (
    <div className="flex flex-col items-center px-8 py-14 text-center">
      <SearchX size={26} className="text-gold" />
      <h2 className="mt-3 font-serif text-[1.35rem] font-semibold text-charcoal">{t('news.empty.filtered.title')}</h2>
      <p className="mt-2 max-w-lg text-[0.98rem] text-charcoal-soft">
        {hasFilters && t('news.empty.filtered.body')}
        {relevantOnly && <> {t('news.empty.filtered.relevant')}</>}
      </p>
      <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
        {relevantOnly && hidden > 0 && (
          <button type="button" className="btn-primary" onClick={onShowHidden}>
            {t('news.results.showHidden')} ({hidden})
          </button>
        )}
        {hasFilters && <button type="button" className="btn-secondary" onClick={onReset}>{t('news.f.reset')}</button>}
      </div>
    </div>
  )
}
