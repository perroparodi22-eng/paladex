// Plain words for the simple view (lib/view.tsx): ONE place that says, in both languages, how the
// technical labels of the data read for someone who is not a data analyst. The words change, the
// figure never does: the full technical label always stays in the source chip's details
// (components/simple/SourceChip.tsx).
//
//   "valore unitario import (dogana)"  -> "prezzo medio pagato in dogana (import)"
//   "valore unitario export (dogana)"  -> "prezzo medio all'esportazione"
//   "Non specificata (HS 0409 total)"  -> "tutto il miele"
//   wholesale_bulk                     -> "prezzo all'ingrosso (fusti)" (the packaging the source
//                                         names: "secchi da 25 kg"; none when it names none)
//   producer                           -> "prezzo pagato all'apicoltore"
//   market                             -> "negli USA", "nell'UE", "con destinazione Spagna"
import { fmtPeriod } from './format'
import type { Lang, SourceBrief } from './types'

type Words = Record<Lang, string>

/** Each price type in plain words. */
export const PLAIN_PRICE_TYPE: Record<string, Words> = {
  wholesale_bulk: { it: "prezzo all'ingrosso", en: 'wholesale price' },
  import_unit_value: { it: 'prezzo medio pagato in dogana (import)', en: 'average price paid at customs (imports)' },
  export_unit_value: { it: "prezzo medio all'esportazione", en: 'average export price' },
  producer: { it: "prezzo pagato all'apicoltore", en: 'price paid to the beekeeper' },
  retail: { it: 'prezzo al consumatore', en: 'consumer price' },
  other: { it: 'altro prezzo', en: 'other price' },
}

/** Titles of the simple price tables (one table per price type, never mixed). */
export const PLAIN_PRICE_TYPE_TITLE: Record<string, Words> = {
  wholesale_bulk: { it: "Prezzi all'ingrosso", en: 'Wholesale prices' },
  import_unit_value: { it: 'Prezzi medi pagati in dogana (import)', en: 'Average prices paid at customs (imports)' },
  export_unit_value: { it: "Prezzi medi all'esportazione", en: 'Average export prices' },
  producer: { it: "Prezzi pagati all'apicoltore", en: 'Prices paid to beekeepers' },
  retail: { it: 'Prezzi al consumatore', en: 'Consumer prices' },
  other: { it: 'Altri prezzi', en: 'Other prices' },
}

/** One line under each table title: what this price is, for whom it matters. */
export const PLAIN_PRICE_TYPE_HINT: Record<string, Words> = {
  wholesale_bulk: {
    it: 'Quanto si paga il miele sfuso tra operatori, da listini e report di mercato.',
    en: 'What bulk honey sells for between traders, from market price lists and reports.',
  },
  import_unit_value: {
    it: 'Valore dichiarato in dogana diviso per i kg importati: una media, non un listino.',
    en: 'Value declared at customs divided by the kilos imported: an average, not a price list.',
  },
  export_unit_value: {
    it: 'Valore dichiarato dal paese che esporta diviso per i kg esportati: una media, non un listino.',
    en: 'Value declared by the exporting country divided by the kilos exported: an average, not a price list.',
  },
  producer: {
    it: "Quanto riceve chi produce il miele, secondo le statistiche ufficiali.",
    en: 'What the honey producer receives, according to official statistics.',
  },
  retail: { it: 'Prezzo del vasetto al consumatore.', en: 'Price of a jar to the consumer.' },
  other: { it: '', en: '' },
}

/** Packaging named in a wholesale price's terms ("fusto da 3 q.li", "secchio da 25 kg", USDA
 * "bulk honey … containers included" = drums), in plain words; null when the source does not say. */
export function packaging(terms: string | null | undefined, lang: Lang): string | null {
  const s = (terms ?? '').toLowerCase()
  const bucket = /secchi(?:o|elli|ello)? da ([\d\s–-]+kg)/.exec(s)
  if (bucket) return lang === 'it' ? `secchi da ${bucket[1].replace(/\s+/g, ' ').trim()}` : `${bucket[1].replace(/\s+/g, ' ').trim()} buckets`
  if (/\bfust[oi]\b|\bdrums?\b|bulk honey/.test(s)) return lang === 'it' ? 'fusti' : 'drums'
  return null
}

