// Types of /api/alerts/* responses (backend/paladex/api/alerts.py, services/alerts.py).
import type { SourceBrief } from '@/lib/types'

export type AlertType = 'price_change' | 'new_report' | 'news_keyword' | 'regulation' | 'trade_change'
export const ALERT_TYPES: AlertType[] = ['price_change', 'new_report', 'news_keyword', 'regulation', 'trade_change']
export type Severity = 'info' | 'warning' | 'critical'
export type Direction = 'up' | 'down' | 'any'

export type RuleParams = Record<string, unknown>

export interface AlertRule {
  id: number
  name: string
  alert_type: AlertType
  params: RuleParams
  enabled: boolean
  created_at: string | null
  watching_since: string | null
  last_checked_at: string | null
  description_it: string
  description_en: string
  events_total: number
  events_unread: number
  last_event_at: string | null
  is_example: boolean
}

export interface RulesResponse { rules: AlertRule[]; types: AlertType[]; last_checked_at: string | null }

export interface AlertEventItem {
  id: number
  rule_id: number | null
  rule_name: string | null
  alert_type: AlertType | null
  dedup_key: string
  triggered_at: string
  severity: Severity
  title_it: string
  title_en: string
  body_it: string | null
  body_en: string | null
  link: string | null
  link_internal: boolean
  ref_type: string | null
  ref_id: number | null
  read: boolean
  source: SourceBrief | null
  source_url: string | null
  published_at: string | null
  collected_at: string | null
  period_label: string | null
  is_demo: boolean
}

export interface EventsResponse {
  items: AlertEventItem[]
  total: number
  unread: number
  page: number
  page_size: number
  pages: number
  rules: { id: number; name: string; alert_type: AlertType }[]
}

export interface UnreadCount { unread: number; unread_warning: number; latest_unread_at: string | null }

export interface PreviewItem {
  dedup_key: string
  title_it: string
  title_en: string
  body_it: string
  body_en: string
  severity: Severity
  link: string | null
  ref_type: string | null
  ref_id: number | null
  observed_at: string | null
  published_at: string | null
  period_label: string | null
  source: SourceBrief | null
  source_url: string | null
  already_sent: boolean
}

/** One series or source the rule looked at (price/trade comparisons, latest report). */
export interface PreviewCheck {
  label_it?: string
  label_en?: string
  source?: SourceBrief | null
  period_label?: string
  previous_period_label?: string
  value?: number | null
  previous_value?: number | null
  value_kg?: number | null
  previous_value_kg?: number | null
  currency?: string
  pct?: number | null
  fires?: boolean
  reason?: 'fires' | 'below_threshold' | 'no_previous' | 'known_before_rule'
  latest_title?: string | null
  latest_published_at?: string | null
  latest_period_label?: string | null
  url?: string | null
}

export interface PreviewResponse {
  alert_type: AlertType
  total: number
  items: PreviewItem[]
  checked: PreviewCheck[]
  window_days: number | null
  description_it: string
  description_en: string
}

export interface PriceOption {
  price_type: string
  origin: string
  variety: string
  market: string | null
  color_grade: string | null
  count: number
  last_period: string | null
  first_period: string | null
}

export interface TradeFlowOption { freqs: ('M' | 'A')[]; partners: string[]; rows: number; last_period: string | null }
export interface TradeOption { iso3: string; flows: Partial<Record<'import' | 'export', TradeFlowOption>> }

export interface OptionsResponse {
  price: PriceOption[]
  report_sources: (SourceBrief & { reports: number; latest_published_at: string | null })[]
  news: { countries: { iso3: string; count: number }[]; articles: number }
  regulation: {
    jurisdictions: { key: string; count: number; tariffs: number }[]
    doc_types: { jurisdiction: string; key: string; count: number }[]
    countries: { iso3: string; count: number }[]
  }
  trade: TradeOption[]
  examples: { name: string; alert_type: AlertType; params: RuleParams }[]
}

export interface RuleDraft { id?: number; name: string; alert_type: AlertType; params: RuleParams }
