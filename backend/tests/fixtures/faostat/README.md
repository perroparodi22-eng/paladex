# FAOSTAT fixtures: RECONSTRUCTED, not captured live

These files were **reconstructed from documentation**. They were not downloaded from
`bulks-faostat.fao.org` or `faostatservices.fao.org`, because the development sandbox cannot
reach any fao.org host. The **values are illustrative**: they only exercise the parser, so never
use them as real statistics. Research notes: `docs/research/fao.json`.

## Bulk downloads (no account)

* `datasets_E.json` follows the catalogue shape recorded live by xippios-faostat on 2026-10-29:
  `{"Datasets": {"-xmlns:xsi": ..., "Dataset": [{DatasetCode, DatasetName, Topic,
  DatasetDescription, Contact, Email, DateUpdate, CompressionFormat, FileType, FileSize,
  FileRows, FileLocation}]}}`. `FileSize` is text in KB, `FileRows` a number, `DateUpdate` a time
  without a zone (`2026-10-02T00:00:00`). The RL entry reuses the recorded example values; the QCL
  `DateUpdate` (2025-12-31) matches the recorded `date_update`; TCL's `267104KB` is the recorded
  size. Other sizes, row counts and dates are illustrative. The QCL, PP, TCL and TM ZIP file names
  are from memory (unverified); the collector always takes them from `FileLocation`.
* `bulk/*_E_All_Data_(Normalized).csv` follow the normalized-table layout recorded for RL: UTF-8,
  comma-separated, every non-empty cell quoted, empty cells bare, CRLF line endings, M49 codes with
  a leading apostrophe (`'032`), values with six decimals, element codes as DISPLAY codes (5510).
  Columns: `Area Code, Area Code (M49), Area, Item Code, Item Code (CPC), Item, Element Code,
  Element, Year Code, Year, Unit, Value, Flag, Note` (`Item Code (CPC)` is expected, unverified).
  The PP file carries `Months Code, Months` and no `Note`, as the API's PP rows do (bulk layout
  unverified). TCL display element codes 5610/5622/5910/5922 and the unit `1000 USD` are from memory;
  the collector also recognises the elements by label. Bee stocks (item 1181, element `Stocks`,
  unit `No`) follow the research's expectation (unverified).
* `bulk/Flags.csv` is a small code list, zipped next to the table as `<Name>_E_Flags.csv` the way
  every bulk ZIP carries its code lists. The tests build the ZIPs from these CSVs at run time.

Rows included on purpose: a year before 1991 (dropped), other items (wheat, beeswax, the TCL
"Sugar and Honey" total), the aggregates 351 "China", 265 "China (excluding intra-trade)", 5000
"World", 5707 and 57070 (EU), 41 "China, mainland" (kept as China), 186 "Serbia and Montenegro"
(Serbia before 2006), Zambia (outside Paladex's country table), a missing value flagged `M`, an
unreadable value (`n.a.`), an unknown flag `Z`, a PP monthly row, PP SLC and index elements, a zero
price, an LCU-only price (Ukraine), an LCU price before the current currency (Ukraine 1995) and an
unexpected unit (`1000 EUR`).

## API (account needed)

* `api/login.json`, `api/login_refused.json`: `POST /auth/login` answers. Keys verified in the
  faostat 2.0.1 and xippios-faostat clients (`AuthenticationResult.AccessToken`, `ExpiresIn`, ...;
  Cognito's `__type` on HTTP 400); token values are fake.
* `api/QCL_production.json`, `api/QCL_bees.json`, `api/PP.json`, `api/TCL_page*.json`: `GET
  /en/data/{domain}` with `output_type=objects`: `{"metadata": {..., "dsd": [...]}, "data": [...]}`,
  every value a string, rows printing display element codes (5510 for filter 2510). Keys verified
  from the clients' recorded answers; values illustrative. PP rows carry `Months Code` 7021
  "Annual value" and no `Note`.
* `api/TM_dimensions.json`: `GET /en/dimensions/TM/`; the shape (`data[].id`,
  `subdimensions[].id/label/coding_systems`) follows the faostat 2.0.1 client; the ids
  `reporterarea` / `partnerarea` are from memory (unverified), which is why the collector probes them.
* `api/TM_element_codes.json`: `GET /en/codes/element/TM`, shaped like the recorded TCL list
  (`code`, `label`, `parent`, `aggregate_type`); TM's codes are assumed equal to TCL's.
* `api/TM_reporter_106.json`: TM rows for reporter Italy; the reporter/partner column names
  (`Reporter Country Code`, `Partner Countries`, ...) are from memory (unverified) and are declared
  in `metadata.dsd`, which the collector reads first.

## Documentation used

* https://pypi.org/project/faostat/ (2.0.1: login, Bearer header, dimensions, `limit`)
* https://pypi.org/project/xippios-faostat/ (catalogue model, bulk CSV reader, recorded code lists)
* https://github.com/berba-q/faostat-mcp
* https://www.fao.org/faostat/en/#developer-portal
* https://www.fao.org/contact-us/terms/db-terms-of-use/en/