/** "negli USA", "in Italia", "nell'UE" — where a price is observed (market). */
const MARKET_IT: Record<string, string> = {
  USA: 'negli USA', ITA: 'in Italia', EU27: "nell'UE", EU28: "nell'UE", GBR: 'nel Regno Unito', NLD: 'nei Paesi Bassi',
  ARE: 'negli Emirati Arabi Uniti', PHL: 'nelle Filippine', CZE: 'in Cechia', WLD: 'nel mondo',
}
const MARKET_EN: Record<string, string> = {
  USA: 'in the US', EU27: 'in the EU', EU28: 'in the EU', GBR: 'in the UK', NLD: 'in the Netherlands',
  ARE: 'in the UAE', PHL: 'in the Philippines', WLD: 'worldwide',
}

export function marketPhrase(iso3: string | null | undefined, lang: Lang, countryName: (iso3: string) => string): string | null {
  if (!iso3) return null
  const known = (lang === 'it' ? MARKET_IT : MARKET_EN)[iso3]
  return known ?? `in ${countryName(iso3)}`
}

/** "con destinazione Spagna" / "to Spain": destination of an export price. */
export function destinationPhrase(iso3: string | null | undefined, lang: Lang, countryName: (iso3: string) => string): string | null {
  if (!iso3) return null
  if (lang === 'en') return (marketPhrase(iso3, lang, countryName) ?? '').replace(/^in /, 'to ')
  return `con destinazione ${iso3 === 'EU27' || iso3 === 'EU28' ? 'UE' : countryName(iso3)}`
}

/** A price type with where it is observed, in plain words:
 *  "prezzo all'ingrosso (fusti) negli USA", "prezzo medio pagato in dogana (import) nell'UE",
 *  "prezzo medio all'esportazione con destinazione Spagna", "prezzo pagato all'apicoltore". */
export function plainPriceLabel(
  p: { price_type: string; market_iso3?: string | null; origin_iso3?: string | null; terms?: string | null },
  lang: Lang,
  countryName: (iso3: string) => string,
): string {
  const base = PLAIN_PRICE_TYPE[p.price_type]?.[lang] ?? p.price_type
  const pack = p.price_type === 'wholesale_bulk' ? packaging(p.terms, lang) : null
  const head = pack ? `${base} (${pack})` : base
  // a domestic price (producer price in its own country) needs no place
  if (!p.market_iso3 || (p.price_type === 'producer' && p.market_iso3 === p.origin_iso3)) return head
  const where = p.price_type === 'export_unit_value'
    ? destinationPhrase(p.market_iso3, lang, countryName)
    : marketPhrase(p.market_iso3, lang, countryName)
  return where ? `${head} ${where}` : head
}

/** Where a price is observed, without its type (rows of a table whose title names the type):
 *  "venduto negli USA (fusti)", "importato nell'UE", "con destinazione Spagna"; null for a
 *  domestic producer price. */
export function plainWhere(
  p: { price_type: string; market_iso3?: string | null; origin_iso3?: string | null; terms?: string | null },
  lang: Lang,
  countryName: (iso3: string) => string,
): string | null {
  const it = lang === 'it'
  if (p.price_type === 'export_unit_value') return destinationPhrase(p.market_iso3, lang, countryName)
  const where = p.market_iso3 && !(p.price_type === 'producer' && p.market_iso3 === p.origin_iso3)
    ? marketPhrase(p.market_iso3, lang, countryName) : null
  if (p.price_type === 'wholesale_bulk') {
    const pack = packaging(p.terms, lang)
    const head = where ? `${it ? 'venduto' : 'sold'} ${where}` : null
    return [head, pack ? `(${pack})` : null].filter(Boolean).join(' ') || null
  }
  if (p.price_type === 'import_unit_value') return where ? `${it ? 'importato' : 'imported'} ${where}` : null
  return where
}

