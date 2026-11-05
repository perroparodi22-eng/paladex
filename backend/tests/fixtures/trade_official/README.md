# Official national trade fixtures: `real_comex_*` are live captures; the others are RECONSTRUCTED

## Real Comex Stat captures (2026-11-04)

Downloaded from `https://api-comexstat.mdic.gov.br` on 2026-11-04, unmodified:

| File | Request | What it shows |
|---|---|---|
| `real_comex_dates_updated_2026-10-06.json` | `GET /general/dates/updated` | `{"data": {"updated": "2026-10-06", "year": "2026", "monthNumber": "09"}, "success": true, ...}` |
| `real_comex_filters.json`, `real_comex_details.json` | `GET /general/filters`, `GET /general/details` | `{"data": {"list": [{"filter": "country", "text": "Países"}, ...], "0": "pt"}}`: 22 names, including `ncm`, `country`, `state`, `heading` |
| `real_comex_metrics.json` | `GET /general/metrics` | `{"data": {"list": [{"id": "metricFOB", ...}, {"id": "metricKG", ...}, ...]}}` |
| `real_comex_general_empty_2025-10_2026-09.json` | `POST /general?language=en`, the first live run's body: period 2025-10..2026-09, filter `ncm` `["04090000"]`, details `country`, `state`, `ncm` | `{"data": {"list": []}, "success": true, ...}` although those months have data (see below) |
| `real_comex_general_2024-01_country.json` | `POST /general?language=en`, period 2024-01..2024-01, `monthDetail` false, filter `ncm` `["04090000"]`, detail `country` | 30 rows `{"year", "country", "metricFOB", "metricKG"}`; United States 2,819,777 USD / 1,017,440 kg |
| `real_comex_general_2023-01_2026-12_trimmed.json` | `POST /general?language=en` as the fixed collector sends it: period 2023-01..2026-12, `monthDetail` true, filter `ncm` `["04090000"]`, details `country`, `state`, `ncm` | **trimmed** from 5,288 rows (825 KB, 45 months 2023-01..2026-09, 102 destinations) to the 484 rows of United States, Germany, Canada, Isle of Man, Marshall Islands and Brazil in 2024 and 2026-07..09, plus United States 2023-01/02; rows unmodified. Row keys: `coNcm, year, monthNumber, country, state, ncm, metricFOB, metricKG`. United States 2024 sums to 78,637,770 USD / 29,984,910 kg, exactly what UN Comtrade republishes for Brazil's 2024 honey exports to the US; all destinations of 2024 sum to 100,559,616 USD (Comtrade World: 100,559,616 USD). |
| `real_comex_rate_limited_429.json` | `POST /general` while rate-limited | HTTP 429, `{"error": {"code": 429, "message": "Você excedeu o limite de solicitações. Por favor, tente novamente em 10 segundos."}}`. Live, the refusal lasted minutes, not 10 s. |

What the live API showed about `POST /general` (the body format of the docs at
`https://api-comexstat.mdic.gov.br/docs/doc.yaml` is the one the collector sends):

