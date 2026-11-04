# NASA POWER fixtures (weather collector)

All files are **real answers captured live from NASA POWER on 4 November 2026** (no edits). The
two Extremadura points of `reference/regions.py` (region `ESP-EXT`) were used:

| File | Request |
|---|---|
| `monthly_plasencia_1991_2026.json` | `GET https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=T2M%2CPRECTOTCORR&community=AG&longitude=-6.09&latitude=40.03&start=1991&end=2026&format=JSON` (MERRA-2; months after 2026-09 are `-999`) |
| `monthly_badajoz_1991_2026.json` | same, `longitude=-6.97&latitude=38.88` |
| `monthly_plasencia_2024_2026.json` | same as the first, `start=2024&end=2026` (the request made once the 1991-2020 normals are cached) |
| `daily_plasencia_20261001_20261031.json` | `GET .../daily/point?parameters=T2M%2CPRECTOTCORR&community=AG&longitude=-6.09&latitude=40.03&start=20261001&end=20261031&format=JSON` (header `sources: ["GEOSIT"]`: October 2026 is entirely near-real-time data) |
| `daily_badajoz_20261001_20261031.json` | same, Badajoz |
| `daily_plasencia_20260901_20261031.json` | same as the Plasencia daily, from `20260901` (header `sources: ["MERRA2", "GEOSIT"]`) |
| `daily_plasencia_20261001_20261104.json` | the Plasencia daily request with `end=20261104` (the capture day): days after 2026-11-01 are `-999`, so November is an incomplete month; used by the pure-function test of incomplete months |
| `daily_badajoz_20261001_20261104.json`, `daily_plasencia_20260901_20261104.json` | the same requests with `end=20261104` (kept for reference; same values as the `..._20261031` captures) |
| `error_422_invalid_latitude.json` | the 422 answer to `latitude=95.00` |

The collector asks the daily API only up to the last day of the newest complete month, hence the
`..._20261031` captures in the end-to-end tests.

The test of the provisional -> published revision derives one input in code from
`monthly_plasencia_1991_2026.json` (September 2026 set back to `-999`, as the monthly API showed it
before September was processed); the derivation is written out in `tests/test_weather.py`.

Notable real values used by the tests: Plasencia August 2025 is +2.62 °C over its 1991-2020
normal (the August 2025 Iberian heat wave); October 2026 (provisional, from the daily data) is
+2.63 °C with 33.7 % of normal precipitation.
