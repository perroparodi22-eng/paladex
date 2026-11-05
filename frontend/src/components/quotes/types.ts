// Mirrors backend/paladex/api/quotes.py and services/landed_cost.py responses.
import type { AdCase, DutyRow, Facet, Quota } from '@/components/regulations/types'
import type { Freshness, SourceBrief } from '@/lib/types'

export type QuoteStatus = 'active' | 'expiring' | 'expired' | 'archived'
export type Incoterm = 'EXW' | 'FCA' | 'FOB' | 'CFR' | 'CIF' | 'DAP' | 'DDP'
export type CostKind = 'origin' | 'port' | 'broker' | 'inland' | 'bank' | 'other'
export type CostBasis = 'per_container' | 'per_kg' | 'total' | 'pct_goods'
export type FreightBasis = 'per_container' | 'per_kg' | 'total'
export type Destination = 'ITA' | 'USA'
export type FxMode = 'received' | 'today'
export type PriceUnit = 'kg' | 'lb'
export type CompareBasis = 'conservative' | 'best'

export interface CostItem {
  kind: CostKind
  amount: number
  basis: CostBasis
  currency: string | null
  note: string | null
}

export interface Quote {
  id: number
  supplier_name: string
  origin_iso3: string
  variety: string
  variety_note: string | null
  /** As quoted, per `price_unit`. */
  price: number
  price_unit: PriceUnit
  price_per_kg: number
  currency: string
  quantity_kg: number | null
  packaging: string | null
  incoterm: Incoterm | null
  incoterm_place: string | null
  shipping_cost: number | null
  shipping_cost_currency: string | null
  shipping_cost_basis: FreightBasis | null
  insurance_pct: number | null
  duty_pct: number | null
  other_costs: number | null
  other_costs_currency: string | null
  cost_items: CostItem[]
  destination: Destination
  date_received: string
  valid_until: string | null
  days_to_expiry: number | null
  notes: string | null
  archived: boolean
  status: QuoteStatus
  created_at: string | null
  updated_at: string | null
  is_demo: boolean
  data_status: string
  reliability: string
}

/** One amount in EUR and USD; null = no conversion available (never estimated). */
export interface Amount { eur: number | null; usd: number | null }

export type FlagKind = 'missing' | 'info' | 'warning'
export interface Flag { code: string; kind: FlagKind; params?: Record<string, unknown> }

export interface Rate {
  ad_valorem_pct: number | null
  specific_amount: number | null
  specific_unit: string | null
  specific_currency: string | null
  duty_text: string | null
}

export interface FxRateUsed { currency: string; per_eur: number; rate_date: string }

export interface Headline {
  eur_per_kg_min: number | null
  eur_per_kg_max: number | null
  usd_per_kg_min: number | null
  usd_per_kg_max: number | null
  alternatives: boolean
  complete: boolean
  missing: string[]
  warnings: string[]
}

export interface ScenarioCompact {
  key: string
  kind: string
  role: 'in_quota' | 'out_of_quota' | 'applicable'
  available: boolean
  unavailable_reason: string | null
  rate: Rate
  quota: Quota | null
  total_per_kg: Amount | null
}

export interface LandedCompact {
  destination: Destination
  headline: Headline
  fx: { date: string; rates: FxRateUsed[]; missing: string[] }
  flags: Flag[]
  scenarios: ScenarioCompact[]
}

export interface QuoteListItem extends Quote { landed: LandedCompact }

export interface QuotesList {
  items: QuoteListItem[]
  total: number
  counts: Record<QuoteStatus, number>
  total_all: number
  facets: { origins: Facet[]; varieties: Facet[]; suppliers: Facet[] }
  today: string
  expiring_days: number
  fx_mode: FxMode
}

export interface LineFx { currency: string; per_eur?: number; rate_date?: string; missing: boolean }

export type LineStatus = 'ok' | 'included' | 'missing' | 'not_computable' | 'subtotal'

export interface Line {
  key: string
  index?: number | null
  status: LineStatus
  per_kg: Amount | null
  input: Record<string, unknown> | null
  source: { kind: 'quote'; date: string } | null
  fx: LineFx | null
}

export interface Totals { per_kg: Amount; per_drum: Amount; per_container: Amount; quantity: Amount | null }

export interface Scenario {
  key: string
  kind: string
  role: 'in_quota' | 'out_of_quota' | 'applicable'
  available: boolean
  unavailable_reason: string | null
  rate: Rate
  measure: DutyRow | null
  stack: DutyRow[]
  duty: Amount | null
  notes: { code: string; params?: Record<string, unknown> }[]
  total: Totals | null
}

