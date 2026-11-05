// Types of /api/harvest/* (backend/paladex/api/harvest.py).
import type { ProductionMetric } from '@/components/countries/types'
import type { Provider, SourceUsed } from '@/components/trade/types'
import type { Freshness, SourceBrief } from '@/lib/types'

export type RuleKey = 'drought_watch' | 'heat_stress' | 'wet_season'
export type Condition = RuleKey | 'normal' | 'no_data'

export interface Rule {
  key: RuleKey
  metric: 'precip_pct' | 'temp_anomaly_c'
  operator: '<' | '>' | '>='
  threshold: number
  unit: string
  min_months: number
  flowering_only: boolean
  label_it: string; label_en: string
  rule_it: string; rule_en: string
  why_it: string; why_en: string
}

/** A rule-based flag: an automatic assessment computed from the data, never data itself. */
export interface Flag {
  rule: RuleKey
  months: string[]
  values: (number | null)[]
  metric: 'precip_pct' | 'temp_anomaly_c'
  data_status: string | null
  recent: boolean
  /** months whose value includes an exceptional point (plausibility check): to verify */
  exceptional_months: string[]
}

export interface PointMonth {
  /** plausibility check: more than 5x its normal rain and over 300 mm (kept as published, to verify) */
  exceptional: boolean
  point: string; name: string
  temp_mean_c: number | null; temp_anomaly_c: number | null
  precip_mm: number | null; precip_anomaly_pct: number | null
  normal_temp_c: number | null; normal_precip_mm: number | null
  basis: 'monthly' | 'daily' | null; nasa_sources: string[]; data_status: string
  source_url: string | null; collected_at: string | null; last_seen_at: string | null; revision: number
}

export interface RegionMonth {
  period_label: string
  temp_mean_c: number | null; temp_anomaly_c: number | null; normal_temp_c: number | null
  precip_mm: number | null; precip_normal_mm: number | null; precip_pct: number | null
  points_with_data: number; points_total: number
  data_status: string | null
  exceptional_points: string[]
  flowering: boolean; harvest: boolean
  points?: PointMonth[]
}

export interface RegionContext {
  varieties_it: string[]; varieties_en: string[]
  flowering_months: number[]; harvest_months: number[]
  note_it: string | null; note_en: string | null
  hemisphere: 'N' | 'S'; is_context: true
}

export interface RegionPoint { key: string; name: string; lat: number; lon: number }

export interface HarvestRegion {
  key: string; country_iso3: string; country_name_it: string | null; country_name_en: string | null
  name_it: string; name_en: string; lat: number; lon: number
  points: RegionPoint[]
  context: RegionContext
  recent: RegionMonth[]
  months?: RegionMonth[]
  latest_period_label: string | null
  flags: Flag[]
  condition: Condition
  condition_recent: RuleKey | null
  has_data: boolean
}

export interface WeatherSource extends SourceBrief {
  freshness: Freshness; expected_update: string | null; expected_update_en: string | null; terms_note: string | null
}

export interface WeatherCollection {
  state: 'running' | 'never' | 'success' | 'partial' | 'no_change' | 'failed' | 'offline' | 'skipped' | 'unknown'
  last_run_at: string | null; last_run_status: string | null; last_success_at?: string | null; enabled: boolean
}

export interface WeatherMeta {
  available: boolean
  source: WeatherSource | null
  collection: WeatherCollection
  citation: string
  accessed_at: string | null
  api_versions: string[]
  months: string[]
  recent_months: string[]
  latest_period_label: string | null
  latest_data_status: string | null
  expected_latest_period_label: string
  behind_expected: boolean
  baseline: string
  rules: Rule[]
  rules_scope_it: string; rules_scope_en: string
  assessment_label_it: string; assessment_label_en: string
  rule_min_normal_mm: number
  exceptional_ratio: number; exceptional_min_mm: number
  is_demo: boolean
  generated_at: string
}

export interface WeatherResponse extends WeatherMeta {
  regions: HarvestRegion[]
  countries: { iso3: string; name_it: string | null; name_en: string | null; regions: string[] }[]
  regions_with_data: number
}

export interface RegionDetailResponse extends WeatherMeta {
  region: HarvestRegion & { months: RegionMonth[] }
}

/** A production value of the table (its source, unit and reliability are on the series). */
export interface ProductionValue {
  period_label: string; year: number; value: number; unit: string; flag_raw: string | null; notes: string | null
  source_url: string | null; published_at: string | null; collected_at: string | null
  data_status: string; is_demo: boolean
}

export interface ProductionRowSeries {
  source: SourceBrief | null; unit: string; reliability: string | null; frequency: string
  latest: ProductionValue | null; previous: ProductionValue | null; change_pct: number | null
  forecast: ProductionValue | null; latest_t: number | null; years: number
}

export interface ProductionCountry {
  iso3: string; name_it: string | null; name_en: string | null
  monitored: boolean; regions: string[]
  series: ProductionRowSeries[]
  primary_t: number | null; primary_year: number | null; is_demo: boolean
}

export interface ProductionResponse {
  available: boolean
  scope: 'monitored' | 'all'
  countries: ProductionCountry[]
  monitored: string[]
  countries_with_data: number
  monitored_with_data: number
  years: number[]
  sources: SourceUsed[]
  providers: Provider[]
  data_status: string | null
  generated_at: string
}

export interface ProductionCountryResponse {
  iso3: string; name_it: string; name_en: string; regions: string[]
  available: boolean; metrics: ProductionMetric[]; providers: Provider[]
  sources: SourceUsed[]; is_demo: boolean
}

export interface HarvestReport {
  id: number; report_key: string; title: string; period_label: string | null
  published_at: string | null; collected_at: string | null
  source: SourceBrief | null; source_url: string; reliability: string | null; data_status: string; is_demo: boolean
  summary_it: string | null; summary_en: string | null; summary_is_ai: boolean
  has_narrative: boolean; narrative_excerpt: string | null
}

export interface HarvestNews {
  id: number; title: string; title_it: string | null; title_en: string | null; language: string | null
  publisher: string | null; url: string; published_at: string | null; collected_at: string | null
  snippet: string | null; summary_it: string | null; summary_en: string | null; ai_model: string | null
  countries: string[]; topics: string[]; harvest_topics: string[]; relevance_score: number
  source: SourceBrief | null; is_demo: boolean
}

export interface ReportsResponse {
  reports: HarvestReport[]
  news: HarvestNews[]
  report_providers: Provider[]
  news_providers: Provider[]
  news_link: string
  news_min_relevance: number
  is_demo: boolean
}
