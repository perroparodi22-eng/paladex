# UN Comtrade fixtures: mostly RECONSTRUCTED; `real_*` files are live captures

## Real captures (2026-11-04)

Archived by the first live run of `un_comtrade` on 2026-11-04 (keyless preview), unmodified except
the partner reference, which is trimmed:

| File | URL |
|---|---|
| `real_preview_A_M_251_2021.json` | `https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=251&period=2021&cmdCode=0409&flowCode=M&partner2Code=0&customsCode=C00&motCode=0&maxRecords=500&format=JSON&breakdownMode=classic&includeDesc=true` (France, imports 2021) |
| `real_preview_A_X_76_2018.json` | same with `reporterCode=76&period=2018&flowCode=X` (Brazil, exports 2018) |
| `real_partner_areas_trimmed.json` | `https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json`, trimmed to the 106 entries of the partner codes in the two previews plus 97, 492 and 568 (the real file has 310 entries and no BOM) |

They show the residual partner areas the API uses besides countries: 899 "Areas, nes" (`_X `),
577 "Other Africa, nes" (`F19`), 837 "Bunkers" (`X1 `), and 490 "Other Asia, nes" (`S19`, Taiwan).
The live run also met 568 "Other Europe, nes" (`E19`). These rows are stored under `M<code>` and
logged at INFO (`comtrade.RESIDUAL_PARTNER_AREAS`); only a code that is neither a country nor such
an area is a warning. Real rows have `partnerDesc`/`reporterDesc` filled (`includeDesc=true`).

## Reconstructed files

The other files were **reconstructed from documentation**. They were not downloaded from
`comtradeapi.un.org`, because the development sandbox cannot reach that host. The **values
are illustrative**: they only exercise the parser, so never use them as real trade statistics.

Each file follows the documented response format:

* Envelope `{"elapsedTime", "count", "data": [...], "error"}`. `data` and `count` are verified
  in UN Comtrade's official Python client. `elapsedTime` and `error` are documented from memory
  in `docs/research/comtrade.json`.
* Row field names follow the rOpenSci *comtradr* raw-to-tidy column mapping (`ct_pretty_cols`,
  `data-raw/DATASET.R`): `typeCode, freqCode, refPeriodId, refYear, refMonth, period,
  reporterCode, reporterISO, reporterDesc, flowCode, flowDesc, partnerCode, partnerISO,
  partnerDesc, partner2Code, ..., cmdCode, aggrLevel, customsCode, motCode, qtyUnitCode, qty,
  isQtyEstimated, netWgt, isNetWgtEstimated, grossWgt, cifvalue, fobvalue, primaryValue,
  legacyEstimationFlag, isReported, isAggregate`. That mapping also lists case variants
  (`isnetWgtEstimated`, `cifValue`, `CIFValue`). The Serbia and Germany rows in
  `preview_A_M_380_2025.json` deliberately use those variants.
* Preview rows have `*Desc = null`, as a third-party scraper reported for the keyless tier. Some
  `partnerISO` / `reporterISO` values are also null, to exercise the fallback to Comtrade code
  lookups (USA 842, France 251, 490 "Other Asia, nes" = Taiwan with pseudo ISO `S19`).
* `getda_*.json` follow the reconstructed `getDa` sample. Only `data`, `reporterCode`, `period`
  and `classificationCode` are verified; `firstReleased` and `lastReleased` are from memory.
* `partner_areas.json` follows the reconstructed `partnerAreas.json` sample: a `results` list
  with capitalised keys and a UTF-8 BOM, which the official client decodes as `utf-8-sig`.

Rows included on purpose: the World total (partner 0), an EU aggregate (97, excluded), a
customs-procedure sub-total (`customsCode` C01, skipped), a malformed value (`"n/a"`), an
estimated weight, a missing net weight, a tiny 400 kg flow (no unit value), an unknown
"Areas, nes" partner (899, stored as `M899`) and a partner outside Paladex's country table
(Falkland Islands 238, resolved through the reference file; Zambia, used before, is now in the
country table).

Documentation used:

* https://github.com/uncomtrade/comtradeapicall (`PreviewGet.py`, `DataAvailability.py`, README)
* https://pypi.org/project/comtradeapicall/
* https://github.com/ropensci/comtradr/blob/main/data-raw/DATASET.R (column mapping)
* https://docs.ropensci.org/comtradr/articles/comtradr.html
* https://comtradeplus.un.org/ApiDocs
* `docs/research/comtrade.json` (full research notes with confidence levels)

Before you rely on the parser in production, log the first live response and compare its field
list with these files.