export interface DutyInfo {
  jurisdiction: 'EU' | 'US'
  on: string
  has_data: boolean
  as_of: string | null
  as_of_latest: string | null
  applied: DutyRow[]
  review: DutyRow[]
  review_other_origins?: number
  not_applied: DutyRow[]
  origin_covered: boolean
  source: SourceBrief | null
  links: { taric?: string; hts?: string }
  ad_case: (Partial<AdCase> & { origin_iso3: string; case_number: string | null; product: string; fr_search_url: string }) | null
  us: { special_text: string | null; column2_text: string | null; column2_note: string | null } | null
}

export interface Landed {
  destination: Destination
  jurisdiction: 'EU' | 'US'
  incoterm: Incoterm | null
  incoterm_rule: { origin_costs: boolean; freight: boolean; insurance: boolean; duty: boolean } | null
  calc_date: string
  fx: { mode: FxMode; date: string; rates: FxRateUsed[]; missing: string[]; source: SourceBrief | null; source_url: string | null }
  assumptions: { drum_kg: number; container_kg: number; quantity_kg: number | null; containers: number | null }
  lines: Line[]
  after_duty: Line[]
  scenarios: Scenario[]
  headline: Headline
  flags: Flag[]
  duty: DutyInfo
}

export interface RefRow {
  id: number
  source: SourceBrief | null
  price_type: string
  origin_iso3: string | null
  market_iso3: string | null
  market_location: string | null
  variety: string | null
  variety_raw: string | null
  color_grade: string | null
  organic: boolean
  terms: string | null
  price_low: number | null
  price_high: number | null
  price_value: number | null
  currency: string
  unit: string
  price_per_kg: number | null
  eur_per_kg: number | null
  usd_per_kg: number | null
  fx_basis: string | null
  fx_date: string | null
  volume_kg: number | null
  period_label: string
  period_start: string
  period_end: string
  frequency: string | null
  published_at: string | null
  collected_at: string | null
  source_url: string | null
  data_status: string
  reliability: string
  is_demo: boolean
  age_days: number
  freshness: Freshness | null
  variety_match?: boolean
}

export type RefKey = 'eu_import' | 'us_importer' | 'it_wholesale'

export interface RefBlock {
  key: RefKey
  price_type: string
  rows: RefRow[]
  not_applicable: boolean
  variety_match?: boolean
  min_volume_kg?: number
  variety_generic?: boolean
}

export interface MarketReference { origin_iso3: string; variety: string; blocks: RefBlock[] }

export interface QuoteDetail { quote: Quote; landed: Landed; market: MarketReference }

export interface CompareItem {
  quote: Quote
  landed: LandedCompact
  value_eur_per_kg: number | null
  value_usd_per_kg: number | null
  scenario: { kind: string; rate: Rate; quota: Quota | null } | null
  rank: number | null
  diff_eur_per_kg: number | null
  diff_pct: number | null
  diff_eur_per_container: number | null
  diff_usd_per_kg: number | null
}

export interface CompareResponse {
  basis: CompareBasis
  fx_mode: FxMode
  container_kg: number
  drum_kg: number
  items: CompareItem[]
  best_id: number | null
  mixed_destinations: boolean
  mixed_demo: boolean
  incomplete: number[]
}

export interface QuotesMeta {
  currencies: string[]
  fx_newest: string | null
  incoterms: Incoterm[]
  incoterm_rules: Record<Incoterm, { origin_costs: boolean; freight: boolean; insurance: boolean; duty: boolean }>
  cost_kinds: CostKind[]
  cost_bases: CostBasis[]
  freight_bases: FreightBasis[]
  destinations: Destination[]
  drum_kg: number
  container_kg: number
  lb_kg: number
  expiring_days: number
  today: string
}

/** Body of POST /quotes, PUT /quotes/{id} and POST /quotes/calculate. */
export interface QuoteBody {
  supplier_name: string | null
  origin_iso3: string
  variety: string
  variety_note: string | null
  price: number
  price_unit: PriceUnit
  currency: string
  quantity_kg: number | null
  packaging: string | null
  incoterm: Incoterm | null
  incoterm_place: string | null
  shipping_cost: number | null
  shipping_cost_currency: string | null
  shipping_cost_basis: FreightBasis | null
  insurance_pct: number | null
  duty_pct: number | null
  other_costs: number | null
  other_costs_currency: string | null
  cost_items: CostItem[]
  destination: Destination
  date_received: string
  valid_until: string | null
  notes: string | null
}
