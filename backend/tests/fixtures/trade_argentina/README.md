# Fixtures for `collectors/trade_argentina.py` (`ar_official_exports`)

Every file here is a **real capture**, byte for byte, of INDEC's public foreign-trade query system
(the JSON back end of https://comex.indec.gob.ar). They were taken on **2026-11-05** by the first
live run of the collector, copied from its raw archive (`data/raw/ar_official_exports/`). Tests
build their variants from these files in code: a new release, a revision, an inconsistent month,
schema drift. No data file was typed in by hand.

| File | URL (GET, no key) |
|---|---|
| `real_indec_staticData_2026-11-05.json` | https://comexbe.indec.gob.ar/public-api/staticData |
| `real_indec_exports_YYYY_by_destination.json` | https://comexbe.indec.gob.ar/public-api/search/?commerceType=export&year=YYYY&period=month&countryQuery=allCountries&products=%5B%2204090000%22%5D&countries=%5B%5D |
| `real_indec_exports_YYYY_total.json` | the same with `countryQuery=totalImported` (INDEC's own monthly total of NCM 04090000) |

`YYYY` = 2023, 2024, 2025, 2026. On the capture date INDEC's newest month was 2026-09 (`lastYear`
2026, `lastMonth` 9). Its "Última fecha de actualización" was 2026-10-16 for 2026, 2026-03-19 for
2025, 2025-04-16 for 2024 and 2026-04-20 for 2023.

What the captures show (used as test expectations):

* Destination-months with fewer than three exporters come back as `"isConfidential": true` with
  `amount` 0 and `weight` 0, which INDEC's own page shows as "s". There are 92 such cells in 2026,
  including Italy in 6 of 9 months. INDEC adds their trade to the destination "Confidencial"
  (`id` 999, `iso2` "ZZ"). The total (`totalImported`) equals the visible destinations plus that
  bucket, exactly, in every month of 2023-2026.
* 2024: total 85,736,012.88 kg / USD 186,316,696.62, of which visible destinations
  78,375,273.68 kg / USD 170,816,007.85 (UN Comtrade's Argentina 2024 world total is
  78,375,279.5 kg / USD 170,816,007.85) and the confidential bucket 7,360,739.2 kg /
  USD 15,500,688.77.
* United States, August 2026: USD 15,140,656.83 FOB, 5,130,298.9 kg.

The same answers had already been captured with curl earlier on 2026-11-05, while the route was
being studied. The 2026 destination file is byte-identical to that capture.
