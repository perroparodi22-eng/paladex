// Honest empty states: say what is missing and which sources will provide it.
import { Database } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { useLabels } from '@/lib/meta'
import { SOURCES_BY_TYPE } from './utils'

export function NoDataForType({ type }: { type: string }) {
  const { t } = useI18n()
  const { priceType } = useLabels()
  const sources = SOURCES_BY_TYPE[type] ?? []
  return (
    <Panel className="mb-5">
      <div className="flex flex-col items-center text-center py-8 px-4">
        <Database size={26} className="text-gold mb-3" />
        <h2 className="font-serif text-[1.35rem] text-charcoal">{t('prices.empty.title')}</h2>
        <p className="mt-1 text-muted max-w-xl">{t('prices.empty.type', { type: priceType(type) })}</p>
        <div className="mt-5 w-full max-w-2xl text-left">
          {sources.length ? (
            <>
              <div className="eyebrow mb-2">{t('prices.empty.willFill')}</div>
              <ul className="flex flex-col gap-2">
                {sources.map((s) => (
                  <li key={s} className="flex items-start gap-2.5 border border-line-soft rounded-sm px-3 py-2 bg-paper text-[0.95rem] text-charcoal-soft">
                    <span className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
                    {t(`prices.src.${s}`)}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-center text-muted">{t('prices.empty.noSource')}</p>
          )}
        </div>
        <Link to="/fonti" className="btn-secondary mt-6">{t('prices.empty.goSources')}</Link>
      </div>
    </Panel>
  )
}

export function NoDataInView({ reason, lastPeriod, onShowAll, onReset }: {
  reason: 'period' | 'filters'
  lastPeriod?: string | null
  onShowAll?: () => void
  onReset?: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="flex flex-col items-center text-center py-10 px-4 text-muted">
      <div className="font-serif text-lg text-charcoal-soft">{t('prices.empty.title')}</div>
      <p className="mt-1">
        {reason === 'period' ? t('prices.empty.period') : t('prices.empty.filters')}
        {lastPeriod && <> {t('prices.empty.lastAvailable', { p: lastPeriod })}</>}
      </p>
      <div className="mt-4 flex gap-2">
        {onShowAll && <button type="button" className="btn-secondary" onClick={onShowAll}>{t('prices.empty.showAll')}</button>}
        {onReset && <button type="button" className="btn-secondary" onClick={onReset}>{t('prices.f.reset')}</button>}
      </div>
    </div>
  )
}
