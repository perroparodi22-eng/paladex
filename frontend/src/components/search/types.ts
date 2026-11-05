// Response of GET /api/search (backend: api/search.py).
import type { Freshness, SourceBrief } from '@/lib/types'

export interface CountryHit {
  iso3: string; name_it: string; name_en: string; region: string | null; priority: boolean
  has_prices: boolean; target: string; external: false
}

export interface VarietyHit { key: string; it: string; en: string; core: boolean; has_prices: boolean; target: string; external: false }

export interface PriceHit {
  origin_iso3: string | null; origin_name_it: string | null; origin_name_en: string | null
  variety: string; variety_it: string; variety_en: string; price_types: string[]
  observations: number; sources: number; latest_period_end: string | null; latest_period_label: string | null
  is_demo: boolean; target: string; external: false
}

export interface NewsHit {
  id: number; title: string; title_it: string | null; title_en: string | null; title_is_ai: boolean
  publisher: string | null; language: string | null; published_at: string | null; collected_at: string | null
  url: string; snippet: string | null; summary_it: string | null; summary_en: string | null; summary_is_ai: boolean
  countries: string[]; source: SourceBrief | null; is_demo: boolean; target: string; external: false
}

export interface ReportHit {
  id: number; title: string; period_label: string | null; published_at: string | null; collected_at: string | null
  url: string; file_url: string | null; summary_it: string | null; summary_en: string | null; summary_is_ai: boolean
  excerpt: string | null; source: SourceBrief | null; is_demo: boolean; target: string; external: true
}

export interface RegulationHit {
  id: number; title: string; reference: string; jurisdiction: string; doc_type: string; status: string | null
  published_at: string | null; effective_date: string | null; url: string
  summary_it: string | null; summary_en: string | null; summary_is_ai: boolean
  source: SourceBrief | null; is_demo: boolean; target: string; external: true
}

export interface SourceHit {
  key: string; name: string; publisher: string | null; category: string; reliability: string; enabled: boolean
  homepage: string | null; last_run_status: string | null; latest_published_at: string | null; freshness: Freshness
  target: string; external: false
}

export interface GroupMap {
  countries: CountryHit; varieties: VarietyHit; prices: PriceHit; news: NewsHit
  reports: ReportHit; regulations: RegulationHit; sources: SourceHit
}
export type GroupKey = keyof GroupMap

export interface SearchGroup<K extends GroupKey = GroupKey> { key: K; items: GroupMap[K][]; total: number; see_all: string | null }

export interface SearchResponse {
  query: string
  tokens: string[]
  total: number
  groups: SearchGroup[]
  suggestions: { countries: CountryHit[]; varieties: VarietyHit[] } | null
}
