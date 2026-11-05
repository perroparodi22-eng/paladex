// Response types for /api/quality/*, /api/sources/{key}/runs (backend: api/quality.py, api/meta.py).
import type { CollectState, SourceBrief, SourceInfo } from '@/lib/types'

export type Severity = 'critical' | 'warning' | 'info'

export interface QualityIssue {
  id: number
  type: string
  severity: Severity
  status: 'open' | 'resolved'
  message_it: string
  message_en: string
  source: SourceBrief | null
  source_keys: string[]
  entity_type: string | null
  entity_id: number | null
  link: string | null
  details: Record<string, unknown>
  detected_at: string | null
  last_seen_at: string | null
  resolved_at: string | null
}

export interface QualityIssues {
  total: number
  counts: Record<Severity, number>
  issues: QualityIssue[]
  last_check_at: string | null
}

export interface QualitySummary {
  sources: {
    total: number; enabled: number; disabled: number; current: number; aging: number; stale: number
    never: number; unknown: number; errors: number; key_missing: number; offline: number
  }
  last_check_at: string | null
  last_success_at: string | null
  last_new_data_at: string | null
  issues: { open: number; critical: number; warning: number; info: number; by_type: Record<string, number>; resolved_last_30_days: number }
  quality_checked_at: string | null
  collect: CollectState
  demo: { visible: boolean; rows: Record<string, number>; total: number }
}

export interface QualityRunResult { detected: number; new: number; reopened: number; updated: number; resolved: number; open: number }

export interface ApiKeyInfo {
  setting: string
  env_var: string
  configured: boolean
  service: string | null
  signup_url: string | null
  help_it: string | null
  help_en: string | null
  sources: { key: string; name: string; optional: boolean }[]
}

export interface CollectionRunInfo {
  id: number
  started_at: string | null
  finished_at: string | null
  status: string
  trigger: string
  items_seen: number
  items_new: number
  items_revised: number
  warnings: string[] | null
  error: string | null
}

export interface SourceRuns { source: SourceInfo; runs: CollectionRunInfo[] }

export interface SourcesList { sources: SourceInfo[]; collect: CollectState }
