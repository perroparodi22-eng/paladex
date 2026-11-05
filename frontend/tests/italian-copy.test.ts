// Italian copy, review of 5 Nov 2026. The interface speaks to the owner with "tu" (Scegli, i tuoi
// fornitori, Clicca…); the Assistant page and one Quotes note used "voi" ("Che cosa volete sapere?",
// "La vostra domanda", "se attivate l'assistente"). Every Italian string must use one register.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { common } from '@/i18n/common'

const pages = import.meta.glob<{ default: { it: Record<string, string> } }>('/src/i18n/pages/*.ts', { eager: true })
const italian: [string, string][] = [
  ...Object.entries(common.it),
  ...Object.entries(pages).flatMap(([path, mod]) => Object.entries(mod.default.it ?? {}).map(([k, v]) => [`${path}:${k}`, v] as [string, string])),
]

// Second person plural (verbs and possessives) that the rest of the interface never uses.
const VOI = /\b(volete|potete|dovete|avete|sapete|vostr[aoie]|Vostr[aoie]|fate|Fate|scegliete|Scegliete|scrivete|scrivetene|attivate|cliccate|Cliccate|aprite|Aprite|chiedete|Chiedete|premete|Premete|inserite le|provate|Provate)\b/

test('the Italian interface addresses the reader in one register ("tu")', () => {
  assert.ok(italian.length > 500, 'dictionaries loaded')
  const offenders = italian.filter(([, v]) => VOI.test(v)).map(([k, v]) => `${k}: ${v.slice(0, 90)}`)
  assert.deepEqual(offenders, [])
})
