import { useQuery } from '@tanstack/react-query'
import { useCallback } from 'react'
import { api } from './api'
import type { Meta } from './types'
import { useI18n } from '@/i18n'

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: () => api.get<Meta>('/meta'), staleTime: 5 * 60_000 })
}

/** Label helpers that follow the current language. Fall back to the raw key while loading. */
export function useLabels() {
  const { data } = useMeta()
  const { lang } = useI18n()

  const country = useCallback(
    (iso3: string | null | undefined) => {
      if (!iso3) return '—'
      if (iso3 === 'WLD') return lang === 'it' ? 'Mondo' : 'World'
      if (iso3 === 'EU27') return lang === 'it' ? 'Unione Europea' : 'European Union'
      if (iso3 === 'EXTRA_EU') return lang === 'it' ? 'Extra-UE' : 'Extra-EU'
      const c = data?.countries.find((x) => x.iso3 === iso3)
      return c ? (lang === 'it' ? c.name_it : c.name_en) : iso3
    },
    [data, lang],
  )
  const pick = useCallback(
    (list: { key: string; it: string; en: string }[] | undefined, key: string | null | undefined) => {
      if (!key) return '—'
      const x = list?.find((v) => v.key === key)
      return x ? x[lang] : key
    },
    [lang],
  )
  const variety = useCallback((k: string | null | undefined) => pick(data?.varieties, k), [data, pick])
  const priceType = useCallback((k: string | null | undefined) => pick(data?.price_types, k), [data, pick])
  const dataStatus = useCallback((k: string | null | undefined) => pick(data?.data_status, k), [data, pick])
  const reliability = useCallback((k: string | null | undefined) => pick(data?.reliability, k), [data, pick])
  return { country, variety, priceType, dataStatus, reliability, meta: data }
}
