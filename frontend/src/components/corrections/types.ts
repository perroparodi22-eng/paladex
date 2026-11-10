// Corrections made by a person (backend/paladex/api/corrections.py, services/corrections*.py).

export type CorrTable = 'price_observations' | 'trade_flows' | 'production_stats'
export type CorrKind = 'value_correction' | 'flag_wrong' | 'note' | 'revert'
export type CorrStatus = 'applied' | 'reverted' | 'superseded_by_source' | 'confirmed_by_source' | 'conflict' | 'waiting'
  | 'replaced' | 'recorded' | string

/** The `correction` object every corrected figure carries in the API answers. */
export interface CorrectionBrief {
  event_id: string
  author: string | null
  created_at: string | null
  reason: string | null
  field?: string | null
  official_value: number | null
  corrected_value?: number | null
  unit: string | null
  currency: string | null
  official_per_kg?: number | Record<string, number | null> | null
  /** trade sums: how many corrected rows, and whether the figure adds up other rows too */
  rows?: number
  part_of_total?: boolean
}

/** A figure a person can correct: one stored row, and what it shows now (in its own unit). */
export interface FigureRef {
  table: CorrTable
  row_id: number
  /** what the figure is, in words ("Argentina · prezzo all'ingrosso negli USA · set 2026") */
  label: string
  value: number | null
  unit: string | null
  currency: string | null
  field?: 'net_weight_kg' | 'value' | null
  country_iso3?: string | null
  period_label?: string | null
  /** the figure as shown on screen when that differs from the stored row (EUR/kg for a USD/lb price):
   * what the person types is read in this unit and currency, and the backend converts it */
  shown?: { value: number | null; unit: string | null; currency: string | null } | null
  /** a figure that is the average of a few stored rows of one period (two USDA lines of the same
   * month): fixing it fixes each of them; `row_id` is then the first */
  row_ids?: number[] | null
}

export interface CorrectionEvent {
  event_id: string
  kind: CorrKind
  created_at: string | null
  author: string | null
  made_here: boolean
  origin: string | null
  target: {
    table: CorrTable | null; source_key: string | null; series_key: string | null; period_label: string | null
    unit: string | null; currency: string | null; field: string | null; country_iso3: string | null; label: string | null
    row_id: number | null
  } | null
  official_value: number | null
  corrected_value: number | null
  entered: { value?: number | null; low?: number | null; high?: number | null; unit?: string | null; currency?: string | null } | null
  normalized: Record<string, unknown> | null
  reverts_event_id: string | null
  reason: string | null
  text: string | null
  ai_interpretation: Record<string, unknown> | null
  status: CorrStatus
  status_detail: Record<string, unknown> | null
  applied_row_id: number | null
  issue_id: number | null
  revertible: boolean
  sync: { state: 'pending_sync' | 'synced' | 'received' | string | null; synced_at: string | null; error: string | null }
}

export interface CorrectionsList {
  total: number
  items: CorrectionEvent[]
  counts: Record<string, number>
  pending_sync: number
  author: string
}

export interface CreateBody {
  kind: 'value_correction' | 'flag_wrong' | 'note'
  target?: { table: CorrTable; row_id: number }
  value?: number | string | null
  low?: number | string | null
  high?: number | string | null
  unit?: string | null
  currency?: string | null
  field?: 'net_weight_kg' | 'value' | null
  reason?: string | null
  text?: string | null
  country_iso3?: string | null
  ai_interpretation?: Record<string, unknown> | null
}

export interface Candidate {
  table: CorrTable
  row_id: number
  source: { key: string; name: string; name_en?: string | null; publisher: string | null; reliability: string; homepage: string | null } | null
  series_key?: string
  period_label?: string | null
  label: string
  field: string
  current: { value: number | null; unit: string | null; currency: string | null; low?: number | null; high?: number | null; data_status?: string }
  correction: CorrectionBrief | null
  matches_old_value: boolean
  provenance: { source_url: string | null; published_at: string | null; collected_at: string | null; period_start?: string | null; period_end?: string | null; frequency?: string | null }
  link: string | null
  proposal: {
    from?: number | null; to?: number | null; unit?: string | null; currency?: string | null; field?: string | null
    entered?: { value?: number | null; unit?: string | null; currency?: string | null }
    create: CreateBody
  } | null
  proposal_error: { code: string; message_it: string; message_en: string } | null
}

export interface Interpretation {
  route: 'correction' | 'quotes' | 'unclear'
  kind: CorrKind | null
  understood: Record<string, unknown> | null
  candidates: Candidate[]
  note: { country_iso3: string | null; country_name: string | null; text: string; create: CreateBody } | null
  ai: { provider: string; model: string } | null
  ai_interpretation: Record<string, unknown> | null
  message_it: string | null
  message_en: string | null
}

export interface SyncState {
  enabled: boolean
  reason?: string | null
  reason_message_it?: string | null
  reason_message_en?: string | null
  remote?: string | null
  branch?: string | null
  interval_minutes?: number | null
  author?: string | null
  device_id?: string | null
  pending: number
  pending_events?: unknown[]
  running?: boolean
  last_attempt_at?: string | null
  last_pull_at?: string | null
  last_push_at?: string | null
  last_received?: Record<string, unknown> | null
  last_pushed?: unknown
  error?: { code: string; message_it: string; message_en: string; detail?: string | null; at?: string | null } | null
  ok?: boolean
}

export interface CorrSettings { author: string; default_author?: string; author_from_env?: boolean; sync_enabled?: boolean }
export interface CorrSettingsSaved { author?: string; sync_enabled?: boolean }

/** An error answer of the corrections API ({detail: {code, message_it, message_en}}). */
export interface CorrErrorDetail { code: string; message_it?: string; message_en?: string; [k: string]: unknown }
