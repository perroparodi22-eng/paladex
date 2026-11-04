// FE-1: links built by the backend (overview briefing, key-price tiles, search, data-quality
// issues) use English parameter names: /prezzi?origin=HUN&price_type=wholesale_bulk&variety=acacia.
// The price page must open on exactly that series, not on an unfiltered view.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { usePriceFilters } from '@/components/prices/useFilters'
import { render } from './helpers'

function Probe() {
  const { apiFilters } = usePriceFilters()
  return <pre>{JSON.stringify(apiFilters)}</pre>
}

function filtersAt(url: string) {
  const html = render(<Probe />, { url })
  return JSON.parse(html.replace(/^<pre>|<\/pre>$/g, '').replace(/&quot;/g, '"'))
}

test('backend deep link (English names) filters the price page', () => {
  assert.deepEqual(filtersAt('/prezzi?origin=HUN&price_type=wholesale_bulk&variety=acacia'),
    { price_type: 'wholesale_bulk', origin: ['HUN'], variety: 'acacia' })
})

test('a producer-price link opens the producer type, not wholesale', () => {
  assert.equal(filtersAt('/prezzi?origin=ARG&price_type=producer').price_type, 'producer')
})

test('repeated origin parameters are all kept', () => {
  assert.deepEqual(filtersAt('/prezzi?origin=ARG&origin=UKR&price_type=import_unit_value').origin, ['ARG', 'UKR'])
})

test('market, source and colour aliases are read too', () => {
  assert.deepEqual(filtersAt('/prezzi?price_type=wholesale_bulk&market=US&source=usda_honey&color_grade=white'),
    { price_type: 'wholesale_bulk', market: 'US', source: 'usda_honey', color_grade: 'white' })
})

test('the page’s own Italian names still work and win over an alias', () => {
  assert.deepEqual(filtersAt('/prezzi?tipo=producer&origini=ARG,HUN&varieta=acacia&origin=CHN'),
    { price_type: 'producer', origin: ['ARG', 'HUN'], variety: 'acacia' })
})

test('changing a filter drops its English alias; changing the type drops every dependent filter', async () => {
  const { patchPriceParams, readPriceFilters } = await import('@/components/prices/useFilters')
  const link = new URLSearchParams('origin=HUN&price_type=wholesale_bulk&variety=acacia')
  const byOrigin = patchPriceParams(link, { origins: ['ARG'] }, 'wholesale_bulk')
  assert.equal(byOrigin.get('origin'), null)
  assert.deepEqual(readPriceFilters(byOrigin).origins, ['ARG'])
  assert.equal(readPriceFilters(byOrigin).variety, 'acacia')

  const byType = patchPriceParams(link, { type: 'producer' }, 'wholesale_bulk')
  const s = readPriceFilters(byType)
  assert.equal(s.type, 'producer')
  assert.deepEqual(s.origins, [])
  assert.equal(s.variety, '')
  assert.equal(byType.get('price_type'), null)

  // Filling in the default type on first load keeps the linked filters.
  const first = patchPriceParams(new URLSearchParams('origin=HUN&variety=acacia'), { type: 'wholesale_bulk' }, null)
  assert.deepEqual(readPriceFilters(first).origins, ['HUN'])
})
