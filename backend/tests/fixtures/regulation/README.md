# Regulation fixtures: RECONSTRUCTED, not captured live

The development sandbox could not reach `www.federalregister.gov` or `publications.europa.eu`
(egress was blocked), and the source research in `docs/research/regulation.json` is marked
`from_memory_unverified`. **None of these files was downloaded from the real source.** They were
rebuilt from the documented formats so that the parsers, the drift checks and the end-to-end
runs can be tested offline.

**All documents are illustrative test data, not real records.** The FR document numbers
(`20xx-90xxx`) and the CELEX numbers of invented acts (`…99xx`, e.g. `32026R9901`) were chosen
outside the ranges real documents use, and invented EU titles end with "(illustrative test …)".
The only real identifiers are the reference acts the collector watches and uses as a self-check:
Directive (EU) 2024/1438 (CELEX `32024L1438`, 14 May 2024, amends the Honey Directive
`32001L0110`) and Directive 2014/63/EU (`32014L0063`). Their titles are reproduced as published.
The corrigendum suffix `32021R0405R(05)` is invented.

On the first live run, compare these fixtures with the real responses archived under
`data/raw/us_federal_register/` and `data/raw/eurlex_honey/`, and update them where they differ.
The things to check first are the ones marked unverified below.

| File | Collector | What is reconstructed, and from what |
|---|---|---|
| `fr_raw_honey_p1.json`, `fr_raw_honey_p2.json` | `us_federal_register`, search `"raw honey"` | `documents.json` envelope (`count`, `description`, `total_pages`, `next_page_url`, `results`) and result fields requested with `fields[]` (`document_number`, `title`, `type`, `abstract`, `publication_date`, `effective_on`, `html_url`, `pdf_url`, `agencies`, `action`, `citation`). Agency objects use `raw_name`, `name`, `id`, `url`, `json_url`, `parent_id`, `slug`. `effective_on`, `action` and `citation` are **unverified** field names. Agency ids are guesses. Page 1 has a `next_page_url` to page 2 and one malformed row (non-ISO `publication_date`). |
| `fr_china_honey.json` | same, search `"honey from the people's republic of china"` | Same format. Repeats the omnibus initiation notice from the raw-honey search, to test de-duplication across searches. |
| `fr_itc_honey.json` | same, USITC + `honey` | One honey notice plus a "honey bee" notice that the topic filter must drop. |
| `fr_fda_honey.json` | same, FDA + `honey` | A notice, a final rule with `effective_on`, a "honey bees" animal-drug rule (topic noise), and a rule from another agency (AMS) that the in-band agency check must drop. |
| `fr_pres_tariff_honey.json`, `fr_pres_tariff_origins.json` | same, `PRESDOCU` + `tariff honey` / `tariff` | Presidential documents (type label `Presidential Document`, `abstract` null). The origins search must keep the Brazil and "reciprocal" documents and drop the lumber one. |
| `fr_agencies.json` | `us_federal_register` start-up probe | `/api/v1/agencies` as a JSON array of agency objects with `slug` (other keys from memory). |
| `cellar_related.json` | `eurlex_honey`, acts related to 32001L0110 / 32024L1438 / 32021R0405 | W3C SPARQL 1.1 JSON results (`head.vars`, `results.bindings[{var: {type, value, datatype / xml:lang}}]`), the standard format (one binding uses Virtuoso's older `typed-literal` term type). The CDM vocabulary in the query (`resource_legal_id_celex`, `work_date_document`, `expression_title`, `resource_legal_amends_resource_legal`, `resource_legal_in-force`, ...) is **unverified**. Includes the canary row (32024L1438 amends 32001L0110), a duplicate row with a shorter title variant, a row without an English title, a corrigendum and a malformed CELEX. |
| `cellar_title.json` | `eurlex_honey`, English title contains "honey" | Same format. Includes the canary, a COM proposal (`52026PC…`), an international-body decision (`22025D…`), a "honeybees"-only title that must be dropped, and a parliamentary question (sector 9) that must be ignored. |

Documentation and evidence used:

* Federal Register API v1 documentation: https://www.federalregister.gov/developers/documentation/api/v1
  and https://www.federalregister.gov/reader-aids/developer-resources
* Type codes `RULE`, `PRORULE`, `NOTICE`, `PRESDOCU` and the `count` / `total_pages` / `next_page_url` /
  `results` envelope, as used by public clients, e.g. the R package `federalregister`:
  https://cran.r-project.org/package=federalregister
* CELLAR SPARQL endpoint and knowledge graph: https://publications.europa.eu/webapi/rdf/sparql and
  https://op.europa.eu/en/web/cellar/cellar-data/metadata/knowledge-graph
* CDM property names in public example queries (R package `eurlex`):
  https://cran.r-project.org/web/packages/eurlex/vignettes/sparql-queries.html
* SPARQL 1.1 Query Results JSON Format: https://www.w3.org/TR/sparql11-results-json/
* EUR-Lex reuse: https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html
