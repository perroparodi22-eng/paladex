# USDA fixtures

## National Honey Report (FVMHONEY) and ESMIS: REAL captures

These files were downloaded from the official USDA servers on **2026-11-04** (first live run of
the collector and a follow-up check). The PDFs are US Government works (public domain, 17 USC 105).
To keep the repository and the test run small, most PDFs are **page subsets** of the original file,
cut with `pypdf` (`PdfWriter.add_page`); the content of every kept page is unchanged. Page numbers
in the file names are those of the original issue.

| File | Original URL | What it covers |
|---|---|---|
| `real_fvmhoney_2025-03-28_p1-3-4.pdf` | https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/4j03fv56x/p841bj501/FVMHONEY.PDF (ESMIS release 2025-03-28) | Vol. XLV No. 3, market month printed as "FEBURARY 2025". Page 1 prints the US beekeeper table and the Canadian + importer tables **side by side**; the beekeeper table uses a horizontally compressed font (pdfplumber reads it as "D A K O T A"). "Extra Light" is used for Extra Light Amber. Page 3: US exports (ignored). Page 4: CBP ACE table HTS 0409000045 for Feb 2025, `$` printed in its own cell. |
| `real_fvmhoney_2026-10-30_p1-2-11.pdf` | https://www.ams.usda.gov/mnreports/fvmhoney.pdf (AMS "latest issue", fetched 2026-11-04; sha256 875fb1d6...) | Vol. XLVI No. 10, market month September 2026. Page 1: beekeeper pivot table (floral cell left blank under the row it repeats, a "(blank)" floral). Page 2: Canadian and importer tables (compressed glyphs, a range printed low > high: "$2.15 - $1.45"). Page 11: ACE table HTS 0409000045 for Sep 2026. |
| `real_fvmhoney_2024-12-26_p1-2-6.pdf` | https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/dn39zw09z/5712p3399/FVMHONEY.PDF (ESMIS release 2024-12-26) | Vol. XLIV No. 12, market month November 2024. Page 1: two columns; the beekeeper table continues at the top of the right column (OREGON ... WYOMING) before the Canadian and importer tables; label misspelt "GEORIGA". Page 2: start of the last "Colony, honey plant and market conditions" narrative. Page 6: ACE table HTS 0409000056 (title wrapped on two lines) for Nov 2024. |
| `real_fvmhoney_2025-06-30_first_p1-2.pdf` | https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/9p2928560/3n205z785/FVMHONEY.PDF (ESMIS release 2025-07-01) | June 30, 2025 issue as first released: heading "HONEY MARKET FOR THE MONTH OF JUNE 2025". |
| `real_fvmhoney_2025-06-30_corrected_p1-2.pdf` | https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/w0894925c/bn99c5321/FVMHONEY.PDF (ESMIS release 2025-07-02) | The same issue re-released as "CORRECTED COPY: HEADINGS UPDATED." with "MONTH OF MAY 2025" and the same prices. |
| `real_fvmhoney_2025-04-30_p1.pdf` | https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/4742c648m/j67332753/FVMHONEY.PDF (ESMIS release 2025-04-30) | The April 2025 issue pasted the price tables as **images**: no price can be read (the parser reports it). |
| `real_esmis_misfiled_tomato_2025-05-15_p1.pdf` | https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/ff367354m/ww72d826j/FVMHONEY.PDF (ESMIS release 2025-05-15) | ESMIS lists this file under FVMHONEY, but it is the AMS **Tomato Fax Report**. (The 2025-09-05 FVMHONEY release is likewise a National Watermelon Report.) |
| `real_esmis_fvmhoney_page0.json` | https://esmis.nal.usda.gov/api/v1/release/findByIdentifier/FVMHONEY?page=0 (fetched 2026-11-04, unchanged) | 25 rows = 13 releases (most listed twice, under `AMS` and `AMS-SC`), newest 2025-09-30: ESMIS has not received an FVMHONEY issue since Sept 2025. |

## National Honey Report from the MyMarketNews file repository: REAL captures

Downloaded from the AMS MyMarketNews file repository (the official archive of every published
issue; ESMIS has none after Sept 2025) on **2026-11-06**, during the live run that recovered the
Oct 2025 - Sept 2026 issues. PDFs are page subsets cut as above (page numbers of the original).

