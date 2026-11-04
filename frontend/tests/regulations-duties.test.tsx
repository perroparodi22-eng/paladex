// Regulations page, "Dazi per origine" matrix.
// F3: every general (erga omnes) EU layer that applies is shown, not only the MFN: a safeguard /
//     additional duty must never disappear from the duty stack of an origin.
// F1: a layer the latest read could not re-confirm (quota balance, Chapter 99 range) keeps its own,
//     older date on screen; the cell never presents it only under the newer date of the other layers.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { DutyMatrix } from '@/components/regulations/DutyMatrix'
import type { DutiesResponse, DutyRow, JurisdictionStatus, OriginDuties } from '@/components/regulations/types'
import { fmtDate } from '@/lib/format'
import { render, text } from './helpers'

let nextId = 1
function row(o: Partial<DutyRow>): DutyRow {
  return {
    id: nextId++, series_key: 'k', jurisdiction: 'EU', origin_iso3: 'ERGA_OMNES', scope: 'general', hs_code: '0409000000',
    measure_type: 'mfn', measure_code: '103', description: null, duty_text: null, ad_valorem_pct: null,
    specific_amount: null, specific_unit: null, specific_currency: null, quota: null, valid_from: null, valid_to: null,
    legal_reference: null, legal_url: null, consult_url: null, source_url: null, published_at: null,
    as_of: '2026-11-20', collected_at: '2026-11-04', last_seen_at: '2026-11-20', revision: 1, is_current: true,
    supersedes_id: null, needs_review: false, review_reason: null, stale: false, extra: null, source: null,
    reliability: 'official', data_status: 'published', is_demo: false, ...o,
  }
}

function status(general: DutyRow[], o: Partial<JurisdictionStatus> = {}): JurisdictionStatus {
  return {
    source: null, terms_note: null, enabled: true, last_run_at: '2026-11-20T08:12:00', last_run_status: 'success',
    last_success_at: '2026-11-20T08:12:00', freshness: null, as_of: '2026-11-20', count: general.length,
    review_count: general.filter((g) => g.needs_review).length, general, ...o,
  }
}

function origin(iso3: string, eu: Partial<OriginDuties['eu']>, us: Partial<OriginDuties['us']> = {}): OriginDuties {
  return {
    iso3, name_it: iso3, name_en: iso3, priority: false,
    eu: { rows: [], general_ids: [], has_own_mfn: false, as_of: '2026-11-20', as_of_latest: '2026-11-20', review_count: 0,
      links: { taric: 'https://ec.europa.eu/taxation_customs/dds2/taric/measures.jsp' }, ...eu },
    us: { rows: [], general_ids: [], domestic: false, as_of: null, as_of_latest: null, review_count: 0,
      links: { hts: 'https://hts.usitc.gov/' }, ad_case: null, ...us },
  }
}

function response(origins: OriginDuties[], eu: JurisdictionStatus, us: JurisdictionStatus = status([])): DutiesResponse {
  return { origins, jurisdictions: { EU: eu, US: us }, ad_cases: [], has_data: true }
}

test('EU cell shows every applicable general layer, not only the MFN', () => {
  const mfn = row({ measure_type: 'mfn', measure_code: '103', duty_text: '17.30 %', ad_valorem_pct: 17.3 })
  const safeguard = row({ measure_type: 'surcharge', measure_code: '696', duty_text: '25.00 %', ad_valorem_pct: 25,
    description: 'Additional duties (safeguard)' })
  const review = row({ measure_type: 'other', measure_code: '105', duty_text: '12.8 % MAX 5 EUR', needs_review: true })
  const arg = origin('ARG', { general_ids: [mfn.id, safeguard.id, review.id] })
  const html = render(<DutyMatrix d={response([arg], status([mfn, safeguard, review]))} />)
  const body = text(html)
  assert.match(body, /17,3 %/)
  assert.match(body, /25 %/, 'the erga-omnes safeguard is part of the duty stack')
  assert.match(body, /Dazio aggiuntivo/)
  assert.match(body, /\+ 1 misura generale da verificare/)

  // an origin with its own MFN drops only the general MFN; the safeguard still applies to it
  const own = row({ origin_iso3: 'TUR', scope: 'origin', measure_type: 'mfn', measure_code: '103', duty_text: '10.00 %', ad_valorem_pct: 10 })
  const tur = origin('TUR', { rows: [own], general_ids: [mfn.id, safeguard.id], has_own_mfn: true })
  const turBody = text(render(<DutyMatrix d={response([tur], status([mfn, safeguard]))} />))
  assert.doesNotMatch(turBody, /17,3 %/)
  assert.match(turBody, /25 %/)
  assert.match(turBody, /10 %/)

  // an origin excluded from the general layer (not in general_ids) does not get it
  const excl = origin('MDA', { general_ids: [mfn.id] })
  assert.doesNotMatch(text(render(<DutyMatrix d={response([excl], status([mfn, safeguard]))} />)), /25 %/)
})

test('a layer not re-confirmed by the latest read keeps its own date next to its values', () => {
  const mfn = row({ measure_type: 'mfn', measure_code: '103', duty_text: '17.30 %', ad_valorem_pct: 17.3 })
  const trq = row({
    origin_iso3: 'MEX', scope: 'origin', measure_type: 'trq_in', measure_code: '143', duty_text: '0.00 %', ad_valorem_pct: 0,
    as_of: '2026-11-04', stale: true,
    quota: { order_number: '099991', volume_kg: 3_000_000, balance_kg: 1_200_000, status: 'critical', fill_pct: 60,
      period_start: '2026-01-01', period_end: '2026-12-31', last_allocation_date: null, critical: 'Y', shared_by_group: false, note: null },
  })
  const mex = origin('MEX', { rows: [trq], general_ids: [mfn.id], as_of: '2026-11-04', as_of_latest: '2026-11-20' })
  for (const lang of ['it', 'en'] as const) {
    const d = response([mex], status([mfn], { last_run_status: 'partial' }))
    const body = text(render(<DutyMatrix d={d} />, { lang }))
    const old = fmtDate('2026-11-04', lang)
    const latest = fmtDate('2026-11-20', lang)
    if (lang === 'it') {
      assert.match(body, new RegExp(`Verificato il ${old} · non riconfermato nell'ultima lettura`))
      assert.match(body, new RegExp(`Residuo .* su .* · al ${old}`), 'the quota balance carries its own date')
      assert.match(body, new RegExp(`Verificato il ${latest}, tranne le misure segnate \\(ultima conferma ${old}\\)`))
      assert.doesNotMatch(body, new RegExp(`Verificato il ${latest} ·`), 'never only the newer date')
      assert.match(body, /ultimo aggiornamento incompleto/)
    } else {
      assert.match(body, new RegExp(`Verified on ${old} · not reconfirmed in the latest read`))
      assert.match(body, new RegExp(`left of .* · as of ${old}`))
      assert.match(body, new RegExp(`Verified on ${latest}, except the marked measures \\(last confirmed ${old}\\)`))
      assert.match(body, /last update incomplete/)
    }
  }

  // re-confirmed: one date in the footer and no warning on the row
  const fresh = origin('MEX', { rows: [{ ...trq, as_of: '2026-11-20', stale: false }], general_ids: [mfn.id] })
  const body = text(render(<DutyMatrix d={response([fresh], status([mfn]))} />))
  assert.doesNotMatch(body, /non riconfermato|tranne le misure segnate|incompleto/)
  assert.match(body, new RegExp(`Verificato il ${fmtDate('2026-11-20', 'it')}`))
})
