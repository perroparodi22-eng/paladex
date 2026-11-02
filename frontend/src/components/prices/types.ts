// Types for /api/prices/* (mirror backend/paladex/api/prices.py).
import type { FreshnessStatus, SourceBrief } from '@/lib/types'

export type PriceTypeKey = 'wholesale_bulk' | 'producer' | 'import_unit_value' | 'export_unit_value' | 'retail' | 'other'
export type Freq = 'M' | 'Q' | 'A'
export type Ccy = 'USD' | 'EUR'
export type MassUnit = 'kg' | 'lb'
export type RangePreset = '1y' | '3y' | '5y' | 'all'

export interface SeriesFreshness {
  status: FreshnessStatus
  age_days: number | null
  reference_date: string | null
  expected_max_age_days: number | null
  basis: 'source' | 'frequency'
}

export interface OriginalPrice { value: number; low: number | null; high: number | null; currency: string; unit: string }

export interface PricePoint {
  period_label: string
  period_start: string
  period_end: string
  value: number | null
  low: number | null
  high: number | null
  original: OriginalPrice | null
  n_points: number
  expected_points: number | null
  periods: string[]
  fx_missing: number
  published_at: string | null
  collected_at: string | null
  source_url: string | null
  fx_date: string | null
  data_status: string
  is_demo: boolean
}

/** Fields that identify a series (one line on the chart). */
export interface SeriesIdentity {
  source: SourceBrief | null
  price_type: string
  origin_iso3: string | null
  origin_label: string | null
  market_iso3: string | null
  market_location: string | null
  variety: string
  variety_raw: string[]
  color_grade: string | null
  terms: string | null
  organic: boolean
}

export interface PriceSeries extends SeriesIdentity {
  id: string
  currency: string
  unit: 'kg'
  native_frequency: string
  freq: Freq
  n_points: number
  first_period: string
  last_period: string
  published_at: string | null
  collected_at: string | null
  source_url: string | null
  data_status: string
  data_statuses: string[]
  reliability: string
  is_demo: boolean
  has_range: boolean
  fx_missing_points: number
  freshness: SeriesFreshness
  points: PricePoint[]
}

export interface SeriesSource extends SourceBrief {
  n_series: number
  published_at: string | null
  collected_at: string | null
  source_url: string | null
  is_demo: boolean
  freshness: SeriesFreshness | null
}

export interface DiscrepancyEntry {
  source: SourceBrief | null
  value: number
  n_rows: number
  color_grades: string[]
  terms: string[]
  published_at: string | null
  collected_at: string | null
  source_url: string | null
  data_status: string
  is_demo: boolean
}

export interface Discrepancy {
  price_type: string
  origin_iso3: string | null
  variety: string
  market_iso3: string | null
  period_label: string
  currency: string
  unit: 'kg'
  min: number
  max: number
  spread_pct: number
  threshold_pct: number
  is_demo: boolean
  entries: DiscrepancyEntry[]
}

export interface SeriesResponse {
  price_type: string
  currency: string
  unit: 'kg'
  freq: Freq
  from: string | null
  to: string | null
  series: PriceSeries[]
  sources: SeriesSource[]
  discrepancies: Discrepancy[]
  today: string
}

export interface PointRef { period_label: string; value: number | null; n_points: number; published_at: string | null }

export interface LatestRow extends SeriesIdentity {
  series_id: string
  currency: string
  unit: 'kg'
  native_frequency: string
  freq: Freq
  reliability: string
  is_demo: boolean
  latest: PricePoint
  period_label: string
  published_at: string | null
  collected_at: string | null
  source_url: string | null
  data_status: string
  previous: PointRef | null
  year_ago: PointRef | null
  change_prev_pct: number | null
  change_yoy_pct: number | null
  freshness: SeriesFreshness
  is_stale: boolean
}

export interface LatestResponse { price_type: string; currency: string; freq: Freq; rows: LatestRow[]; today: string }

export interface CompareComponent {
  series_id: string
  origin_iso3: string | null
  variety: string
  color_grade: string | null
  terms: string | null
  organic: boolean
  market_iso3: string | null
  source: SourceBrief | null
  period_label: string
  value: number
  low: number | null
  high: number | null
  published_at: string | null
  source_url: string | null
  data_status: string
  is_demo: boolean
  freshness: SeriesFreshness
}

export interface CompareBar {
  key: string
  value: number
  min: number
  max: number
  n_series: number
  period_label: string
  period_labels: string[]
  mixed_periods: boolean
  is_demo: boolean
  sources: (SourceBrief | null)[]
  components: CompareComponent[]
}

export interface CompareResponse {
  by: 'origin' | 'variety'
  price_type: string
  currency: string
  period: string
  window_months: number
  anchor_period: string | null
  window_from: string | null
  window_to: string | null
  bars: CompareBar[]
  excluded: { key: string; series_id: string; variety: string; origin_iso3: string | null; source: SourceBrief | null; last_period: string }[]
}

export interface FacetItem { key: string; count: number }
export interface CountryFacet extends FacetItem { priority: boolean; name_it: string | null; name_en: string | null }
export interface SourceFacet extends SourceBrief { count: number; expected_update: string | null; latest_published_at: string | null }

export interface FacetsResponse {
  scoped_to: string | null
  total: number
  price_types: (FacetItem & { min_period: string | null; max_period: string | null })[]
  origins: CountryFacet[]
  markets: CountryFacet[]
  varieties: FacetItem[]
  sources: SourceFacet[]
  color_grades: FacetItem[]
  currencies: FacetItem[]
  frequencies: FacetItem[]
  conversions: { USD: number; EUR: number }
  has_ranges: boolean
  demo_rows: number
  period: { min: string | null; max: string | null }
}

export interface ObservationRow {
  id: number
  source: SourceBrief | null
  price_type: string
  origin_iso3: string | null
  origin_label: string | null
  market_iso3: string | null
  market_location: string | null
  variety: string
  variety_raw: string | null
  color_grade: string | null
  organic: boolean
  terms: string | null
  price_low: number | null
  price_value: number
  price_high: number | null
  currency: string
  unit: string
  price_per_kg: number
  usd_per_kg: number | null
  eur_per_kg: number | null
  fx_date: string | null
  volume_kg: number | null
  period_label: string
  period_start: string
  period_end: string
  frequency: string
  published_at: string | null
  collected_at: string | null
  source_url: string | null
  data_status: string
  reliability: string
  revision: number
  is_demo: boolean
  notes: string | null
}

export interface ObservationsResponse { total: number; page: number; page_size: number; pages: number; rows: ObservationRow[] }

/** Filters shared by every price request (URL state). */
export interface PriceFilterState {
  type: PriceTypeKey | null
  origins: string[]
  variety: string
  market: string
  source: string
  color: string
  ccy: Ccy
  unit: MassUnit
  range: RangePreset
  freq: Freq
}
