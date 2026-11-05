# Tariff fixtures: `real_xi_*` are live captures; the others are RECONSTRUCTED

## Real XI captures (2026-11-04)

Downloaded from the UK Online Trade Tariff XI API on 2026-11-04:

| File | URL (`https://www.trade-tariff.service.gov.uk/xi/api/v2/...`) | Notes |
|---|---|---|
| `real_xi_heading_0409.json` | `headings/0409` | unmodified. `data.type` is `heading`, no `import_measures`; `relationships.commodities` lists the two declarable lines 0409000010 "Mānuka honey" and 0409000090 "Other" (valid from 2024-05-01). `commodities/0409000000` answers the same heading document, which is what the first live run tripped on. |
| `real_xi_commodity_0409000090.json`, `real_xi_commodity_0409000010.json` | `commodities/0409000090`, `commodities/0409000010` | **trimmed** from 476 KB each: the `included` objects the collector does not read were removed (measure components, condition permutations, preference codes, the trade summary, conditions of non-duty measures) and `export_measures`/`import_trade_summary` dropped from `data.relationships`. Every measure (60 per line) and its type, duty expression, legal acts, footnotes and geographical areas are kept as published. |
| `real_xi_quota_search_0409000000.json` | `quotas/search?goods_nomenclature_item_id=0409000000` | unmodified: 5 quota definitions (090881 Mercosur, 091002 Algeria, 091218 Tunisia, 091833 Mexico, 096701 Ukraine), pagination `per_page` 5 (the `page` parameter pages). |
| `real_xi_quota_search_091833.json` | `quotas/search?order_number=091833` | unmodified (search by order number, the fallback path). |
| `real_xi_measure_4209614.json`, `real_xi_measure_4254929.json`, `real_xi_measure_4244733.json` | `measures/{sid}` | unmodified: the quota measures of Ukraine, Mexico and Mercosur (in-quota duty, legal act, area with its members, current definition). |

What the real tariff shows (all values read from these files, nothing assumed): third-country duty
(type 103, ERGA OMNES) 17.30 % since 2005-01-01 (R2204/99, R2658/87) on both lines; tariff
preferences (142) at 0.00 % for e.g. Serbia (XS), Türkiye, Viet Nam, Chile, Moldova, Canada; EU-New
Zealand at 4.30 % on "Other" (staged, 2026) and 0.00 % on Mānuka; additional duties (695) of 50 % on
Russia and Belarus and an ERGA OMNES row whose duty depends on conditions; the EUR 3 low-value
consignment duty (107) from 2026-11-01; tariff quotas only through the quota search: Ukraine
096701 (35,000 t, exhausted, 0.00 %), Mexico 091833 (30,000 t, 8.60 %), Mercosur 090881 (quarterly
1,722.96 t, 0.00 %). The commodity documents carry no order numbers at all.

## Reconstructed fixtures

The development sandbox could not reach `www.trade-tariff.service.gov.uk` or `hts.usitc.gov` when
these were written (egress was blocked), and the research in `docs/research/official_tariffs_trade_policy.json` and
`docs/research/regulation.json` is marked `from_memory_unverified`. **None of the files below was
downloaded from the real source.** They were rebuilt from the documented formats so that the
parsers, the drift checks, the append-only revisions and the end-to-end runs can be tested offline.
The XI ones are kept for edge cases the real tariff does not show today (UK-origin measures, a group
whose members must be fetched, quotas found only by order number, an unmapped duty type); the test
serves `xi_commodity_0409000000.json` at the heading URL as a declarable heading.

**The measures, rates, quota figures, order numbers, legal acts and Chapter 99 headings are
illustrative test data, not the real tariff.** In particular:

* Quota order numbers `099990`, `099991`, `099992`, the legal-act codes `D9901/25` ... `D9910/95`
  (CELEX `3....D99..` / `3....R99..`) and geographical group `9901` are invented, outside the ranges
  real TARIC identifiers use. The only real identifiers are ERGA OMNES (`1011`), the ISO/TARIC
  country codes (with `XS` for Serbia) and Council Regulation (EEC) No 2658/87 (`R2658/87`,
  CELEX `31987R2658`, the Combined Nomenclature).
