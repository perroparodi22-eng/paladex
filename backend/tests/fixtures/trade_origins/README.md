# Fixtures for `collectors/trade_origins.py`

All files are REAL answers captured on **2026-11-05** from the development sandbox, stored gzipped
(`.gz`) to keep the repository small. Tests read them with `gzip.decompress`. Nothing here was written
by hand; the variants the tests need (a revision, a short download, another product, a new month) are
built from these files in `tests/test_trade_origins.py`.

## Ukraine: State Customs Service open data (`ua_honey_exports`)

| File | Source |
|---|---|
| `real_datagovua_package_show_scsu-bi-trade-src-en_2026-11-05.json.gz` | `GET https://data.gov.ua/api/3/action/package_show?id=scsu-bi-trade-src-en` (complete answer, 101 KB: 119 resources, 2017-01..2026-10; 2023-05 is listed twice) |
| `real_ua_bi_trade_2026-09_en_excerpt.csv.gz` | EXCERPT of `https://data.gov.ua/dataset/c125270a-f24e-4fb3-80cb-ed8e641eb61e/resource/274d7741-862c-4389-ace6-b6c5d45c1100/download/bi_trade_2026-09_en-csv.gz` (10.8 MB, 160,461 rows, MD5 42825b5cea7816229505a69ff181b84f): the header, all 73 honey rows (UKTZED 0409000000, both flows) and the first 300 non-honey rows of the file, verbatim, re-gzipped |
| `real_ua_bi_trade_2026-08_en_honey_rows.csv.gz` | the header and the 47 honey rows (of 156,637) of `.../bi_trade_2026-08_en-csv.gz`, verbatim, as the collector archives them |
| `real_ua_bi_trade_2026-10_en_honey_rows.csv.gz` | the header and the 60 honey rows (of 164,296) of `.../bi_trade_2026-10_en-csv.gz`, verbatim, as the collector archives them |

Because the monthly files are excerpts, the tests replace `file_hash_sum` and `size` in the package
answer with those of the bytes served.

## Mexico: INEGI, Balanza Comercial de Mercancías de México (`mx_honey_exports`)

| File | Source |
|---|---|
| `real_inegi_bcmm_start_2026-11-05.html.gz` | `GET https://www.inegi.org.mx/sistemas/Olap/Proyectos/bd/continuas/comex/comex_bcmm_mensual2023.asp` (cube "enero 2023 - agosto 2026", "Cifras ajustadas de enero 2023 a diciembre 2025, a partir de enero 2026 datos revisados.") |
| `real_inegi_honey_exports_<year>_p<page>.html.gz` | `POST https://www.inegi.org.mx/sistemas/olap/consulta/general_ver4/MDXQueryDatos.asp` with the form fields of `trade_origins.mx_query_fields(cube, year, page)`: honey exports (fracción 0409.00.01) of 2023 (5 pages, 146 rows), 2024 (4 pages, 128 rows), 2025 (5 pages, 137 rows) and 2026 (3 pages, 93 rows) by month and destination, plus INEGI's Total. Captured by the collector's live run (its raw archive), byte for byte |
