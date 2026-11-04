// View state of /raccolti, kept in the address so a view can be bookmarked, shared or captured
// (e.g. /raccolti?paese=ARG&regione=ARG-BA&segnale=drought_watch&elenco=tutti).
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { RuleKey } from './types'

export type SignalFilter = '' | 'any' | RuleKey
export type ProdScope = 'monitored' | 'all'
export type YearsRange = '20' | 'all'

export interface HarvestParams {
  /** ISO3 country shown (weather table, map focus, production chart); '' = all countries */
  country: string
  /** region key opened in the detail panel; '' = none */
  region: string
  /** weather table filter on the automatic signals */
  signal: SignalFilter
  /** production table: monitored countries (default) or every country */
  scope: ProdScope
  /** production chart metric (production, colonies...) */
  metric: string
  /** production chart years */
  years: YearsRange
}

const SIGNALS: SignalFilter[] = ['', 'any', 'drought_watch', 'heat_stress', 'wet_season']

export function readHarvestParams(sp: URLSearchParams): HarvestParams {
  const country = (sp.get('paese') ?? '').trim().toUpperCase()
  const region = (sp.get('regione') ?? '').trim().toUpperCase()
  const signal = (sp.get('segnale') ?? '') as SignalFilter
  return {
    country: /^[A-Z]{3}$/.test(country) ? country : '',
    region: /^[A-Z0-9-]{2,20}$/.test(region) ? region : '',
    signal: SIGNALS.includes(signal) ? signal : '',
    scope: sp.get('elenco') === 'tutti' ? 'all' : 'monitored',
    metric: (sp.get('misura') ?? '').trim() || 'production',
    years: sp.get('anni') === 'tutti' ? 'all' : '20',
  }
}

export function patchHarvestParams(prev: URLSearchParams, patch: Partial<HarvestParams>): URLSearchParams {
  const next = new URLSearchParams(prev)
  const set = (k: string, v: string | undefined, def = '') => {
    if (v === undefined) return
    if (v === def || v === '') next.delete(k)
    else next.set(k, v)
  }
  set('paese', patch.country)
  set('regione', patch.region)
  set('segnale', patch.signal)
  if (patch.scope !== undefined) set('elenco', patch.scope === 'all' ? 'tutti' : '')
  set('misura', patch.metric, 'production')
  if (patch.years !== undefined) set('anni', patch.years === 'all' ? 'tutti' : '')
  return next
}

export function useHarvestParams() {
  const [sp, setSp] = useSearchParams()
  const state = useMemo(() => readHarvestParams(sp), [sp])
  const update = useCallback((patch: Partial<HarvestParams>) => {
    setSp((prev) => patchHarvestParams(prev, patch), { replace: true })
  }, [setSp])
  return { state, update }
}
