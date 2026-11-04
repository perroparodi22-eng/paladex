// Mirrors backend/paladex/api/regulations.py responses.
import type { Freshness, SourceBrief } from '@/lib/types'

export type Jurisdiction = 'EU' | 'US'
export type MeasureType = 'mfn' | 'preference' | 'trq_in' | 'trq_out' | 'antidumping' | 'surcharge' | 'other'

export interface Quota {
  order_number: string
  volume_kg: number | null
  balance_kg: number | null
  status: string | null
  fill_pct: number | null
  period_start: string | null
  period_end: string | null
  last_allocation_date: string | null
  critical: string | null
  shared_by_group: boolean | null
  note: string | null
}

export interface DutyRow {
  id: number
  series_key: string
  jurisdiction: Jurisdiction
  origin_iso3: string
  scope: 'origin' | 'general'
  hs_code: string
  measure_type: MeasureType
  measure_code: string | null
  description: string | null
  duty_text: string | null
  ad_valorem_pct: number | null
  specific_amount: number | null
  specific_unit: string | null
  specific_currency: string | null
  quota: Quota | null
  valid_from: string | null
  valid_to: string | null
  legal_reference: string | null
  legal_url: string | null
  consult_url: string | null
  source_url: string | null
  published_at: string | null
  as_of: string | null
  collected_at: string | null
  last_seen_at: string | null
  revision: number
  is_current: boolean
  supersedes_id: number | null
  needs_review: boolean
  review_reason: string | null
  /** /regulations/duties only: the latest run of the source could not re-confirm this layer, which
   *  keeps its older `as_of` and values (e.g. a quota balance or a Chapter 99 range that failed). */
  stale?: boolean
  extra: Record<string, unknown> | null
  source: SourceBrief | null
  reliability: string
  data_status: string
  is_demo: boolean
}

export interface AdCaseDoc {
  id: number
  reference: string
  title: string
  doc_type: string
  published_at: string | null
  url: string
  is_demo: boolean
}

export interface AdCase {
  case_number: string | null
  product: string
  fr_search_url: string
  documents_total: number
  documents: AdCaseDoc[]
}

export interface OriginDuties {
  iso3: string
  name_it: string | null
  name_en: string | null
  priority: boolean
  eu: {
    rows: DutyRow[]
    general_ids: number[]
    has_own_mfn: boolean
    /** Oldest `as_of` of the layers shown in the cell (every one was confirmed at least then). */
    as_of: string | null
    /** Newest `as_of` of the layers shown in the cell. */
    as_of_latest: string | null
    review_count: number
    links: { taric: string }
  }
  us: {
    rows: DutyRow[]
    general_ids: number[]
    domestic: boolean
    as_of: string | null
    as_of_latest: string | null
    review_count: number
    links: { hts: string }
    ad_case: AdCase | null
  }
}

export interface JurisdictionStatus {
  source: SourceBrief | null
  terms_note: string | null
  enabled: boolean
  last_run_at: string | null
  last_run_status: string | null
  last_success_at: string | null
  freshness: Freshness | null
  as_of: string | null
  count: number
  review_count: number
  general: DutyRow[]
}

export interface DutiesResponse {
  origins: OriginDuties[]
  jurisdictions: Record<Jurisdiction, JurisdictionStatus>
  ad_cases: { origin_iso3: string; case_number: string | null; product: string; fr_search_url: string }[]
  has_data: boolean
}

export interface DutySeries {
  series_key: string
  jurisdiction: Jurisdiction
  origin_iso3: string
  scope: 'origin' | 'general'
  measure_type: MeasureType
  measure_code: string | null
  current: boolean
  revisions: DutyRow[]
}

export interface DutyHistory {
  origin: string
  name_it: string | null
  name_en: string | null
  series: DutySeries[]
  ad_case: AdCase | null
  links: { taric: string; hts: string }
}

export interface RegulationDoc {
  id: number
  reference: string
  jurisdiction: string
  doc_type: string
  title: string
  status: string | null
  published_at: string | null
  effective_date: string | null
  url: string
  source_url: string
  countries: string[]
  summary_en: string | null
  summary_it: string | null
  summary_is_ai: boolean
  collected_at: string | null
  source: SourceBrief | null
  reliability: string | null
  data_status: string
  is_demo: boolean
  ad_cases: { origin_iso3: string; case_number: string | null; product: string }[]
}

export interface Facet { key: string; count: number }

export interface DocSource extends SourceBrief {
  enabled: boolean
  last_run_at: string | null
  last_run_status: string | null
  last_success_at: string | null
  latest_published_at: string | null
  freshness: Freshness
}

export interface RegulationsResponse {
  total: number
  page: number
  page_size: number
  pages: number
  items: RegulationDoc[]
  facets: { jurisdictions: Facet[]; doc_types: Facet[]; countries: Facet[] }
  sources: DocSource[]
  last_collected_at: string | null
}

export interface DocFilterState {
  q: string
  jurisdiction: string
  docType: string
  country: string
}
