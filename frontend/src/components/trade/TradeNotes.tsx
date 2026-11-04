// "How to read these data": customs declarations, publication lag, mirror data, unit values.
import { Panel } from '@/components/ui'
import { expectedUpdate, useI18n } from '@/i18n'
import { SourcesFooter } from './bits'
import type { FacetsResponse, SourceUsed } from './types'

export function TradeNotes({ facets, className, wide = false }: { facets: FacetsResponse; className?: string; wide?: boolean }) {
  const { t, lang } = useI18n()
  const sources: SourceUsed[] = facets.sources.map((s) => ({
    key: s.key, name: s.name, publisher: s.publisher, reliability: s.reliability, homepage: s.homepage,
    freshness: s.freshness, latest_published_at: s.latest_published_at, expected_update: s.expected_update,
    expected_update_en: s.expected_update_en,
  }))
  const items = ['customs', 'lag', 'mirror', 'uv', 'eu']
  return (
    <Panel title={t('trade.notes.title')} className={className}>
      <div className={wide ? 'grid gap-x-10 gap-y-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]' : ''}>
      <ul className="flex flex-col gap-2.5 text-[0.92rem] leading-snug text-charcoal-soft">
        {items.map((k) => (
          <li key={k} className="flex gap-2.5">
            <span className="mt-[0.55rem] h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
            <span>{t(`trade.notes.${k}`)}</span>
          </li>
        ))}
      </ul>
      {sources.length > 0 && (
        <div className={wide ? 'xl:border-l xl:border-line-soft xl:pl-8 max-xl:pt-3 max-xl:border-t max-xl:border-line-soft' : 'mt-4 pt-3 border-t border-line-soft'}>
          <div className="eyebrow mb-1.5">{t('trade.notes.sources')}</div>
          <SourcesFooter sources={sources} />
          <div className="mt-1.5 flex flex-col gap-0.5 text-[0.78rem] text-muted">
            {facets.sources.filter((s) => expectedUpdate(s, lang)).map((s) => (
              <div key={s.key}><span className="text-charcoal-soft">{s.publisher || s.name}</span>: {expectedUpdate(s, lang)}</div>
            ))}
          </div>
        </div>
      )}
      </div>
    </Panel>
  )
}
