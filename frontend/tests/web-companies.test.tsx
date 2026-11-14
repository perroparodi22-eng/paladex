// 15 Nov 2026 (owner): "do the business part per each country, you can get the first Google
// results, no need for them to update". Companies found on the web are shown apart from the official
// lists, labelled "Non ufficiale", with the search date, alphabetical, each with its own website.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { WebCompaniesPanel } from '@/components/companies/WebCompanies'
import type { WebCompanies } from '@/components/companies/types'
import { hrefs, render, text } from './helpers'

const WEB: WebCompanies = {
  searched_on: '2026-11-15',
  companies: [
    { name: 'Alfa Miel S.A.', role: 'exporter', city: 'Rosario', website: 'https://www.alfamiel.example/', source_url: 'https://www.alfamiel.example/empresa',
      what_it: 'Esporta miele sfuso in fusti.', what_en: 'Exports bulk honey in drums.' },
    { name: 'Coop Apicola Norte', role: 'cooperative', city: null, website: 'https://coopnorte.example', source_url: null,
      what_it: 'Cooperativa di apicoltori che vende miele.', what_en: 'Beekeepers’ cooperative selling honey.' },
  ],
}

test('companies found on the web: labelled not official, with the search date, name, business and own site', () => {
  const html = render(<WebCompaniesPanel web={WEB} />)
  const s = text(html)
  assert.match(s, /^Aziende del miele trovate sul web Non ufficiale Dai primi risultati di una ricerca sul web del 15 novembre 2026:/)
  assert.match(s, /Non è un elenco ufficiale, non è una classifica e non è completo; non si aggiorna da solo\./)
  assert.match(s, /Alfa Miel S\.A\. Esportatore · Rosario alfamiel\.example Esporta miele sfuso in fusti\./)
  assert.match(s, /Coop Apicola Norte Cooperativa coopnorte\.example Cooperativa di apicoltori che vende miele\./)
  assert.deepEqual(hrefs(html), ['https://www.alfamiel.example/', 'https://coopnorte.example'])
  assert.match(html, /target="_blank" rel="noreferrer"/)
  const en = text(render(<WebCompaniesPanel web={WEB} />, { lang: 'en' }))
  assert.match(en, /^Honey companies found on the web Not official From the first results of a web search on 15 November 2026:/)
  assert.match(en, /Alfa Miel S\.A\. Exporter · Rosario alfamiel\.example Exports bulk honey in drums\./)
})

test('a country without web companies shows no panel at all', () => {
  assert.equal(render(<WebCompaniesPanel web={{ searched_on: '2026-11-15', companies: [] }} />), '')
  assert.equal(render(<WebCompaniesPanel web={null} />), '')
  assert.equal(render(<WebCompaniesPanel web={undefined} />), '')
})
