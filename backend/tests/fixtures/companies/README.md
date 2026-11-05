# Honey exporters and importers by company: real captures of 5 November 2026

Every file was downloaded from the official source on **2026-11-05** (development sandbox; SIE at
20:23 UTC, HMRC at 20:37 UTC). Where a file is trimmed, this README says exactly how; names and
numbers are never edited. Tests that need a variant (a revision, a withdrawn company, a broken
answer) derive it from these files in the test code and say so.

## Uruguay: Uruguay XXI, Sistema de Información Estadística (SIE), "Por Empresa"

Query: `https://herramientas.uruguayxxi.gub.uy/sistema_de_estadistica/filtros.php?t=empresa&pr=&e=&a=2026&pa=&cat=Todos&ncm=0409`
(`t=empresa`: the "Por Empresa" button of the advanced export query, `script.js` `buscar('empresa')`;
`ncm=0409`: natural honey; `e` (one company) and `pa` (destination) empty).

| File | What it is |
|---|---|
| `real_sie_empresa_2026_page.html` | The whole answer page (1,844,433 bytes) **minus** the three autocomplete lists in its scripts (`source: [...]` emptied: every exporting company and private person with an ID, and the product names) and the default company of `#empresa_auto` (blanked): 92,718 bytes, everything else byte for byte. |

What the real page showed:

* Caption `Exportaciones por NCM: '0409', Período: 2022 - 2026` (the same caption as the monthly total:
  the rows, not the caption, say it is the company view); year columns `2022 ... 2025` and
  `2026 (ene - oct)`.
* 17 company rows, sorted by the running year, then a `Total Detalle` row equal to the sum of the
  rows in every year. Exact amounts in US$ FOB, dot thousands and decimal comma.
* The totals are the same as the SIE's monthly and destination views (`uy_honey_exports`): 2025 =
  27,928,748.53 USD; 2026 January-October = 33,100,409.13 USD.
* Largest exporters: NECTARBEE S.A. (2025: 15,571,168.32; 2026 Jan-Oct: 18,061,978.55), BUZARAM
  COMPANY S.A. (3,074,002.27; 5,750,902.81), MEGAVOR S.A (1,849,266.68; 2,343,160.27).
* Names are truncated by the SIE at 60 characters: `SOCIEDAD ANONIMA URUGUAYA DE IMPORTACIONES Y
  EXPORTACIONES (UR`. Two rows are private persons (sole traders): only their names are shown; no ID.
* The import menu of the SIE offers "Por NCM", "Por País" and "Por Mes" only: no company view.

## United Kingdom: HMRC, UK Trade Info "Find UK traders" (API)

Queries: `https://api.uktradeinfo.com/Import?$filter=CommodityId eq 4090000 and MonthId ge 202607&$expand=Trader`
and the same for `/Export` (`CommodityId` 4090000 = CN8 04090000 "Natural honey", from `/Commodity`).

| File | What it is |
|---|---|
| `real_hmrc_import_04090000_2026-07_08.json` | The real answer (48,846 bytes, 191 rows: July 2026 102, August 2026 89) with `Trader.Address1` (the street line) blanked in every row; everything else as published. |
| `real_hmrc_export_04090000_2026-07_08.json` | Same for exports (9,549 bytes, 36 rows: July 19, August 17). |

What the real answers showed:

* One row per trader and month: `TraderId` (HMRC's own trader number, not a tax ID), `CommodityId`,
  `MonthId` (YYYYMM) and the expanded `Trader` (`CompanyName`, `Address1`-`Address5`, `PostCode`).
  **No quantity and no value**: HMRC states it does not publish quantities or values of transactions,
  VAT or EORI numbers, partner countries, or traders who asked to be removed.
* The newest month published on 5 November 2026 was August 2026 (313 honey importers and 58 exporters
  appear in January-August 2026).
* Examples (importers, July 2026): NELSON HONEY UK LIMITED (published address lines Gloucester Road,
  Mitcheldean, Gloucestershire; GL17 0DS), HONEY NEW ZEALAND EUROPE LTD (Burbage, Hinckley; LE10 3ER).
  Paladex keeps "GLOUCESTERSHIRE, GL17" and "HINCKLEY, LE10".
