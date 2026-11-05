// The owner can paste a free key received by e-mail instead of editing the .env file by hand.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { KeyHelp } from '@/components/sources/KeyHelp'
import type { ApiKeyInfo } from '@/components/sources/types'
import { render, text } from './helpers'

const info: ApiKeyInfo = {
  setting: 'usda_nass_api_key', env_var: 'PALADEX_USDA_NASS_API_KEY', configured: false,
  service: 'USDA NASS Quick Stats', signup_url: 'https://quickstats.nass.usda.gov/api',
  help_it: null, help_en: null, sources: [{ key: 'usda_nass_honey', name: 'USDA NASS', optional: false }],
}

test('a missing key offers a paste box (hidden characters) and a save button, in both languages', () => {
  const html = render(<KeyHelp info={info} settingAttr="usda_nass_api_key" optional={false} />)
  assert.match(html, /type="password"/)
  assert.match(html, /autoComplete="off"|autocomplete="off"/)
  assert.match(text(html), /Hai già la chiave\? Incollala qui|Salva la chiave/)
  const en = text(render(<KeyHelp info={info} settingAttr="usda_nass_api_key" optional={false} />, { lang: 'en' }))
  assert.match(en, /Save the key/)
})
