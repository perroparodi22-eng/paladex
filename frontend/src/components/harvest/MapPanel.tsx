// Map panel: the region map (lazy, browser only), its legend and how to read it.
import { lazy, Suspense, useEffect, useState } from 'react'
import { Loading, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtPeriod } from '@/lib/format'
import { AssessmentMark, ConditionDot } from './parts'
import type { Condition, WeatherResponse } from './types'

const RegionMap = lazy(() => import('./RegionMap'))

const LEGEND: Condition[] = ['drought_watch', 'heat_stress', 'wet_season', 'normal', 'no_data']

function useMapHeight(): number {
  const pick = () => (typeof window === 'undefined' ? 470 : window.innerWidth < 640 ? 300 : window.innerWidth >= 1280 ? 520 : 440)
  const [h, setH] = useState(pick)
  useEffect(() => {
    const on = () => setH(pick())
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  return h
}

export function MapPanel({ data, visible, selected, onSelect }: {
  data: WeatherResponse; visible: Set<string>; selected: string; onSelect: (key: string) => void
}) {
  const { t, lang } = useI18n()
  const height = useMapHeight()
  // Leaflet needs a browser: on the server (tests) the panel renders its legend only.
  const inBrowser = typeof window !== 'undefined' && typeof document !== 'undefined'
  return (
    <Panel
      title={t('harvest.map.title')}
      eyebrow={data.latest_period_label ? t('harvest.map.eyebrow', { month: fmtPeriod(data.latest_period_label, lang) }) : undefined}
      className="min-w-0"
      bodyClassName="!p-0"
    >
      <div className="relative" style={{ minHeight: height }}>
        {inBrowser && (
          <Suspense fallback={<Loading />}>
            <RegionMap regions={data.regions} visible={visible} selected={selected} onSelect={onSelect} height={height} />
          </Suspense>
        )}
      </div>
      <div className="flex flex-col gap-2 border-t border-line-soft px-4 py-3 sm:px-5">
        <div><AssessmentMark /></div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-[0.85rem] text-charcoal-soft">
          {LEGEND.map((c) => (
            <li key={c} className="flex items-center gap-1.5"><ConditionDot condition={c} />{t(`harvest.cond.${c}`)}</li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[0.8rem] text-muted">
          <span className="flex items-center gap-1.5"><ConditionDot condition="drought_watch" size={10} /> {t('harvest.map.recent')}</span>
          <span className="flex items-center gap-1.5"><ConditionDot condition="drought_watch" hollow size={10} /> {t('harvest.map.earlier')}</span>
        </div>
        <p className="text-[0.8rem] text-muted">{t('harvest.map.hint')}</p>
      </div>
    </Panel>
  )
}
