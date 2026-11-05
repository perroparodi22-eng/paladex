// FE-4: Italian CLDR leaves 4-digit numbers ungrouped, so "8775 t" stood next to "27.605 t" in the
// same column and chart axes read "9000 · 6000" next to "12.000". Every figure must group thousands.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fmtMoney, fmtNumber, fmtPct, fmtPeriod, fmtTonnes } from '@/lib/format'

test('4-digit numbers get a thousands separator in Italian', () => {
  assert.equal(fmtNumber(8775, 'it'), '8.775')
  assert.equal(fmtNumber(9000, 'it'), '9.000')
  assert.equal(fmtNumber(2625, 'it'), '2.625')
  assert.equal(fmtNumber(27605, 'it'), '27.605')
  assert.equal(fmtNumber(1234.5, 'it', 1), '1.234,5')
  assert.equal(fmtTonnes(6_150_000, 'it'), '6.150 t')
})

test('money and percentages group the same way', () => {
  assert.match(fmtMoney(1234.5, 'EUR', 'it'), /^1\.234,50\s€$/)
  assert.equal(fmtPct(1234.5, 'it'), '+1.234,5%')
})

test('small numbers and English are unchanged', () => {
  assert.equal(fmtNumber(999, 'it'), '999')
  assert.equal(fmtNumber(8775, 'en'), '8,775')
  assert.equal(fmtNumber(null, 'it'), '—')
})

// ISMEA weekly prices are labelled "YYYY-MM-S<n>" (week n of the month): the Italy profile showed
// "2026-06-S4" raw in the Periodo column.
test('every period label the backend stores is formatted, none is shown raw', () => {
  assert.equal(fmtPeriod('2026-06-S4', 'it'), '4ª sett. giu 2026')
  assert.equal(fmtPeriod('2026-06-S4', 'en'), 'week 4 of Jun 2026')
  assert.equal(fmtPeriod('2026-W45', 'it'), 'sett. 45 2026')
  assert.equal(fmtPeriod('2026-09', 'it'), 'set 2026')
  assert.equal(fmtPeriod('2026-Q3', 'it'), '3° trim. 2026')
  assert.equal(fmtPeriod('2025', 'it'), '2025')
})
