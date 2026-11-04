# Tariff fixtures: RECONSTRUCTED, not captured live

The development sandbox could not reach `www.trade-tariff.service.gov.uk` or `hts.usitc.gov`
(egress was blocked), and the research in `docs/research/official_tariffs_trade_policy.json` and
`docs/research/regulation.json` is marked `from_memory_unverified`. **None of these files was
downloaded from the real source.** They were rebuilt from the documented formats so that the
parsers, the drift checks, the append-only revisions and the end-to-end runs can be tested offline.

**The measures, rates, quota figures, order numbers, legal acts and Chapter 99 headings are
illustrative test data, not the real tariff.** In particular:

* Quota order numbers `099990`, `099991`, `099992`, the legal-act codes `D9901/25` ... `D9910/95`
  (CELEX `3....D99..` / `3....R99..`) and geographical group `9901` are invented, outside the ranges
  real TARIC identifiers use. The only real identifiers are ERGA OMNES (`1011`), the ISO/TARIC
  country codes (with `XS` for Serbia) and Council Regulation (EEC) No 2658/87 (`R2658/87`,
  CELEX `31987R2658`, the Combined Nomenclature).
* The 17.30 % third-country duty and the 35,000 t Ukraine quota volume follow the research
  (confidence "high" and "medium"); the balance, the Mexico quota and the preference rates are
  invented. Group `2020` with India as a member mimics a GSP group; its id is unverified.
* The HTS rates of 0409.00.00 (`1.9¢/kg`, special `Free (A+,AU,...,S,SG)`, column 2 `6.6¢/kg`)
  are as recalled in the research. The footnote `See 9903.88.15.` is invented to exercise the
  footnote path: whether honey carries a Section 301 footnote is **not known**. Every Chapter 99
  heading text ends with "(illustrative)".

On the first live run, compare these fixtures with the real responses archived under
`data/raw/eu_tariff_xi/` and `data/raw/us_hts/`, and update them where they differ.

| File | Collector | What is reconstructed, and from what |
|---|---|---|
| `xi_commodity_0409000000.json` | `eu_tariff_xi` | JSON:API document of `GET /xi/api/v2/commodities/0409000000`: `data` (type `commodity`, `goods_nomenclature_item_id`, `relationships.import_measures`) and `included` objects of type `measure` (attributes `origin` eu/uk, `import`, `effective_start_date`/`effective_end_date`; relationships `measure_type`, `geographical_area`, `excluded_countries`, `duty_expression`, `legal_acts`, `order_number`, `footnotes`), `duty_expression` (`base`, `formatted_base` with HTML spans), `measure_type` (`description`, `measure_type_series_id`), `geographical_area` (`description`, optional `children_geographical_areas`), `legal_act` (`regulation_code`, `regulation_url`, `published_date`, `officialjournal_number`), `order_number` (`number`, `definition`) and `definition`. It contains: the EU 103 ERGA OMNES canary; a UK duty and UK VAT measure (origin `uk`, must be ignored); an EU veterinary control (series B, not a duty); a preferential quota for Ukraine with an inline definition (fallback when the quota search fails); preferences for Serbia (`XS`), Vietnam, Chile, Moldova and Norway (Norway is not a Parodi origin); a group preference (`2020`, children included); a group quota (`9901`, children **not** included, so the collector must call the geographical-area endpoint); a Mexico quota; and an unmapped duty type (105) that must be kept for review. |
| `xi_quota_099990.json`, `xi_quota_099991.json`, `xi_quota_099992.json` | `eu_tariff_xi` | `GET /xi/api/v2/quotas/search?order_number=...&years[]=2026`: `data` list of `definition` objects (`quota_order_number_id`, `initial_volume`, `balance` as strings in kg, `measurement_unit`, `validity_start_date`, `validity_end_date`, `status`, `critical`, `last_allocation_date`) and `meta.pagination`. `099992` answers with no definition (no period open): the row is stored with empty quota figures and a note. |
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
