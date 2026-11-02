// Responses of /api/countries and /api/countries/{iso3} (backend/paladex/api/countries.py).
import type { Freshness, SourceBrief } from '@/lib/types'
import type {
  CountryTotal, FlowsResponse, Provider, SourceUsed, TradeFigures, TradeProv, TradeSeries,
} from '@/components/trade/types'

export type MapMetric = 'exports' | 'imports' | 'production' | 'news'

export interface CountryRefFull {
  iso3: string; iso2: string | null; m49: number | null; name_it: string; name_en: string
  region: string | null; lat: number | null; lon: number | null; priority: boolean
}

export interface Availability {
  production: boolean; exports: boolean; imports: boolean; exports_mirror: boolean; imports_mirror: boolean
  prices: boolean; news: boolean; regulations: boolean; context: boolean
}

export interface Headline extends Partial<TradeProv> {
  net_weight_kg: number | null; usd_value: number | null; unit_value_usd_per_kg: number | null
  year: number; summed_from_partners: boolean; summed_from_months: boolean
  partners_count: number | null; months_count: number | null; yoy_volume_pct: number | null
}

export interface ProductionHeadline extends TradeProv {
  value_t: number; unit: string; unit_as_published: string; year: number
}

export interface CountryListItem extends CountryRefFull {
  available: Availability
  metrics: {
    exports: Headline | null
    imports: Headline | null
    production: ProductionHeadline | null
    news_30d: { count: number; latest_at: string | null; days: number } | null
    prices_count: number
    regulations_count: number
  }
}

export interface MetricMeta {
  countries: number; years: number[]; sources: SourceUsed[]; is_demo: boolean
  data_status?: string | null; unit?: string; providers: Provider[]; days?: number
}

export interface CountriesResponse {
  countries: CountryListItem[]
  priority: string[]
  metrics: Record<MapMetric, MetricMeta>
}

// ---- profile ----

export interface ProductionPoint extends TradeProv {
  period_label: string; value: number; unit: string; flag_raw: string | null; notes: string | null
}

export interface ProductionSeries {
  source: SourceBrief | null; unit: string; frequency: string; points: ProductionPoint[]
  latest: ProductionPoint; is_demo: boolean; freshness: Freshness | null
}

export interface ProductionMetric { metric: string; series: ProductionSeries[] }

export interface MirrorRow extends TradeProv, TradeFigures {
  iso3: string; name_it: string | null; name_en: string | null; year: number; complete: boolean
  months_count: number | null; summed_from_months: boolean; link: string
}

export interface TradeFlowSection {
  available: boolean
  latest: CountryTotal | null
  series: TradeSeries[]
  excluded_partial: { source: SourceBrief | null; period_label: string; months_count: number; last_month: string }[]
  discrepancies: { period_label: string; diff_pct: number; values: { source: SourceBrief | null; net_weight_kg: number }[] }[]
  partners: FlowsResponse | null
  mirror: { declared_flow: string; rows: MirrorRow[]; count: number } | null
}

export interface PriceRow extends TradeProv {
  price_type: string; variety: string; variety_raw: string | null; market_iso3: string | null
  market_location: string | null; color_grade: string | null; organic: boolean; terms: string | null
  price_value: number; price_low: number | null; price_high: number | null; currency: string; unit: string
  price_per_kg: number; usd_per_kg: number | null; eur_per_kg: number | null; observations: number
}

export interface NewsItem {
  id: number; title: string; title_it: string | null; title_en: string | null; language: string | null
  publisher: string | null; url: string; published_at: string | null; collected_at: string | null
  snippet: string | null; summary_it: string | null; summary_en: string | null; ai_model: string | null
  relevance_score: number; duplicate_count: number; topics: string[]; source: SourceBrief | null; is_demo: boolean
}

export interface RegulationRow {
  id: number; jurisdiction: string; doc_type: string; reference: string; title: string; status: string | null
  published_at: string | null; effective_date: string | null; url: string; summary_it: string | null
  summary_en: string | null; summary_is_ai: boolean; source: SourceBrief | null; collected_at: string | null
  is_demo: boolean; match: 'mentioned' | 'jurisdiction'
}

export interface MissingItem {
  key: 'production' | 'exports' | 'imports' | 'prices' | 'news' | 'regulations' | 'context'
  category: string | null; partial_alternative: string | null; providers: Provider[]
}

export interface CountryProfile {
  country: CountryRefFull
  availability: Availability
  production: { available: boolean; metrics: ProductionMetric[]; providers: Provider[] }
  trade: { import: TradeFlowSection; export: TradeFlowSection; providers: Provider[] }
  prices: { available: boolean; groups: { price_type: string; rows: PriceRow[]; count: number; latest_period_label: string | null; link: string }[]; providers: Provider[] }
  news: { available: boolean; items: NewsItem[]; count_30d: number; days: number; link: string; providers: Provider[] }
  regulations: { available: boolean; items: RegulationRow[]; providers: Provider[] }
  context: {
    available: boolean; label_it: string; label_en: string; is_collected_data: false; varieties: string[]
    harvest: string | null; notes_it: string | null; notes_en: string | null; refs: string[]
  }
  missing: MissingItem[]
  sources: SourceUsed[]
  is_demo: boolean
  generated_at: string
  today: string
}
