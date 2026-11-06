// "Other sources (non-official)": the `web_findings` block of /api/countries/{iso3} and the AI web
// search settings of /api/findings/ai (backend/paladex/api/findings.py).

export type FindingMetric = 'production' | 'exports' | 'imports' | 'hives' | 'producer_price' | 'export_price'
export type FindingStatus = 'official_final' | 'official_provisional' | 'official_estimate' | 'forecast' | 'estimate' | 'reported'

export interface WebFinding {
  id: number
  country_iso3: string
  metric: FindingMetric
  period_label: string
  period_start: string
  period_end: string
  value: number | null
  unit: string
  value_as_published: string
  value_low?: number | null
  value_high?: number | null
  status: FindingStatus
  kind: string
  is_official: boolean
  publisher: string
  source_url: string
  source_title: string | null
  published_at: string | null
  language: string | null
  quote: string
  also_reported_by: (string | { url?: string; publisher?: string; title?: string })[]
  verified_at: string | null
  last_check: { at: string | null; ok: boolean | null; reason: string | null; detail: string | null; doc_type: string | null; number_in_quote: boolean | null } | null
  found_by: 'seed' | 'ai_web_search' | null
  ai_model: string | null
  collected_at: string | null
  revision: number
  notes: string | null
  is_demo: boolean
}

export interface WebFindingsBlock {
  available: boolean
  count: number
  metrics: { metric: FindingMetric; findings: WebFinding[]; count: number }[]
  not_found: { by: 'seed' | 'ai_web_search'; searched: string; result: string; on: string | null }[]
  seed_compiled_on: string | null
  note_it: string
  note_en: string
  is_official_statistics: false
}

export interface AiRun {
  at: string
  model?: string
  skipped?: string
  provider?: string
  max_searches?: number
  requests?: number
  searches?: number
  input_tokens?: number
  output_tokens?: number
  cost_usd?: number
  cost_known?: boolean
  countries?: { iso3: string; searches: number; proposed: number; stored: number }[]
  proposed?: number
  stored?: number
  error?: string | null
}

export interface AiEstimate {
  known: boolean
  model: string
  model_label?: string
  max_searches: number
  prices_checked_on: string
  prices_source: string
  web_search_usd_per_1000: number
  input_usd_per_mtok?: number
  output_usd_per_mtok?: number
  long_context?: { over: number; input: number; output: number } | null
  assumed_input_tokens_per_search: number
  assumed_output_tokens_per_search: number
  runs_per_month: number
  per_search_usd?: number
  per_run_usd?: number
  per_month_usd?: number
}

export interface AiStatus {
  enabled: boolean
  enabled_by: 'setting' | 'env' | 'default'
  max_searches: number
  max_searches_limit: number
  searches_per_country: number
  provider: 'anthropic'
  configured_provider: string
  model: string
  unavailable: 'no_key' | 'provider_not_supported' | null
  will_run: boolean
  estimate: AiEstimate
  runs: AiRun[]
  openai_supported: false
}
