// Response types for /api/news* (backend: paladex/api/news.py, services/news.py).
import type { Lang, SourceBrief } from '@/lib/types'

export type TopicKey =
  | 'prices' | 'production' | 'trade' | 'adulteration' | 'quality' | 'policy'
  | 'tariffs' | 'import_restrictions' | 'companies' | 'colony_health' | 'weather'

export type RelevanceLevel = 'high' | 'medium' | 'low'

/** What to show in one UI language (the backend decides; the UI never guesses). */
export interface DisplayBlock {
  /** Original title when the article is already in this language or no AI translation exists. */
  title: string
  /** The title shown is an AI translation: show <AiBadge> and the original title. */
  title_is_ai: boolean
  /** Article in another language without an AI title yet ("Traduci" when AI is configured). */
  needs_translation: boolean
  /** AI summary in this language. */
  summary: string | null
  summary_is_ai: boolean
  /** The publisher's own excerpt, original language ("Estratto della fonte"). */
  excerpt: string | null
}

export interface DuplicateOutlet {
  id: number
  publisher: string | null
  url: string
  published_at: string | null
  collected_at: string | null
  language: string | null
  source_key: string | null
  source_name: string | null
  source_name_en?: string | null
}

export interface NewsItem {
  id: number
  title: string
  url: string
  source_url: string
  canonical_url: string
  publisher: string | null
  language: string | null
  published_at: string | null
  collected_at: string
  image_url: string | null
  snippet: string | null
  countries: string[]
  topics: TopicKey[]
  relevance_score: number
  relevance_level: RelevanceLevel
  relevance_reason: string | null
  relevance_reason_it: string | null
  relevance_reason_en: string | null
  title_it: string | null
  title_en: string | null
  summary_it: string | null
  summary_en: string | null
  summary_is_ai: boolean
  ai_model: string | null
  ai_processed_at: string | null
  display: Record<Lang, DisplayBlock>
  duplicate_of_id: number | null
  duplicate_of: { id: number; title: string; publisher: string | null; url: string; published_at: string | null } | null
  duplicate_count: number
  duplicate_outlets: DuplicateOutlet[]
  source: SourceBrief | null
  reliability: string | null
  data_status: 'published'
  is_demo: boolean
}

export interface NewsDetail extends NewsItem {
  duplicates: (DuplicateOutlet & { title: string; is_this: boolean })[]
  llm_enabled: boolean
}

export interface CountryFacet { key: string; count: number; name_it: string; name_en: string; origin_of_interest: boolean }
export interface TopicFacet { key: TopicKey; it: string; en: string; count: number }
export interface SourceFacet { key: string; name: string; name_en?: string | null; publisher: string | null; reliability: string; count: number }
export interface LanguageFacet { key: string; count: number }

export interface NewsFacets {
  countries: CountryFacet[]
  topics: TopicFacet[]
  sources: SourceFacet[]
  languages: LanguageFacet[]
}

export interface NewsListResponse {
  items: NewsItem[]
  total: number
  page: number
  page_size: number
  pages: number
  sort: 'date' | 'relevance'
  filters: {
    q: string | null; country: string[]; topic: string[]; source: string[]
    from: string | null; to: string | null; lang: string[]; min_relevance: number; include_duplicates: boolean
  }
  facets: NewsFacets
  llm_enabled: boolean
  updated: {
    last_checked_at: string | null
    last_collected_at: string | null
    sources_total: number
    sources_enabled: number
  }
}

export type PeriodPreset = 'today' | '7d' | '30d' | 'all'
export type NewsSort = 'date' | 'relevance'

/** Filter state kept in the URL (/notizie?q=…&country=ARG,CHN&topic=prices…). */
export interface NewsFilterState {
  q: string
  countries: string[]
  topics: string[]
  sources: string[]
  langs: string[]
  period: PeriodPreset
  /** "Solo rilevanti per Parodi" (default on = medium relevance or higher). */
  relevantOnly: boolean
  sort: NewsSort
}
