// The address a person opens for a figure's official source.
//
// Every figure keeps the exact official address it was read from (provenance, never rewritten).
// Most of those addresses are pages, PDFs or files that open as they are, and are linked as they
// are. Some are machine-only addresses: an official data service answering raw JSON/XML (often
// only to the application's own form requests, an error in a browser), or a bulk archive of tens
// of megabytes. For those, the link opens THE SAME PUBLISHER'S OWN PAGE for that dataset, on its
// own website, where a person can read or query the same figures. Nothing else is ever linked:
// every target below is an official page of the publisher of the address it replaces, opened and
// checked on 5 Nov 2026 (docs/DATA_SOURCES.md, "Links").
//
// Anything not matched here (pages, PDFs, news articles, the copy of a report kept by Paladex
// under /api/reports/...) is returned unchanged.

type Rule = { re: RegExp; to: (m: RegExpMatchArray, u: URL) => string }

const FAOSTAT_DOMAINS: [RegExp, string][] = [
  [/Production_Crops_Livestock/i, 'QCL'],
  [/Prices_E_All/i, 'PP'],
  [/Trade_DetailedTradeMatrix/i, 'TM'],
  [/Trade_CropsLivestock/i, 'TCL'],
]

const CL_DUS_PAGE = 'https://www.aduana.cl/base-de-datos-operaciones-de-salida/aduana/2024-11-12/153724.html'
const CL_STATS_PAGE = 'https://www.aduana.cl/exportacion-por-pais-y-codigo-arancelario/aduana/2018-12-14/101258.html'

function comtradePage(m: RegExpMatchArray, u: URL): string {
  const q = u.searchParams
  const p = new URLSearchParams({
    Frequency: m[1],
    Flows: q.get('flowCode') ?? 'M,X',
    CommodityCodes: q.get('cmdCode') ?? '0409',
    Partners: q.get('partnerCode') ?? '0',
    Reporters: q.get('reporterCode') ?? 'all',
    period: q.get('period') ?? '',
    AggregateBy: 'none',
    BreakdownMode: 'plus',
  })
  return `https://comtradeplus.un.org/TradeFlow?${p.toString()}`
}

