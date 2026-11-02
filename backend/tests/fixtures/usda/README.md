# USDA fixtures: RECONSTRUCTED, not captured live

**None of the files in this folder was downloaded from a USDA server.** The development sandbox
cannot reach `www.ams.usda.gov`, `esmis.nal.usda.gov`, `api.fas.usda.gov` or
`quickstats.nass.usda.gov`. Every fixture was rebuilt by hand from the documented formats in
`docs/research/usda.json` and the documentation listed below.

**All numbers are illustrative.** A few values are copied from search snippets of real issues
(for example `IDAHO Clover Extra Light Amber $1.90`, `ARGENTINA Light Amber 1.44-1.73`,
`URUGUAY Honey Dew Light Amber $1.30`, NASS price $3.05/lb for 2025 and $2.41/lb for 2024).
Never use these files as market data.

Check every format against the first live run, and replace these fixtures with recorded ones
when network access is available. The parsers report anything they cannot recognise through
`ctx.warn`.

| File | What it reconstructs | Documentation |
|---|---|---|
| `fvmhoney_2026-06-30.txt` / `.pdf` | AMS National Honey Report, current layout (after Jan 2025). Prices are printed in dollars although the heading says "cents". The issue has prices paid to US beekeepers, prices paid to Canadian beekeepers (in U.S. currency), prices paid to importers, CBP/ACE import tables by HTS-10, an export note about the 2026 funding lapse, and a weather-map page. It has no narrative. | https://www.ams.usda.gov/mnreports/fvmhoney.pdf , https://mymarketnews.ams.usda.gov/viewReport/2901 |
| `fvmhoney_2025-09-30.txt` / `.pdf` | Same layout, a smaller issue. "DAKOTA" is used as a region label, Uruguay is quoted as "ELA", and there is one ACE table. | https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/7p88fj37r/rr173w627/FVMHONEY.PDF (the real Sept 30, 2025 issue, never opened) |
| `fvmhoney_2024-12-31.txt` / `.pdf` | Legacy layout (before 2025). Headings are upper case, prices are in cents (`195.00`, `210-225`), and the issue includes the "COLONY, HONEY PLANT AND MARKET CONDITIONS" narrative. | https://esmis.nal.usda.gov/publication/national-honey-report |
| `make_fixture_pdfs.py` | Renders the `.txt` layouts to PDF with fpdf2 (a dev-only dependency). The font is proportional Helvetica, columns are space-aligned and unruled, and headings are bold. | — |
| `esmis_fvmhoney_page0.json` | ESMIS `GET /api/v1/release/findByIdentifier/FVMHONEY?page=0`. The response shape follows the OpenAPI document. Release ids and the `fixture0001/fixture0002` path are invented. The 2025-09-30 file URL is a real archive path. | https://esmis.nal.usda.gov/api-documentation , https://esmis.nal.usda.gov/sites/default/files/swagger/esmis_public_api.yaml |
| `gats_release_dates.json` | FAS GATS `GET /api/gats/census/data/imports/dataReleaseDates`. Monthly 2026 releases are followed by the 2026-06-24 annual revision of 2023-2025. | https://apps.fas.usda.gov/opendatawebV2/assets/swagger/swagger.json |
| `gats_imports_{AR,VM,CH}_YYYYMM.json` | FAS GATS `GET /api/gats/censusImports/partnerCode/{p}/year/{y}/month/{m}`. Field names follow the recorded SDK fixture quoted in the research. Each file mixes honey lines (HS 0409) with non-honey lines. The China file has no honey line. | https://pypi.org/project/xippios-usda-gats/ |
| `gats_commodities.json` | FAS GATS `GET /api/gats/commodities`. The response shape (`hS10Code`, `commodityDescription`) is **unverified**. The honey HS-10 descriptions are also **unverified**: sources disagree on which suffix is which colour, so the collector reads the colour from the description text. | https://apps.fas.usda.gov/opendatawebV2/ |
| `nass_honey_national.json` | NASS Quick Stats `GET /api/api_GET/?commodity_desc=HONEY&source_desc=SURVEY&agg_level_desc=NATIONAL&format=JSON`. Keys follow the official API page sample. The honey `short_desc` strings for price, yield, stocks and colonies are **unverified**. | https://quickstats.nass.usda.gov/api |