| File | Original URL | What it covers |
|---|---|---|
| `real_mmn_filerepo_2901_page0.html` | https://mymarketnews.ams.usda.gov/filerepo/reports?field_slug_id_value=2901 (sha256 c628a12e...) | The listing ("Mars Document" view): 50 rows, newest first (2026-10-30 back to 2023-07-26), document links relative to `/filerepo/reports` (`sites/default/files/2901/{report date}/{node id}/ams_2901_NNNNN.pdf`), a pager to `page=1` and `page=2`. Lists re-uploads (`_01` files: same bytes as an earlier issue) and two Tomato Fax Reports (2025-05-15, 2026-04-13). The Oct 31, 2025 issue is listed on 2025-11-12, as a corrected copy only. |
| `real_mmn_filerepo_2901_page1.html` | the same with `&page=1` | Rows 51-100: 2023-06-27 back to 2019-07-29. |
| `real_fvmhoney_2025-10-31_corrected_p1-2-10.pdf` | https://mymarketnews.ams.usda.gov/filerepo/sites/default/files/2901/2025-11-12/1285160/ams_2901_00078.pdf (sha256 0493f8a9...) | Vol. XLV No. 10, "CORRECTED COPY", market month September 2025 (the first issue after the federal funding lapse). Page 1: beekeeper table ("CanoLight Amber": overlapping glyphs, rows skipped and reported). Page 2: importer table. Page 10: ACE table HTS 0409000045 for Sep 2025 (Uruguay without a value). |
| `real_fvmhoney_2026-09-30_p1-2-11.pdf` | https://mymarketnews.ams.usda.gov/filerepo/sites/default/files/2901/2026-09-30/1355143/ams_2901_00094.pdf (sha256 d6e043d4...; byte-identical to the 2026-10-23 re-upload `.../1360720/ams_2901_00095_01.pdf`) | Vol. XLVI No. 9, market month August 2026: beekeeper, Canadian and importer tables, ACE table HTS 0409000045 for Aug 2026. |
| `real_fvmhoney_2026-05-29_p1-9-10.pdf` | https://mymarketnews.ams.usda.gov/filerepo/sites/default/files/2901/2026-05-29/1328060/ams_2901_00089.pdf (sha256 5a8ca750...) | Vol. XLVI No. 5. Page 9: ACE table HTS 0409000065 for Apr 2026. Page 10: an ACE table **printed without its title** (HTS code unknown): its rows are skipped, not filed under 0409000065. |

The MyMarketNews tests serve these PDFs (and, for the 2024-12-26, 2025-03-28 and 2025-05-15
rows of the real listing, the ESMIS subsets above: the same reports) at the URLs of the real listing.

Facts checked against these files (and the other 2023-2026 issues of the live run): the price
tables print US dollars per pound although their headings still say "cents"; prices refer to the
market month printed on page 1, one month before the issue date; Canadian prices are "in U.S.
currency"; the ACE tables give kilograms, customs value, CIF value and total value for the month
and the year to date, with `-` for no imports.

## FAS GATS and NASS Quick Stats: RECONSTRUCTED, not captured live

**None of the files below was downloaded from a USDA server.** They were rebuilt by hand from the
documented formats in `docs/research/usda.json`. All numbers are illustrative (a few values copied
from search snippets, e.g. NASS price $3.05/lb for 2025 and $2.41/lb for 2024). Never use these
files as market data, and replace them with recorded captures when the collectors are checked live.

| File | What it reconstructs | Documentation |
|---|---|---|
| `gats_release_dates.json` | FAS GATS `GET /api/gats/census/data/imports/dataReleaseDates`. Monthly 2026 releases are followed by the 2026-06-24 annual revision of 2023-2025. | https://apps.fas.usda.gov/opendatawebV2/assets/swagger/swagger.json |
| `gats_imports_{AR,VM,CH}_YYYYMM.json` | FAS GATS `GET /api/gats/censusImports/partnerCode/{p}/year/{y}/month/{m}`. Field names follow the recorded SDK fixture quoted in the research. Each file mixes honey lines (HS 0409) with non-honey lines. The China file has no honey line. | https://pypi.org/project/xippios-usda-gats/ |
| `gats_commodities.json` | FAS GATS `GET /api/gats/commodities`. The response shape (`hS10Code`, `commodityDescription`) is **unverified**. The honey HS-10 descriptions are also **unverified**: sources disagree on which suffix is which colour, so the collector reads the colour from the description text. | https://apps.fas.usda.gov/opendatawebV2/ |
| `nass_honey_national.json` | NASS Quick Stats `GET /api/api_GET/?commodity_desc=HONEY&source_desc=SURVEY&agg_level_desc=NATIONAL&format=JSON`. Keys follow the official API page sample. The honey `short_desc` strings for price, yield, stocks and colonies are **unverified**. | https://quickstats.nass.usda.gov/api |
