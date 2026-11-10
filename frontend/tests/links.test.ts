// Source links: a person opening a figure's source must land on a page they can read. Machine-only
// addresses (data services answering raw JSON/XML, bulk archives of tens of MB) open the SAME
// publisher's own page for that dataset; everything else opens exactly as stored. The addresses
// below are real ones stored by the collectors (database of 5 Nov 2026); every target was opened
// and checked that day.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isMappedUrl, pageUrl } from '@/lib/links'

const MAPPED: [string, string][] = [
  ['https://comexbe.indec.gob.ar/public-api/search/?commerceType=export&year=2023&period=month&countryQuery=allCountries&products=%5B%2204090000%22%5D&countries=%5B%5D',
    'https://comex.indec.gob.ar/#/search'],
  ['https://api-comexstat.mdic.gov.br/general?language=en', 'https://comexstat.mdic.gov.br/en/geral'],
  ['https://apisidra.ibge.gov.br/values/t/74/n1/all/n3/all/v/106,215/p/2015-2026/c80/2687', 'https://sidra.ibge.gov.br/tabela/74'],
  ['https://datos.magyp.gob.ar/dataset/15fbd380-fa31-436c-9283-457c23e30ecc/resource/fcf61106-a82c-4ce7-9997-a7f0f40345b5/download/renapa-productores-apicolas.csv',
    'https://datos.magyp.gob.ar/dataset/15fbd380-fa31-436c-9283-457c23e30ecc'],
  ['https://data.gov.ua/dataset/c125270a-f24e-4fb3-80cb-ed8e641eb61e/resource/8e0307dc-4fab-4597-828d-afb6d89298e1/download/bi_trade_2026-10_en-csv.gz',
    'https://data.gov.ua/dataset/c125270a-f24e-4fb3-80cb-ed8e641eb61e/resource/8e0307dc-4fab-4597-828d-afb6d89298e1'],
  ['https://www.aduana.cl/aduana/site/docs/20241112/20241112153724/salidas_2024.csv',
    'https://www.aduana.cl/base-de-datos-operaciones-de-salida/aduana/2024-11-12/153724.html'],
  ['https://www.aduana.cl/aduana/site/docs/20181214/20181214101258/expo_pais_sa_monto_0112_2025.xlsx',
    'https://www.aduana.cl/exportacion-por-pais-y-codigo-arancelario/aduana/2018-12-14/101258.html'],
  ['https://api.tech.ec.europa.eu/agrifood/api/taxud/weeklyData/import?sectors=Honey&marketingYears=2024',
    'https://agridata.ec.europa.eu/extensions/DashboardTaxud/TaxudWeeklyImport-m.html'],
  ['https://www.trade-tariff.service.gov.uk/xi/api/v2/commodities/0409000010', 'https://www.trade-tariff.service.gov.uk/xi/commodities/0409000010'],
  ['https://www.trade-tariff.service.gov.uk/xi/api/v2/measures/20000614', 'https://www.trade-tariff.service.gov.uk/xi/headings/0409'],
  ['https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409?format=JSON&lang=EN&freq=M&reporter=AT&product=04090000&flow=1&flow=2',
    'https://ec.europa.eu/eurostat/web/international-trade-in-goods/database'],
  ['https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip', 'https://www.fao.org/faostat/en/#data/QCL'],
  ['https://bulks-faostat.fao.org/production/Prices_E_All_Data_(Normalized).zip', 'https://www.fao.org/faostat/en/#data/PP'],
  ['https://faostatservices.fao.org/api/v1/en/data/QCL?area=106&item=1182', 'https://www.fao.org/faostat/en/#data/QCL'],
  ['https://api.fas.usda.gov/api/gats/censusImports/partnerCode/AR/year/2026/month/08', 'https://apps.fas.usda.gov/gats/default.aspx'],
  ['https://bulks-faostat.fao.org/production/Trade_CropsLivestock_E_All_Data_(Normalized).zip', 'https://www.fao.org/faostat/en/#data/TCL'],
  ['https://eicindia.gov.in/api/facilities', 'https://eicindia.gov.in/offerings/commodity-wise-facilities?tab=animal'],
  ['https://nube.agricultura.gob.mx/cierre_pecuario/?xajax=reporte2&xajaxargs%5B%5D=2025', 'https://nube.agricultura.gob.mx/cierre_pecuario/'],
  ['https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=T2M&community=AG&longitude=-0.43&latitude=39.15&start=2025&end=2026&format=JSON',
    'https://power.larc.nasa.gov/data-access-viewer/'],
  ['https://api.uktradeinfo.com/OTS?%24apply=filter%28%28CommodityId+eq+4090000%29%29', 'https://www.uktradeinfo.com/trade-data/ots-custom-table/'],
  ['https://api.uktradeinfo.com/Export?%24filter=CommodityId+eq+4090000&%24expand=Trader', 'https://www.uktradeinfo.com/find-uk-traders/'],
  ['https://api.census.gov/data/timeseries/intltrade/imports/hs?get=CTY_CODE&COMM_LVL=HS6&I_COMMODITY=040900&time=from+2023-11+to+2024-10',
    'https://www.census.gov/foreign-trade/data/index.html'],
  ['https://hts.usitc.gov/reststop/exportList?from=0409&to=0410&format=JSON&styles=false', 'https://hts.usitc.gov/search?query=0409'],
]

test('machine-only official addresses open the same publisher\'s page for the dataset', () => {
  for (const [stored, page] of MAPPED) {
    assert.equal(pageUrl(stored), page, stored)
    assert.ok(isMappedUrl(stored), stored)
  }
})

test('UN Comtrade opens the same query on UN Comtrade\'s own Trade Data page', () => {
  const page = new URL(pageUrl('https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=124&period=2018&cmdCode=0409&flowCode=X&partner2Code=0&customsCode=C00&motCode=0&maxRecords=500&format=JSON'))
  assert.equal(page.origin + page.pathname, 'https://comtradeplus.un.org/TradeFlow')
  assert.equal(page.searchParams.get('Frequency'), 'A')
  assert.equal(page.searchParams.get('Reporters'), '124')
  assert.equal(page.searchParams.get('period'), '2018')
  assert.equal(page.searchParams.get('CommodityCodes'), '0409')
  assert.equal(page.searchParams.get('Flows'), 'X')
  assert.equal(page.searchParams.get('Partners'), '0')
})

test('pages, documents, files and news open exactly as stored', () => {
  for (const u of [
    'https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210035301',
    'https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/1c18g901j/s1786g65f/FVMHONEY.PDF',
    'https://herramientas.uruguayxxi.gub.uy/sistema_de_estadistica/filtros.php?t=mes&pr=&e=&a=2026&pa=&cat=Todos&ncm=0409',
    'https://www.ismeamercati.it/api-miele',            // "api" = bees: a page, not a data service
    'https://veriportali.tuik.gov.tr/api/tr/data/downloads?t=i&pid=58015&p=x', // TÜİK's official Excel table
    'https://www.inegi.org.mx/sistemas/Olap/Proyectos/bd/continuas/comex/comex_bcmm_mensual2023.asp',
    'https://www.trade-tariff.service.gov.uk/xi/headings/0409',
    'https://www.federalregister.gov/documents/2026/09/14/2026-18701/raw-honey-from-argentina-preliminary-results',
    '/api/reports/23/file',                               // the copy of a report kept by Paladex
  ]) {
    assert.equal(pageUrl(u), u)
    assert.equal(isMappedUrl(u), false)
  }
  assert.equal(pageUrl(null), null)
  assert.equal(pageUrl(undefined), null)
})