const RULES: Rule[] = [
  // Argentina, INDEC: the query service behind comex.indec.gob.ar -> the query page itself.
  { re: /^https:\/\/comexbe\.indec\.gob\.ar\//, to: () => 'https://comex.indec.gob.ar/#/search' },
  // Brazil, MDIC/SECEX Comex Stat API -> Comex Stat "General Data" query page.
  { re: /^https:\/\/api-comexstat\.mdic\.gov\.br\//, to: () => 'https://comexstat.mdic.gov.br/en/geral' },
  // Brazil, IBGE SIDRA values API -> the SIDRA table page.
  { re: /^https:\/\/apisidra\.ibge\.gov\.br\/values\/t\/(\d+)\//, to: (m) => `https://sidra.ibge.gov.br/tabela/${m[1]}` },
  // Argentina, MAGyP open data (CKAN): file download -> the dataset page (lists and previews the file).
  { re: /^(https:\/\/datos\.magyp\.gob\.ar\/dataset\/[^/]+)\/resource\/[^/]+\/download\//, to: (m) => m[1] },
  // Ukraine, data.gov.ua (CKAN): compressed monthly file -> that file's own page on data.gov.ua.
  { re: /^(https:\/\/data\.gov\.ua\/dataset\/[^/]+\/resource\/[^/]+)\/download\//, to: (m) => m[1] },
  // Chile, Aduanas: yearly database files (~26 MB) and statistics workbooks -> the pages that publish them.
  { re: /^https:\/\/www\.aduana\.cl\/aduana\/site\/docs\/\d+\/20181214101258\//, to: () => CL_STATS_PAGE },
  { re: /^https:\/\/www\.aduana\.cl\/aduana\/site\/docs\/\d+\/20241112153724\//, to: () => CL_DUS_PAGE },
  // EU, DG AGRI agri-food data portal API (TAXUD weekly imports) -> its dashboard.
  { re: /^https:\/\/api\.tech\.ec\.europa\.eu\/agrifood\/api\/taxud\//, to: () => 'https://agridata.ec.europa.eu/extensions/DashboardTaxud/TaxudWeeklyImport-m.html' },
  // EU TARIC via the UK Online Trade Tariff (XI) API -> the commodity / heading page of the same service.
  { re: /^https:\/\/www\.trade-tariff\.service\.gov\.uk\/(xi\/)?api\/v2\/commodities\/(\d{10})/, to: (m) => `https://www.trade-tariff.service.gov.uk/${m[1] ?? ''}commodities/${m[2]}` },
  { re: /^https:\/\/www\.trade-tariff\.service\.gov\.uk\/(xi\/)?api\/v2\/headings\/(\d{4})/, to: (m) => `https://www.trade-tariff.service.gov.uk/${m[1] ?? ''}headings/${m[2]}` },
  { re: /^https:\/\/www\.trade-tariff\.service\.gov\.uk\/(xi\/)?api\/v2\//, to: (m) => `https://www.trade-tariff.service.gov.uk/${m[1] ?? ''}headings/0409` },
  // Eurostat Comext API -> Eurostat's international trade in goods database page.
  { re: /^https:\/\/ec\.europa\.eu\/eurostat\/api\/comext\//, to: () => 'https://ec.europa.eu/eurostat/web/international-trade-in-goods/database' },
  // FAOSTAT bulk archives (hundreds of MB) -> the FAOSTAT domain page of the same data.
  {
    re: /^https:\/\/bulks-faostat\.fao\.org\//,
    to: (_m, u) => {
      const d = FAOSTAT_DOMAINS.find(([re]) => re.test(u.pathname))
      return d ? `https://www.fao.org/faostat/en/#data/${d[1]}` : 'https://www.fao.org/faostat/en/#data'
    },
  },
  // India, Export Inspection Council: the register's data service -> the register page.
  { re: /^https:\/\/eicindia\.gov\.in\/api\//, to: () => 'https://eicindia.gov.in/offerings/commodity-wise-facilities?tab=animal' },
  // Mexico, SIAP: the query service of the year-end close -> the year-end close page.
  { re: /^https:\/\/nube\.agricultura\.gob\.mx\/cierre_pecuario\/\?/, to: () => 'https://nube.agricultura.gob.mx/cierre_pecuario/' },
  // NASA POWER API -> the POWER Data Access Viewer.
  { re: /^https:\/\/power\.larc\.nasa\.gov\/api\//, to: () => 'https://power.larc.nasa.gov/data-access-viewer/' },
  // UK, HMRC uktradeinfo API -> the overseas trade table / the traders search.
  { re: /^https:\/\/api\.uktradeinfo\.com\/OTS\b/i, to: () => 'https://www.uktradeinfo.com/trade-data/ots-custom-table/' },
  { re: /^https:\/\/api\.uktradeinfo\.com\/(Import|Export|Trader)/i, to: () => 'https://www.uktradeinfo.com/find-uk-traders/' },
  { re: /^https:\/\/api\.uktradeinfo\.com\//, to: () => 'https://www.uktradeinfo.com/trade-data/' },
  // UN Comtrade API -> the same query on UN Comtrade's own Trade Data page (reporter, period, flow, HS code).
  { re: /^https:\/\/comtradeapi\.un\.org\/(?:public\/v1\/preview|data\/v1\/get)\/C\/([AM])\/HS\?/, to: comtradePage },
  // US Census Bureau international trade API -> the Census international trade data page.
  { re: /^https:\/\/api\.census\.gov\/data\/timeseries\/intltrade\//, to: () => 'https://www.census.gov/foreign-trade/data/index.html' },
  // USITC HTS export service -> the HTS search for the same heading.
  { re: /^https:\/\/hts\.usitc\.gov\/reststop\//, to: (_m, u) => `https://hts.usitc.gov/search?query=${encodeURIComponent(u.searchParams.get('from') ?? '0409')}` },
]

/** The address to open for an official source address (see the comment at the top). */
export function pageUrl(url: string): string
export function pageUrl(url: string | null | undefined): string | null
export function pageUrl(url: string | null | undefined): string | null {
  if (!url) return null
  if (!/^https?:\/\//i.test(url)) return url
  let u: URL
  try {
    u = new URL(url)
  } catch {
    return url
  }
  for (const r of RULES) {
    const m = url.match(r.re)
    if (m) return r.to(m, u)
  }
  return url
}

/** True when `pageUrl` opens the publisher's page instead of the exact address (shown in the link's tooltip). */
export function isMappedUrl(url: string | null | undefined): boolean {
  return !!url && pageUrl(url) !== url
}
