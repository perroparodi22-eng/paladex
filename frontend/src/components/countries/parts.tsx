// Small pieces shared by the countries page and the country profile.
import clsx from 'clsx'
import { ArrowDownLeft, ArrowUpRight, BookOpen, Newspaper, Scale, Sprout, Tag } from 'lucide-react'
import type { ReactNode } from 'react'
import { useI18n } from '@/i18n'
import type { Lang } from '@/lib/types'
import type { Availability } from './types'

export type AvailKey = 'production' | 'exports' | 'imports' | 'prices' | 'news' | 'regulations' | 'context'

const ICONS: Record<AvailKey, ReactNode> = {
  production: <Sprout size={15} />,
  exports: <ArrowUpRight size={15} />,
  imports: <ArrowDownLeft size={15} />,
  prices: <Tag size={14} />,
  news: <Newspaper size={14} />,
  regulations: <Scale size={14} />,
  context: <BookOpen size={14} />,
}
export const AVAIL_KEYS: AvailKey[] = ['production', 'exports', 'imports', 'prices', 'news', 'regulations', 'context']

function state(a: Availability, k: AvailKey): 'yes' | 'mirror' | 'no' {
  if (a[k]) return 'yes'
  if (k === 'exports' && a.exports_mirror) return 'mirror'
  if (k === 'imports' && a.imports_mirror) return 'mirror'
  return 'no'
}

/** Row of small icons: which kinds of data exist for a country (hover for the label). */
export function AvailabilityIcons({ a, className, keys = AVAIL_KEYS, size = 'md' }: {
  a: Availability; className?: string; keys?: readonly AvailKey[]; size?: 'sm' | 'md'
}) {
  const { t } = useI18n()
  return (
    <div className={clsx('flex items-center', size === 'sm' ? 'gap-0.5' : 'gap-1', className)}>
      {keys.map((k) => {
        const s = state(a, k)
        return (
          <span
            key={k}
            title={`${t(`countries.avail.${k}`)}: ${t(`countries.avail.${s === 'yes' ? 'yes' : s === 'mirror' ? 'mirror' : 'no'}`)}`}
            className={clsx('inline-flex items-center justify-center rounded-sm border', size === 'sm' ? 'h-[19px] w-[19px] [&>svg]:h-[13px] [&>svg]:w-[13px]' : 'h-[22px] w-[22px]',
              s === 'yes' ? 'border-forest-100 bg-forest-50 text-forest-700'
                : s === 'mirror' ? 'border-dashed border-gold-light text-gold-dark'
                  : 'border-transparent text-line')}
          >
            {ICONS[k]}
          </span>
        )
      })}
    </div>
  )
}

/** Explains the icons once, in plain words. */
export function AvailabilityLegend({ keys = ['production', 'exports', 'imports', 'prices', 'news', 'regulations'] }: { keys?: readonly AvailKey[] }) {
  const { t } = useI18n()
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.78rem] text-muted">
      {keys.map((k) => (
        <span key={k} className="inline-flex items-center gap-1">
          <span className="inline-flex h-[17px] w-[17px] items-center justify-center rounded-sm border border-forest-100 bg-forest-50 text-forest-700 [&>svg]:h-[12px] [&>svg]:w-[12px]">{ICONS[k]}</span>
          {t(`countries.avail.${k}`)}
        </span>
      ))}
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-[15px] w-[15px] rounded-sm border border-dashed border-gold-light" />
        {t('countries.avail.mirror')}
      </span>
    </div>
  )
}

/** Labelled chips for the profile header. */
export function AvailabilityChips({ a }: { a: Availability }) {
  const { t } = useI18n()
  return (
    <div className="flex flex-wrap gap-1.5">
      {AVAIL_KEYS.map((k) => {
        const s = state(a, k)
        return (
          <span key={k}
            title={t(`countries.avail.${s === 'yes' ? 'yes' : s === 'mirror' ? 'mirror' : 'no'}`)}
            className={clsx('inline-flex items-center gap-1.5 rounded-sm border px-2 py-[3px] text-[0.82rem]',
              s === 'yes' ? 'border-forest-100 bg-forest-50 text-forest-800'
                : s === 'mirror' ? 'border-dashed border-gold-light bg-gold-pale/50 text-gold-dark'
                  : 'border-line bg-white text-muted line-through decoration-muted/40')}>
            {ICONS[k]}{t(`countries.avail.${k}`)}
          </span>
        )
      })}
    </div>
  )
}

export function useRegion() {
  const { t } = useI18n()
  return (r: string | null | undefined) => (r ? (t(`countries.region.${r}`) === `countries.region.${r}` ? r : t(`countries.region.${r}`)) : '—')
}

export function countryName(c: { name_it: string; name_en: string }, lang: Lang): string {
  return lang === 'it' ? c.name_it : c.name_en
}
