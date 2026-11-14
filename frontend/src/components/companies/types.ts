// Answers of /api/companies and /api/companies/{iso3} (backend/paladex/api/companies.py).
import type { FreshnessStatus } from '@/lib/types'

export type AvailabilityStatus = 'figures' | 'register' | 'unavailable' | 'not_published' | 'unverified'
export const STATUS_ORDER: AvailabilityStatus[] = ['figures', 'register', 'unavailable', 'not_published', 'unverified']

export interface Availability {
  status: AvailabilityStatus
  authority: string
  url: string | null
  reason_it: string
  reason_en: string
  source_keys: string[]
  roles: string[]
  checked_on: string | null
}

export interface CompanyCountryRef {
  iso3: string
  name_it: string
  name_en: string
  region: string | null
  priority: boolean
}

export interface OverviewCountry extends CompanyCountryRef, Availability {
  companies: Partial<Record<string, number>>
  latest_period: string | null
  /** companies found on the web for this country (not official, shown apart) */
  web_companies?: number
}

/** A honey business found on the web (backend/paladex/reference/companies_web.py): not official. */
export interface WebCompany {
  name: string
  role: 'exporter' | 'packer' | 'cooperative' | 'importer' | 'trader'
  city: string | null
  website: string
  source_url: string | null
  what_it: string | null
  what_en: string | null
}

export interface WebCompanies { searched_on: string | null; companies: WebCompany[] }

export interface CompanySource {
  key: string
  name: string
  publisher: string | null
  reliability: string
  homepage: string | null
  freshness: { status: FreshnessStatus; age_days?: number | null; reference_date?: string | null }
  expected_update: string | null
  expected_update_en: string | null
  terms_note: string | null
  latest_period_label: string | null
  last_success_at: string | null
}

export interface CompaniesOverview {
  checked_on: string
  web_searched_on?: string | null
  countries: OverviewCountry[]
  status_counts: Record<AvailabilityStatus, number>
  sources: CompanySource[]
}

export interface PeriodInfo {
  label: string
  start: string
  end: string
  frequency: string
  data_status: string
  months_covered: [number, number] | null
  running_year: boolean
}

export interface FigureCell {
  value: number | null
  value_min: number | null
  value_max: number | null
  volume_kg: number | null
  data_status: string
  revision: number
  share_pct?: number
}

export interface FigureCompany {
  name: string
  location: string | null
  values: Record<string, FigureCell>
  rank_in_ref: number | null
}

export interface RegisterCompany {
  name: string
  location: string | null
  periods: string[]
  latest_period: string
}

interface ListBase {
  role: 'exporter' | 'importer' | 'registered_exporter'
  hs_code: string
  source: CompanySource | null
  source_url: string | null
  web_url: string | null
  published_at: string | null
  collected_at: string | null
  last_seen_at: string | null
  reliability: string
  is_demo: boolean
  notes: string | null
  company_count: number
}

export interface FiguresList extends ListBase {
  measure_kind: 'exact_value' | 'value_band' | 'exact_volume' | 'rank'
  periods: PeriodInfo[]
  ref_period: string | null
  national_totals: Record<string, number>
  companies: FigureCompany[]
  currency: string | null
  value_basis: string | null
}

export interface RegisterList extends ListBase {
  measure_kind: 'none'
  periods: string[]
  /** Unit of `periods`: 'M' monthly lists (HMRC), 'A' yearly lists (Canada's CID), 'register' (an
   * official register, e.g. India's EIC: the months it was seen listing the company, not a period of trade). */
  frequency?: string
  first_period: string
  latest_period: string
  companies: RegisterCompany[]
}

export type CompanyList = FiguresList | RegisterList

export interface CompaniesCountry {
  country: CompanyCountryRef
  availability: Availability
  checked_on: string
  lists: CompanyList[]
  /** companies found on the web: never mixed with `lists` */
  web?: WebCompanies | null
}
