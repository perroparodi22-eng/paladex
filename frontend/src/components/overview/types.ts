// Response of GET /api/overview (backend/paladex/api/overview.py). Page-specific types.
import type { Freshness, FreshnessStatus, SourceBrief } from '@/lib/types'

export interface Provider { key: string; name: string; publisher: string | null; enabled: boolean; last_run_status: string | null }

export interface SourceWithFreshness extends SourceBrief { freshness: Freshness }

export interface ItemFreshness { status: FreshnessStatus; age_days: number | null; reference_date: string | null; expected_max_age_days?: number | null }

export interface StatusBlock {
  counts: {
    total: number; disabled: number; current: number; aging: number; stale: number; never: number
    unknown: number; failed: number; offline: number; skipped: number
  }
  last_check_at: string | null
  newest_data_at: string | null
  newest_published_at: string | null
  offline: boolean
  collection_running: boolean
  never_collected: boolean
  sources: {
    key: string; name: string; publisher: string | null; category: string; freshness: Freshness
    last_run_status: string | null; last_run_at: string | null; latest_published_at: string | null
  }[]
  link: string
}

export interface BriefingBullet {
  kind: 'price' | 'report' | 'trade' | 'news' | 'text' | string
  text: string
  source: SourceBrief | null
  publisher: string | null
  date: string | null
  period_label: string | null
  url: string | null
  link: string | null
  is_demo: boolean
  is_ai: boolean
  data_status: string | null
  change_pct?: number | null
}

export interface BriefingBlock {
  generator: string
  is_ai: boolean
  stored: boolean
  briefing_date: string
  generated_at: string
  bullets: BriefingBullet[]
  rules: { key: string; text: string; count?: number }[]
  empty_message: string | null
  has_any_data: boolean
  is_demo?: boolean
  providers: Provider[]
  sources: SourceWithFreshness[]
}

export interface PriceTile {
  id: string
  label: string
  origin_iso3: string | null
  origin_label: string | null
  variety: string
  variety_raw: string | null
  price_type: string
  market_iso3: string | null
  market_location: string | null
  color_grade: string | null
  organic: boolean
  terms: string | null
  usd_per_kg: number | null
  eur_per_kg: number | null
  price_per_kg: number
  currency: string
  price_value: number
  price_low: number | null
  price_high: number | null
  unit: string
  fx_date: string | null
  mom_pct: number | null
  mom_period_label: string | null
  yoy_pct: number | null
  yoy_period_label: string | null
  spark: { period_label: string; value: number }[]
  freshness: ItemFreshness
  source: SourceBrief | null
  source_url: string | null
  published_at: string | null
  collected_at: string | null
  period_label: string
  period_start: string
  period_end: string
  frequency: string
  data_status: string
  reliability: string
  is_demo: boolean
  link: string
}

export interface PricesBlock {
  items: PriceTile[]
  price_types: string[]
  mixed_price_types: boolean
  series_available: number
  updated_at: string | null
  latest_published_at: string | null
  sources: SourceWithFreshness[]
  providers: Provider[]
  link: string
}

export interface NewsItem {
  id: number
  title: string
  original_title: string
  title_is_ai: boolean
  summary: string | null
  summary_is_ai: boolean
  publisher: string | null
  source: SourceBrief | null
  url: string
  image_url: string | null
  language: string | null
  published_at: string | null
  collected_at: string | null
  countries: string[]
  topics: string[]
  relevance_score: number
  duplicate_count: number
  ai_model: string | null
  is_demo: boolean
}

export interface NewsBlock {
  items: NewsItem[]
  min_relevance: number
  window_days: number
  collected_last_7_days: number
  total_stored: number
  updated_at: string | null
  sources: SourceWithFreshness[]
  providers: Provider[]
  link: string
}

export interface ReportItem {
  id: number
  title: string
  period_label: string | null
  published_at: string | null
  collected_at: string | null
  url: string
  source: SourceBrief | null
  summary: string | null
  summary_is_ai: boolean
  is_new: boolean
  is_demo: boolean
  freshness: ItemFreshness
}

export interface ReportsBlock {
  items: ReportItem[]
  new_count: number
  recent_days: number
  updated_at: string | null
  latest_published_at: string | null
  sources: SourceWithFreshness[]
  providers: Provider[]
  link: string
}

export interface TradeRow {
  iso3: string
  name: string
  net_weight_kg: number | null
  usd_value: number | null
  unit_value_usd_per_kg: number | null
  prev_net_weight_kg: number | null
  yoy_pct: number | null
  partners_count: number | null
  is_demo: boolean
  data_status: string
  link: string
}

export interface TradeSide {
  basis: 'world_rows' | 'sum_partners' | 'mirror_imports'
  items: TradeRow[]
  count: number
  published_at: string | null
  updated_at: string | null
  is_demo: boolean
  data_status: string | null
  source_url: string | null
  source: SourceBrief | null
  period_label: string | null
  prev_period_label: string | null
  partial_latest: boolean
  flow: 'import' | 'export'
  freshness: ItemFreshness
  reporters_count?: number
}

export interface TradeBlock {
  available: boolean
  frequency: 'A' | 'M' | null
  importers: TradeSide | null
  exporters: TradeSide | null
  updated_at: string | null
  latest_published_at?: string | null
  sources: SourceWithFreshness[]
  providers: Provider[]
  link: string
}

export interface CountryReason { kind: 'news' | 'price' | 'trade'; text: string; link: string; change_pct?: number; is_demo?: boolean }

export interface CountryActivity {
  iso3: string
  name: string
  score: number
  components: { news: number; price_mom_pct: number | null; new_trade_period: string | null }
  reasons: CountryReason[]
  link: string
}

export interface CountriesBlock {
  items: CountryActivity[]
  priority_count: number
  updated_at: string | null
  providers: Provider[]
  link: string
}

export interface AlertItem {
  id: number; severity: 'info' | 'warning' | 'critical' | string; triggered_at: string
  title: string; body: string | null; link: string | null; ref_type: string | null; ref_id: number | null
}

export interface AlertsBlock { unread: number; items: AlertItem[]; updated_at: string | null; link: string }

export interface QualityBlock { open: number; by_severity: Record<string, number>; updated_at: string | null; link: string }

export interface OverviewData {
  lang: string
  today: string
  generated_at: string
  show_demo: boolean
  demo_rows_present: boolean
  status: StatusBlock
  briefing: BriefingBlock
  prices: PricesBlock
  news: NewsBlock
  reports: ReportsBlock
  trade: TradeBlock
  countries: CountriesBlock
  alerts: AlertsBlock
  quality: QualityBlock
}
