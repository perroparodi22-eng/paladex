// Responses of /api/assistant/* (backend/paladex/api/assistant.py, services/assistant.py, services/briefing.py).
import type { Lang, SourceBrief } from '@/lib/types'

/** How a fact was published: drives its section and badge. */
export type FactStatus = 'verified_official' | 'verified_industry' | 'provisional' | 'estimate' | 'historical' | 'press' | 'user'

export type SectionKey = 'verified' | 'historical' | 'estimates' | 'news' | 'quotes' | 'analysis' | 'forecast'

/** One numbered context block [n]: a fact read from the local database, with its provenance. */
export interface AssistantFact {
  id: number
  kind: string
  title: string
  text: string
  status: FactStatus
  status_label: string
  source: SourceBrief | null
  source_name: string | null
  url: string | null          // original document / article / API call
  link: string | null         // page of this app
  published_at: string | null
  period_label: string | null
  unit: string | null
  data_status: string | null
  reliability: string | null
  is_demo: boolean
  private: boolean
  country: string | null
  price_type: string | null
  change_pct: number | null
  quote_id?: number
}

export interface AnswerItem { text: string; refs: number[]; kind?: string; status?: FactStatus }

export interface AnswerSection {
  key: SectionKey
  title: string
  /** Written by the AI (false: the retrieved fact itself). */
  ai: boolean
  /** AI interpretation or outlook (not a fact). */
  analysis: boolean
  items: AnswerItem[]
}

export interface Named { key: string; name: string }

export interface Understood {
  mode: string
  countries: { iso3: string; name: string }[]
  eu: boolean
  jurisdictions: string[]
  varieties: Named[]
  price_types: Named[]
  topics: Named[]
  flow: string | null
  direction: string | null
  period: { kind: string; start: string; end: string; days: number | null; year: number | null; label_it: string; label_en: string } | null
  years: number[]
  sources: string[]
  llm_entities: boolean
}

export interface HowToEnable { file: string; lines: string[]; alternative: string[]; text: string }

export interface AnswerChecks {
  sentences: number
  dropped: number
  dropped_items: { text: string; reason: string; numbers?: string[]; section?: string }[]
  rejected: boolean
}

export interface Answer {
  id?: string
  question: string
  lang: Lang
  asked_at: string
  understood: Understood
  ai_used: boolean
  ai: { enabled: boolean; provider: string | null; model: string | null }
  intro: string
  sections: AnswerSection[]
  facts: AssistantFact[]
  notes: string[]
  warnings: string[]
  is_demo: boolean
  insufficient: boolean
  insufficient_note: string | null
  checks: AnswerChecks | null
  how_to_enable?: HowToEnable
  private_data_used: boolean
  sent_private_to_ai: boolean
}

export interface HistoryItem {
  id: string
  asked_at: string
  question: string
  lang: Lang
  ai_used: boolean
  facts: number
  insufficient: boolean
}

export interface HistoryResponse { items: HistoryItem[]; count: number; max: number }

export interface AssistantStatus {
  llm_enabled: boolean
  provider: string | null
  model: string | null
  provider_configured: boolean
  key_missing: boolean
  how_to_enable: Record<Lang, HowToEnable>
  briefing: {
    date: string
    schedule: string
    items: { language: Lang; generator: string; is_ai: boolean; generated_at: string; bullets: number }[]
  }
  history_count: number
  quotes_count: number
  limits: { max_facts: number; news_days: number; question_max_chars: number }
}

export interface QuoteOption {
  id: number
  supplier_name: string
  origin_iso3: string
  origin_name: string
  variety: string
  variety_name: string
  price_per_kg: number
  currency: string
  incoterm: string | null
  date_received: string
  valid_until: string | null
  is_demo: boolean
}

export interface StoredBriefing {
  date: string
  language: Lang
  generator: string
  generated_at: string
  is_ai: boolean
  sections: { key: string; title: string; is_analysis: boolean; count: number }[]
  bullets: { section: string; text: string; refs: number[]; is_analysis: boolean }[]
  facts: AssistantFact[]
  checks: AnswerChecks | null
}

export interface BriefingResponse { enabled: boolean; date: string; schedule: string; briefing: StoredBriefing | null }

export interface RegenerateResponse {
  enabled: boolean
  date: string
  generator: string | null
  skipped?: string
  results: Record<string, { status: 'generated' | 'exists' | 'no_facts' | 'rejected' | 'error'; error?: string; bullets?: number }>
}