* The 17.30 % third-country duty and the 35,000 t Ukraine quota volume follow the research
  (both confirmed by the real captures above); the balance, the Mexico quota and the preference
  rates are invented. Group `2020` with India as a member mimics a GSP group; its id is unverified.
* The HTS rates of 0409.00.00 (`1.9¢/kg`, special `Free (A+,AU,...,S,SG)`, column 2 `6.6¢/kg`)
  are as recalled in the research. The footnote `See 9903.88.15.` is invented to exercise the
  footnote path: whether honey carries a Section 301 footnote is **not known**. Every Chapter 99
  heading text ends with "(illustrative)".

| File | Collector | What is reconstructed, and from what |
|---|---|---|
| `xi_commodity_0409000000.json` | `eu_tariff_xi` | JSON:API document of `GET /xi/api/v2/commodities/0409000000`: `data` (type `commodity`, `goods_nomenclature_item_id`, `relationships.import_measures`) and `included` objects of type `measure` (attributes `origin` eu/uk, `import`, `effective_start_date`/`effective_end_date`; relationships `measure_type`, `geographical_area`, `excluded_countries`, `duty_expression`, `legal_acts`, `order_number`, `footnotes`), `duty_expression` (`base`, `formatted_base` with HTML spans), `measure_type` (`description`, `measure_type_series_id`), `geographical_area` (`description`, optional `children_geographical_areas`), `legal_act` (`regulation_code`, `regulation_url`, `published_date`, `officialjournal_number`), `order_number` (`number`, `definition`) and `definition`. It contains: the EU 103 ERGA OMNES canary; a UK duty and UK VAT measure (origin `uk`, must be ignored); an EU veterinary control (series B, not a duty); a preferential quota for Ukraine with an inline definition (fallback when the quota search fails); preferences for Serbia (`XS`), Vietnam, Chile, Moldova and Norway (Norway is not a Parodi origin); a group preference (`2020`, children included); a group quota (`9901`, children **not** included, so the collector must call the geographical-area endpoint); a Mexico quota; and an unmapped duty type (105) that must be kept for review. |
| `xi_quota_099990.json`, `xi_quota_099991.json`, `xi_quota_099992.json` | `eu_tariff_xi` | `GET /xi/api/v2/quotas/search?order_number=...`: `data` list of `definition` objects (`quota_order_number_id`, `initial_volume`, `balance` as strings in kg, `measurement_unit`, `validity_start_date`, `validity_end_date`, `status`, `critical`, `last_allocation_date`) and `meta.pagination`. `099992` answers with no definition (no period open): the row is stored with empty quota figures and a note. |
| `xi_geo_9901.json` | `eu_tariff_xi` | `GET /xi/api/v2/geographical_areas/9901` with `relationships.children_geographical_areas`. |
| `hts_0409.json` | `us_hts` | `GET /reststop/exportList?from=0409&to=0410&format=JSON&styles=false`: a JSON array of rows with `htsno`, `indent`, `description`, `superior`, `units`, `general`, `special`, `other`, `footnotes` (`{columns, value, type}`), `quotaQuantity`, `additionalDuties`. Statistical suffixes have empty rate columns. |
| `hts_9903_01.json` | `us_hts` | Same format, range `9903.01`-`9903.04` (country-wide surcharge headings): an all-countries heading, a Brazil heading, a Japan heading (not a Parodi origin), an exemption heading without additional duty and an "all countries except" heading. |
| `hts_9903_88.json` | `us_hts` | Same format, range `9903.88`-`9903.89` (Section 301, China): one heading referenced by the 0409 footnote, one that is not. |

Documentation and evidence used:

* UK Online Trade Tariff API reference (v2, JSON:API): https://api.trade-tariff.service.gov.uk/reference.html
  and the XI service pages https://www.trade-tariff.service.gov.uk/xi/commodities/0409000000 ,
  https://www.trade-tariff.service.gov.uk/xi/quota_search
* JSON:API specification (resource objects, `relationships`, `included`): https://jsonapi.org/format/
* EU TARIC consultation (link target): https://ec.europa.eu/taxation_customs/dds2/taric/taric_consultation.jsp?Lang=en
* USITC HTS and its REST interface: https://hts.usitc.gov/ and https://www.usitc.gov/harmonized_tariff_information
