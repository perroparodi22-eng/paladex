// Shared API types (mirror backend/paladex/api/*.py responses).

export type Lang = 'it' | 'en'

export interface Labelled { key: string; it: string; en: string }

export interface CountryRef {
  iso3: string; iso2: string; name_it: string; name_en: string; priority: boolean
  region: string | null; lat: number | null; lon: number | null
}

export interface Meta {
  flags: {
    llm_enabled: boolean; llm_provider: string | null; comtrade_key: boolean
    usda_mmn_key: boolean; usda_nass_key: boolean; scheduler_enabled: boolean
  }
  show_demo: boolean
  language: Lang
  countries: CountryRef[]
  varieties: (Labelled & { core: boolean })[]
  price_types: Labelled[]
  data_status: Labelled[]
  reliability: Labelled[]
}

export type FreshnessStatus = 'current' | 'aging' | 'stale' | 'never' | 'unknown'

export interface Freshness { status: FreshnessStatus; age_days: number | null; reference_date: string | null }

export interface SourceBrief { key: string; name: string; name_en?: string | null; publisher: string | null; reliability: string; homepage: string | null }

export interface SourceInfo extends SourceBrief {
  kind: string; category: string; country_iso3: string | null
  expected_update: string | null; expected_update_en?: string | null; expected_max_age_days: number | null; terms_note: string | null
  enabled: boolean; requires_key: string | null; key_missing: boolean
  last_run_at: string | null; last_run_status: string | null; last_success_at: string | null
  last_new_data_at: string | null; latest_published_at: string | null; latest_period_label: string | null
  hours_since_check: number | null; freshness: Freshness; counts: Record<string, number>
}

export interface CollectState {
  running: boolean
  started_at: string | null
  keys: string[] | null
  results: unknown
  /** First minutes after installation (GET /collect/status only). */
  first_run?: FirstRunState
}

export interface FirstRunState {
  has_data: boolean
  /** Collection runs finished on this computer (since the starter data was merged), by status. */
  local_runs: Record<string, number>
  /** Real data shipped with the app and merged at start-up, if any. */
  starter: { built_at: string | null; data_collected_until: string | null; imported_at: string | null } | null
}

/** Provenance block that every fact row carries in API responses. */
export interface Provenance {
  source: SourceBrief | null
  source_url: string | null
  published_at: string | null
  collected_at: string | null
  period_label: string
  period_start: string
  period_end: string
  data_status: string
  reliability: string
  is_demo: boolean
}
