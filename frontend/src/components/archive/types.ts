// Types of /api/archive/* responses (backend/paladex/api/archive.py).
import type { TradeOption } from '@/components/alerts/types'
import type { NewsItem } from '@/components/news/types'
import type { Freshness, SourceBrief } from '@/lib/types'

export type ArchiveView = 'prezzi' | 'commercio' | 'produzione' | 'notizie' | 'offerte' | 'revisioni'
export const VIEWS: ArchiveView[] = ['prezzi', 'commercio', 'produzione', 'notizie', 'offerte', 'revisioni']
export type Ccy = 'ORIGINAL' | 'USD' | 'EUR'

export interface PriceSelection { price_type: string; origin: string; variety: string | null; market: string | null; color_grade: string | null }

export interface PriceCombo {
  origin: string; variety: string; market: string | null; color_grade: string | null; rows: number
  frequencies: string[]; first_period: string; last_period: string
}

export interface PriceOptionsResponse {
  price_types: { key: string; count: number }[]
  price_type: string | null
  combos: PriceCombo[]
  default: PriceSelection | null
}

export interface SeriesMeta {
  id: string
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
  currency: string
  unit: string
  native_frequency: string
  freq: 'M' | 'Q' | 'A'
  n_points: number
  first_period: string
  last_period: string
  weighting: string | null
  published_at: string | null
  collected_at: string | null
  source_url: string | null
  data_status: string | null
  data_statuses: string[]
  reliability: string | null
  is_demo: boolean
  freshness: Freshness & { expected_max_age_days?: number | null; basis?: string }
  fx_missing_points: number | null
}

export interface YearRow {
  year: number
  average: number | null
  weighting: 'volume' | 'simple'
  volume_kg: number | null
  periods: number
  expected_periods: number
  complete: boolean
  first_period: string
  last_period: string
  min: { period_label: string; value: number }
  max: { period_label: string; value: number }
  change_pct: number | null
  change_periods: number
  change_same_periods_only: boolean
  data_status: string | null
  published_at: string | null
  collected_at: string | null
  source_url: string | null
  is_demo: boolean
}

export interface OverlayPoint {
  period_label: string
  value: number | null
  low: number | null
  high: number | null
  n_points: number | null
  expected_points: number | null
  volume_kg: number | null
  published_at: string | null
  collected_at: string | null
  source_url: string | null
  data_status: string | null
  is_demo: boolean
  original: { value: number | null; currency: string; unit: string } | null
}

export interface Overlay { latest_year: number; years: { year: number; months: number; points: (OverlayPoint | null)[] }[] }

export interface PriceHistoryResponse {
  available: boolean
  filters: Record<string, unknown>
  series: SeriesMeta[]
  selected: (SeriesMeta & { years: YearRow[]; overlay: Overlay | null }) | null
}

export interface TradePoint {
  period_label: string
  net_weight_kg: number | null
  usd_value: number | null
  value: number | null
  currency: string | null
  summed_from_partners: boolean
  partners_count: number | null
  summed_from_months: boolean
  months_count: number | null
  source: SourceBrief | null
  source_url: string | null
  published_at: string | null
  collected_at: string | null
  data_status: string | null
  is_demo: boolean
  change_pct: number | null
}

export interface YtdYear {
  year: number; months: number; complete: boolean; net_weight_kg: number | null; usd_value: number | null
  data_status: string | null; published_at: string | null; source_url: string | null; is_demo: boolean; change_pct: number | null
}

export interface TradeHistoryResponse {
  reporter: string
  partner: string
  flow: 'import' | 'export'
  reporter_names: { name_it: string | null; name_en: string | null }
  partner_names: { name_it: string | null; name_en: string | null }
  total_scope: string | null
  available: boolean
  annual: { source: SourceBrief | null; points: TradePoint[]; freshness: Freshness; is_demo: boolean;
    expected_update: string | null; expected_update_en: string | null }[]
  ytd: { source: SourceBrief | null; freshness: Freshness; is_demo: boolean; through_month: number; latest_label: string; years: YtdYear[] }[]
  excluded_partial: { source: SourceBrief | null; period_label: string; months_count: number; last_month: string }[]
  /** months a source published without the reporter's total (partial data): never shown as a total */
  excluded_months?: { source: SourceBrief | null; month: string; reason: 'no_total'; partners_count: number }[]
  discrepancies: { period_label: string; diff_pct: number; values: { source: SourceBrief | null; net_weight_kg: number }[] }[]
  providers: { key: string; name: string; publisher: string | null; enabled: boolean }[]
}

export interface TradeOptionsResponse { reporters: TradeOption[] }

export interface ProductionPoint {
  period_label: string; year: number; value: number; unit: string; flag: string | null; change_pct: number | null
  data_status: string; published_at: string | null; collected_at: string | null; source_url: string | null; is_demo: boolean
  revision: number
}

export interface ProductionResponse {
  country: string
  metric: string
  available: boolean
  series: { source: SourceBrief | null; unit: string; frequency: string; points: ProductionPoint[]; reliability: string | null;
    expected_update: string | null; expected_update_en: string | null; is_demo: boolean }[]
  metrics: { key: string; rows: number }[]
  countries: { iso3: string; rows: number; last_period: string | null }[]
}

export interface NewsArchiveResponse {
  items: NewsItem[]
  total: number
  page: number
  page_size: number
  pages: number
  months: { month: string; count: number }[]
  archive: { oldest: string | null; newest: string | null; articles: number }
}

export interface QuoteItem {
  id: number
  supplier_name: string
  origin_iso3: string
  variety: string
  variety_note: string | null
  price_per_kg: number
  currency: string
  price_quoted: number | null
  price_unit: string
  quantity_kg: number | null
  packaging: string | null
  incoterm: string | null
  incoterm_place: string | null
  destination: string | null
  date_received: string
  valid_until: string | null
  expired: boolean
  archived: boolean
  notes: string | null
  is_demo: boolean
  data_status: string
}

export interface QuotesHistoryResponse {
  available: boolean
  total: number
  origin: string | null
  variety: string | null
  items: QuoteItem[]
  summary: { year: number; currency: string; incoterm: string | null; quotes: number; suppliers: number; min: number;
    max: number; average: number; is_demo: boolean }[]
  origins: { iso3: string; count: number }[]
  varieties: { key: string; count: number }[]
  total_all: number
}

export interface RevisionEntry {
  id: number
  revision: number
  is_current: boolean
  supersedes_id: number | null
  published_at: string | null
  collected_at: string | null
  last_seen_at: string | null
  data_status: string | null
  source_url: string | null
  is_demo: boolean
  value: number | null
  low?: number | null
  high?: number | null
  currency?: string | null
  unit: string | null
  volume_kg?: number | null
  trade_value?: number | null
  flag?: string | null
  change_pct: number | null
}

export interface RevisionPeriod {
  source: SourceBrief | null
  period_label: string
  period_start: string
  frequency: string
  status: 'revised' | 'withdrawn'
  label: string | null
  revisions: RevisionEntry[]
}

export interface RevisionsResponse {
  kind: 'price' | 'trade' | 'production'
  periods: RevisionPeriod[]
  counts: { periods: number; stored_values: number; revised: number; withdrawn: number }
  first_period: string | null
  last_period: string | null
  last_collected_at: string | null
}
