// Empty states of /offerte: the first visit (no quote yet) explains the page and invites the first
// offer; a filter with no match offers to reset the filters.
import { Calculator, FileText, GitCompareArrows, Lock, Plus, SearchX } from 'lucide-react'
import type { ReactNode } from 'react'
import { EmptyState, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate } from '@/lib/format'

function Step({ n, icon, title, children }: { n: number; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-sm border border-gold-light/60 bg-gold-pale text-gold-dark">
        {icon}
      </span>
      <div className="min-w-0">
        <div className="font-medium text-charcoal"><span className="num mr-1 text-gold-dark">{n}.</span>{title}</div>
        <p className="mt-0.5 text-[0.93rem] leading-relaxed text-muted">{children}</p>
      </div>
    </li>
  )
}

export function FirstQuote({ onAdd, fxNewest }: { onAdd: () => void; fxNewest?: string | null }) {
  const { t, lang } = useI18n()
  return (
    <Panel bodyClassName="p-5 sm:p-8">
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        <div className="min-w-0">
          <div className="eyebrow mb-1">{t('quotes.empty.eyebrow')}</div>
          <h2 className="font-serif text-[1.55rem] font-semibold leading-tight">{t('quotes.empty.title')}</h2>
          <p className="mt-3 max-w-xl leading-relaxed text-charcoal-soft">{t('quotes.empty.body')}</p>
          <button type="button" className="btn-primary mt-5 !px-5 !py-2.5 text-[1rem]" onClick={onAdd}>
            <Plus size={18} /> {t('quotes.empty.cta')}
          </button>
          <p className="mt-5 flex items-start gap-2 text-[0.9rem] text-muted">
            <Lock size={16} className="mt-0.5 shrink-0 text-forest-600" />
            <span>{t('quotes.privacy')}</span>
          </p>
        </div>
        <div className="min-w-0 border-t border-line-soft pt-6 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
          <div className="eyebrow mb-3">{t('quotes.empty.howTitle')}</div>
          <ol className="space-y-4">
            <Step n={1} icon={<FileText size={18} />} title={t('quotes.empty.step1')}>{t('quotes.empty.step1Body')}</Step>
            <Step n={2} icon={<Calculator size={18} />} title={t('quotes.empty.step2')}>{t('quotes.empty.step2Body')}</Step>
            <Step n={3} icon={<GitCompareArrows size={18} />} title={t('quotes.empty.step3')}>{t('quotes.empty.step3Body')}</Step>
          </ol>
          <p className="mt-5 text-[0.84rem] text-muted">
            {t('quotes.empty.sources')}
            {fxNewest && <> {t('quotes.empty.fxNewest', { date: fmtDate(fxNewest, lang) })}</>}
          </p>
        </div>
      </div>
    </Panel>
  )
}

export function NoMatches({ onReset, archivedHint }: { onReset: () => void; archivedHint?: boolean }) {
  const { t } = useI18n()
  return (
    <EmptyState
      icon={<SearchX size={22} />}
      title={t('quotes.noMatch.title')}
      hint={archivedHint ? t('quotes.noMatch.archivedHint') : t('quotes.noMatch.hint')}
      action={<button type="button" className="btn-secondary" onClick={onReset}>{t('ui.reset')}</button>}
    />
  )
}