/** Variety in plain words: an unspecified variety (customs totals, HS 0409) is all honey. */
export function plainVariety(key: string | null | undefined, lang: Lang, label: (k: string) => string): string | null {
  if (!key) return null
  if (key === 'unspecified') return lang === 'it' ? 'tutto il miele' : 'all honey'
  return label(key)
}

/** Technical wording inside sentences written by the backend (stored or AI summaries, or answers
 * without the structured fields): the same replacements as above. */
const TEXT: Record<Lang, [RegExp, string][]> = {
  it: [
    [/\s*·\s*Non specificata \(HS 0409 total\)/g, ', tutto il miele'],
    [/Non specificata \(HS 0409 total\)/g, 'tutto il miele'],
    [/\s*\(HS 0409 total\)/g, ' (tutto il miele)'],
    [/valore unitario import \(dogana\)/gi, 'prezzo medio pagato in dogana (import)'],
    [/valore unitario export \(dogana\)/gi, "prezzo medio all'esportazione"],
    [/prezzo all'ingrosso \(sfuso\)/gi, "prezzo all'ingrosso"],
    [/prezzo al produttore/gi, "prezzo pagato all'apicoltore"],
  ],
  en: [
    [/\s*·\s*Not specified \(HS 0409 total\)/g, ', all honey'],
    [/Not specified \(HS 0409 total\)/g, 'all honey'],
    [/\s*\(HS 0409 total\)/g, ' (all honey)'],
    [/import unit value \(customs\)/gi, 'average price paid at customs (imports)'],
    [/export unit value \(customs\)/gi, 'average export price'],
    [/wholesale \(bulk\)/gi, 'wholesale price'],
    [/producer \/ beekeeper price/gi, 'price paid to the beekeeper'],
  ],
}

export function plainText(text: string, lang: Lang): string {
  return TEXT[lang].reduce((s, [re, to]) => s.replace(re, to), text)
}

/** "€/kg", "$/kg", else "GBP/kg". */
export function perKg(currency: string): string {
  const sym = currency === 'EUR' ? '€' : currency === 'USD' ? '$' : `${currency} `
  return `${sym}/kg`
}

/** "rispetto al 2023", "rispetto ad ago 2025", "rispetto a set 2025"; "compared with 2023". */
export function vsPeriod(label: string, lang: Lang): string {
  const txt = fmtPeriod(label, lang)
  if (lang !== 'it') return `compared with ${txt}`
  if (/^\d{4}$/.test(label)) return `rispetto al ${txt}`
  return `rispetto ${/^[aeiou]/i.test(txt) ? 'ad' : 'a'} ${txt}`
}

/** "nel 2024", "a set 2026", "ad ago 2026"; "in 2024", "in Sep 2026". */
export function inPeriod(label: string, lang: Lang): string {
  const txt = fmtPeriod(label, lang)
  if (lang !== 'it') return `in ${txt}`
  if (/^\d{4}$/.test(label)) return `nel ${txt}`
  return `${/^[aeiou]/i.test(txt) ? 'ad' : 'a'} ${txt}`
}

/** Italian "del 18,5%" but "dell'84,5%", "dell'11%", "dell'1,2%" (read with a vowel first). */
export function ofPct(pctText: string, lang: Lang): string {
  if (lang !== 'it') return ''
  const whole = pctText.replace(/^[+−-]/, '').split(/[,.]/)[0]
  return whole.startsWith('8') || whole === '1' || whole === '11' ? "dell'" : 'del '
}

// ---------------------------------------------------------------------------------------------
// Short source names ("Fonte: USDA · set 2026"); the chip's details give the full name.
// ---------------------------------------------------------------------------------------------
const SHORT_SOURCE: Record<string, Words | string> = {
  usda_honey_report: 'USDA',
  usda_nass_honey: 'USDA NASS',
  usda_fas_gats: 'USDA FAS',
  us_census_trade: 'US Census Bureau',
  us_federal_register: { it: 'Federal Register (USA)', en: 'US Federal Register' },
  us_hts: { it: 'USITC (USA)', en: 'USITC' },
  ar_official_exports: 'INDEC (Argentina)',
  ar_magyp_hives: 'SAGyP (Argentina)',
  ar_senasa_honey: 'SENASA (Argentina)',
  br_comexstat: { it: 'Comex Stat (Brasile)', en: 'Comex Stat (Brazil)' },
  br_ibge_honey: { it: 'IBGE (Brasile)', en: 'IBGE (Brazil)' },
  br_mapa_honey: { it: 'MAPA (Brasile)', en: 'MAPA (Brazil)' },
  ca_cid_honey_importers: { it: 'Governo del Canada', en: 'Government of Canada' },
  ca_statcan_honey: 'Statistics Canada',
  cciaa_cuneo_miele: { it: 'Camera di Commercio di Cuneo', en: 'Cuneo Chamber of Commerce' },
  cciaa_siena_miele: { it: 'Camera di Commercio di Arezzo-Siena', en: 'Arezzo-Siena Chamber of Commerce' },
  cl_honey_exports: { it: 'Dogana del Cile', en: 'Chile Customs' },
  cl_odepa_hives: { it: 'ODEPA (Cile)', en: 'ODEPA (Chile)' },
  demo: { it: 'Dati dimostrativi', en: 'Demo data' },
  ec_honey_market: { it: 'Commissione europea', en: 'European Commission' },
  ec_taxud_weekly: { it: 'Commissione europea', en: 'European Commission' },
  ecb_fx: { it: 'BCE', en: 'ECB' },
  eu_tariff_xi: { it: 'TARIC (UE)', en: 'TARIC (EU)' },
  eurlex_honey: 'EUR-Lex',
  eurostat_comext: 'Eurostat',
  faostat: 'FAO',
  in_dgft_honey: 'DGFT (India)',
  in_eic_honey_establishments: 'EIC (India)',
  ismea_miele: 'ISMEA',
  manual_quotes: { it: 'Offerte fornitori', en: 'Supplier quotes' },
  mx_honey_exports: { it: 'INEGI (Messico)', en: 'INEGI (Mexico)' },
  mx_siap_honey: { it: 'SIAP (Messico)', en: 'SIAP (Mexico)' },
  nasa_power_weather: 'NASA',
  onm_informamiele: { it: 'Osservatorio Nazionale Miele', en: 'Italian Honey Observatory' },
  rasff_honey: { it: 'RASFF (UE)', en: 'RASFF (EU)' },
  tr_tuik_honey: { it: 'TÜİK (Turchia)', en: 'TÜİK (Turkey)' },
  ua_honey_exports: { it: "Dogana dell'Ucraina", en: 'Ukraine Customs' },
  uk_hmrc_honey: { it: 'HMRC (Regno Unito)', en: 'HMRC (UK)' },
  uk_hmrc_honey_traders: { it: 'HMRC (Regno Unito)', en: 'HMRC (UK)' },
  un_comtrade: 'UN Comtrade',
  uy_honey_exports: 'Uruguay XXI',
  uy_sie_honey_exporters: 'Uruguay XXI',
}

/** A short name for a source: the mapping above, else the publisher up to its first bracket,
 * comma or dash ("Apimondia (International Federation…)" -> "Apimondia"), else the source name
 * up to its first colon or dash. */
export function shortSource(s: Pick<SourceBrief, 'key' | 'name' | 'publisher'> & { name_en?: string | null } | null | undefined, lang: Lang): string {
  if (!s) return '—'
  const known = SHORT_SOURCE[s.key]
  if (known) return typeof known === 'string' ? known : known[lang]
  const cut = (x: string, seps: string[]) => seps.reduce((acc, sep) => {
    const i = acc.indexOf(sep)
    return i > 0 ? acc.slice(0, i) : acc
  }, x).trim()
  if (s.publisher) return cut(s.publisher, [' (', ', ', ';', ' – ', ' — ', ' / '])
  const name = (lang === 'en' && s.name_en) || s.name
  return cut(name, [': ', ' — ', ' – ', ' - '])
}