* `{"flow": "export", "monthDetail": true, "period": {"from": "2025-10", "to": "2026-09"}, "filters":
  [{"filter": "ncm", "values": ["04090000"]}], "details": ["country", "state", "ncm"], ...}` answers
  `{"data": {"list": []}, "success": true}` (the first live run's "no honey export rows"), while the
  same filter for a period inside one year answers rows. `period` is read as a year range plus a
  month range applied to each year (like the web form), so a range across a year boundary must ask
  for whole years (`trade_official.comex_query_period`).
* Filter values are strings: `"04090000"` works, the number `4090000` answered an empty list for
  2026-07..2026-09 (a probe not kept here), months the whole-year answer shows to have rows.
* Rows carry `year`, the detail names (`country` as an English name with `language=en`), and the
  metrics as strings (`"metricFOB": "2819777"`); no country code column.

## Reconstructed files

The development sandbox could not reach `api-comexstat.mdic.gov.br` or `api.census.gov` when the
files below were written (outbound traffic was blocked). **None of them was downloaded from the
real source.**
They were rebuilt from the documentation and evidence in
`docs/research/official_south_america.json` (Comex Stat),
`docs/research/official_north_america_oceania.json` and
`docs/research/official_tariffs_trade_policy.json` (Census), so that the formats are as close
as possible to the real ones. **All numbers are illustrative test data, not market data.**

`build_fixtures.py` regenerates every file:
`cd backend && python tests/fixtures/trade_official/build_fixtures.py`.

On the first live run, compare these fixtures with the real answers archived under
`data/raw/br_comexstat/` and `data/raw/us_census_trade/`, and update them where they differ.
Both collectors check the live API before they trust it (Comex Stat `/general/filters`,
`/details` and `/metrics`; Census `variables.json`), and they fail loudly on schema drift.

| File | Collector | What is reconstructed, and from what |
|---|---|---|
| `comex_dates_updated_*.json` | `br_comexstat` | `GET /general/dates/updated`. The research only says "latest month loaded". The `{"data": {"updated", "year", "monthNumber"}, "success", "message", "language"}` envelope follows the API's usual envelope and is **unverified**. The parser also accepts close variants: a dd/mm/yyyy date, `month`/`coMes`, or a missing date (warned). |
| `comex_filters.json`, `comex_details.json`, `comex_metrics.json` | `br_comexstat` | `GET /general/filters`, `/details`, `/metrics`. The names `ncm`, `country`, `state`, `heading`, `subHeading`, `via`, `metricFOB`, `metricKG`, `metricStatistic`, `metricFreight`, `metricInsurance` and `metricCIF` come from the research (the comexr R package documentation). The object shapes (`filter`/`detail`/`id` + `text`) are **unverified**, and the parser accepts any of them. |
| `comex_general_*.json` | `br_comexstat` | `POST /general?language=en`, body `{"flow":"export","monthDetail":true,"period":{...},"filters":[{"filter":"ncm","values":["04090000"]}],"details":["country","state","ncm"],"metrics":["metricFOB","metricKG"]}`. The row shape follows the research's reconstructed sample (`year`, `monthNumber`, `country`, `state`, `ncm`, `metricFOB`, `metricKG`), with the code/name pair `coNcm` + `ncm` the research warns about. Numbers alternate between strings and JSON numbers. One file per former 12-month query window; the backfill is now one whole-year query (2023-01..2026-12), which the tests answer with the three files merged. The 2025-10..2026-09 window is the newest release (2026-10-06). The 2026-08..2026-10 window is the next release (2026-11-05). In it, United States 2026-08 is revised, Germany 2026-08 falls below 1 t, and Netherlands 2026-09 is withdrawn. |
| `comex_rate_limited.json` | `br_comexstat` | The research says third-party clients see frequent rate-limit answers asking them to retry after about 10 s. The exact body is **unknown**: this one is a guess that the detector (`success: false` + a "too many requests" message, or HTTP 429) handles. |
| `census_variables.json` | `us_census_trade` | `GET .../imports/hs/variables.json`: the documented `{"variables": {NAME: {label, predicateType, ...}}}` shape. Variable names are from the research (`CTY_CODE`, `CTY_NAME`, `I_COMMODITY`, `I_COMMODITY_SDESC`, `GEN_VAL_MO`, `GEN_QY1_MO`, `UNIT_QY1`, `CON_VAL_MO`, `CON_QY1_MO`, `GEN_CIF_MO`, `DUT_VAL_MO`, `CAL_DUT_MO`, `COMM_LVL`). `CON_CIF_MO`, `SUMMARY_LVL` and the labels are from memory (**unverified**; both are optional in the collector). |
| `census_hs6_*.json` | `us_census_trade` | `GET .../imports/hs?get=...&COMM_LVL=HS6&I_COMMODITY=040900&time=from YYYY-MM to YYYY-MM`. The layout is the documented Census one: an array of arrays, header first, every value a string, and the predicate variables (`COMM_LVL`, `I_COMMODITY`, `time`) repeated at the end. The total row (`-`, "TOTAL FOR ALL COUNTRIES") and the country groupings (`0003`, `3XXX`, `5XXX`, `SUMMARY_LVL=CGP`) are reconstructed from memory of the API. Country codes are Census Schedule C (Argentina 3570, Brazil 3510, India 5330, Vietnam 5520, Ukraine 4623, Mexico 2010, Canada 1220, Uruguay 3550, Turkey 4890, from the research; New Zealand 6141 and Singapore 5590 are from memory). The 2026-06..2026-10 file is the trailing window asked again before the next release, with the same numbers. The 2026-06..2026-11 file is the next monthly release. In it, Argentina 2026-07 is revised, India 2026-07 falls below 1 t, Ukraine 2026-07 is withdrawn and 2026-09 is new. |
| `census_hs10_*.json` | `us_census_trade` | Same query with `COMM_LVL=HS10&I_COMMODITY=0409*`. The wildcard is **unverified** (research: "if it fails, request each HS-10 code"), and the collector falls back to one query per line. HS-10 codes are from the research (0409.00.00.05 / .10 / .35 / .45 / .56 / .65). The `I_COMMODITY_SDESC` texts are invented. Only some origin-months have lines. |
| `census_invalid_key.html` | `us_census_trade` | The HTML "Invalid Key" page Census serves instead of data for a bad key (wording from memory). |

Documentation and evidence used:

* Comex Stat API: https://api-comexstat.mdic.gov.br/docs and https://comexstat.mdic.gov.br
* comexr (R client) vignette: https://cran.nics.utk.edu/cran/web/packages/comexr/vignettes/querying-trade-data.html
* comexr README: https://packages.oit.ncsu.edu/cran/web/packages/comexr/readme/README.html
* MCP client for Comex Stat: https://glama.ai/mcp/servers/luizzzvictor/mcp-comexstat
* Comex Stat bulk files (not used; future fallback): https://rdrr.io/github/datazoompuc/datazoom.amazonia/src/R/comex.R
* Census International Trade API: https://www.census.gov/data/developers/data-sets/international-trade.html
* Census imports/hs variables: https://api.census.gov/data/timeseries/intltrade/imports/hs/variables.html
* Census API examples: https://api.census.gov/data/timeseries/intltrade/imports/enduse/examples.html
* Census key signup: https://api.census.gov/data/key_signup.html
* Census Schedule C country codes: https://www.census.gov/foreign-trade/schedules/c/countrycode.html
