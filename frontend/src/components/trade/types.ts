// Responses of /api/trade/* (backend/paladex/api/trade.py). Also reused by the country profile.
import type { Freshness, SourceBrief } from '@/lib/types'

export type TradeFlow = 'import' | 'export'
export type TradeMetric = 'volume' | 'value'
export type TradeFreq = 'A' | 'M'

export interface Provider {
  key: string; name: string; publisher: string | null; enabled: boolean
  last_run_status: string | null; expected_update?: string | null; expected_update_en?: string | null
}

export interface SourceUsed extends SourceBrief {
  freshness: Freshness | null
  latest_published_at: string | null
  expected_update: string | null
  expected_update_en?: string | null
}

/** Provenance carried by every trade figure. */
export interface TradeProv {
  source: SourceBrief | null
  source_url: string | null
  published_at: string | null
  collected_at: string | null
  period_label: string | null
  period_start: string | null
  period_end: string | null
  frequency: string
  data_status: string | null
  reliability: string | null
  is_demo: boolean
}

export interface TradeFigures {
  net_weight_kg: number | null
  usd_value: number | null
  value: number | null
  currency: string | null
  value_basis: string | null
  unit_value_usd_per_kg: number | null
  fx_missing: boolean
}

export interface Names { name_it: string | null; name_en: string | null }

export interface CountryTotal extends TradeProv, TradeFigures, Names {
  iso3: string
  year: number
  summed_from_partners: boolean
  summed_from_months: boolean
  partners_count: number | null
  months_count: number | null
  complete: boolean
  prev: { year: number; net_weight_kg: number | null; usd_value: number | null; summed_from_partners: boolean; is_demo: boolean } | null
  yoy_volume_pct: number | null
  yoy_value_pct: number | null
}

export interface LeaderRow extends CountryTotal {
  rank: number
  link: string
  // mirror basis only
  reporters_count?: number
  reporters?: string[]
  sources_list?: SourceBrief[]
  yoy_like_for_like_reporters?: number
}

export interface LeadersResponse {
  flow: TradeFlow
  basis: 'declared' | 'mirror'
  metric: TradeMetric
  year: number | null
  default_year: number | null
  available_years: number[]
  rows: LeaderRow[]
  incomplete: { iso3: string; name_it: string | null; name_en: string | null; months_count: number; net_weight_kg: number | null; source: SourceBrief | null; is_demo: boolean }[]
  count: number
  sources: SourceUsed[]
  mixed_sources: boolean
  providers: Provider[]
  reporters?: (Names & { iso3: string; source: SourceBrief | null; frequency: string })[]
}

export interface FacetReporter extends Names {
  iso3: string
  is_aggregate: boolean
  flows: Partial<Record<TradeFlow, { frequencies: string[]; years: number[]; rows: number }>>
  sources: string[]
  rows: number
  first_period: string | null
  last_period: string | null
}

export interface FacetsResponse {
  total_rows: number
  reporters: FacetReporter[]
  partners: (Names & { iso3: string; known: boolean; rows: number })[]
  years: { year: number; import_reporters: number; import_complete: number; export_reporters: number; export_complete: number }[]
  months: { period: string; import_reporters: number; export_reporters: number }[]
  default_year: Record<TradeFlow, number | null>
  sources: (SourceBrief & {
    frequencies: string[]; rows: number; first_period: string | null; last_period: string | null
    latest_period_label: string | null; latest_published_at: string | null; collected_at: string | null
    is_demo: boolean; expected_update: string | null; expected_update_en?: string | null; freshness: Freshness
  })[]
  providers: Provider[]
}

export interface FlowRow extends TradeProv, TradeFigures, Names {
  iso3: string
  rank: number
  known: boolean
  share_volume_pct: number | null
  share_value_pct: number | null
  prev_net_weight_kg: number | null
  yoy_volume_pct: number | null
  months_count: number | null
  link: string | null
}

export interface FlowsResponse extends Partial<TradeProv>, Names {
  reporter: string
  flow: TradeFlow
  year: number | null
  metric: TradeMetric
  default_year: number | null
  available_years: number[]
  complete_years: number[]
  available: boolean
  rows: FlowRow[]
  others: { count: number; net_weight_kg: number | null; usd_value: number | null; share_volume_pct: number | null; share_value_pct: number | null } | null
  unallocated: { net_weight_kg: number | null; usd_value: number | null; share_volume_pct: number | null } | null
  total: CountryTotal | null
  share_basis?: 'world_total' | 'partner_sum'
  partners_count?: number
  months_count?: number | null
  complete?: boolean
  alternatives: { source: SourceBrief | null; frequency: string; months_count: number | null; complete: boolean; has_partners: boolean }[]
  freshness?: Freshness
  providers: Provider[]
}

export interface SeriesPoint extends TradeProv, TradeFigures {
  period_label: string
  summed_from_partners: boolean
  partners_count: number | null
  summed_from_months: boolean
  months_count: number | null
}

export interface TradeSeries {
  source: SourceBrief | null
  frequency: TradeFreq
  points: SeriesPoint[]
  is_demo: boolean
  freshness: Freshness | null
  expected_update: string | null
  expected_update_en?: string | null
}

export interface SeriesResponse {
  reporter: string
  partner: string
  flow: TradeFlow
  freq: TradeFreq
  reporter_names: Names
  partner_names: Names
  available: boolean
  series: TradeSeries[]
  excluded_partial: { source: SourceBrief | null; period_label: string; months_count: number; last_month: string }[]
  discrepancies: { period_label: string; diff_pct: number; values: { source: SourceBrief | null; net_weight_kg: number }[] }[]
  providers: Provider[]
}
