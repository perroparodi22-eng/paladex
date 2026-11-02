# UN Comtrade fixtures: RECONSTRUCTED, not captured live

These files were **reconstructed from documentation**. They were not downloaded from
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
(Zambia 894, resolved through the reference file).

Documentation used:

* https://github.com/uncomtrade/comtradeapicall (`PreviewGet.py`, `DataAvailability.py`, README)
* https://pypi.org/project/comtradeapicall/
* https://github.com/ropensci/comtradr/blob/main/data-raw/DATASET.R (column mapping)
* https://docs.ropensci.org/comtradr/articles/comtradr.html
* https://comtradeplus.un.org/ApiDocs
* `docs/research/comtrade.json` (full research notes with confidence levels)

Before you rely on the parser in production, log the first live response and compare its field
list with these files.
