# Real captures for the official-production collectors

Every file here is a real answer of an official source, saved unmodified unless stated below.
Tests that need a variant (a revision, schema drift, an inconsistent extract) build it from these
files in the test itself and say what they change.

## Used by `collectors/production_official.py` (captured 5 Nov 2026, 14:25–14:37 UTC)

Requests sent with Paladex's User-Agent (`Paladex/0.1 (internal research tool)`).

Brazil, IBGE SIDRA, Pesquisa da Pecuária Municipal, table 74 (`br_ibge_honey`):

* `real_sidra_t74_probe_last1.json` — the release check:
  `https://apisidra.ibge.gov.br/values/t/74/n1/all/v/106,215/p/last%201/c80/2687`
  (Brazil, 2025: 71,329,020 kg; 1,216,769 thousand reais).
* `real_sidra_t74_honey_2015-2026.json` — the full honey query (Brazil and the 27 states, both
  variables, 2015–2025; byte-identical to the answer for `p/2015-2025`):
  `https://apisidra.ibge.gov.br/values/t/74/n1/all/n3/all/v/106,215/p/2015-2026/c80/2687`
* `real_sidra_t74_wrong_category_99999.json` — what SIDRA answers for a category that does not
  exist (HTTP 200, an empty category name and `...`):
  `https://apisidra.ibge.gov.br/values/t/74/n1/all/v/106/p/last%201/c80/99999`
* `real_sidra_t74_wrong_variable_9999_http400.txt` — the HTTP 400 text answer for a variable that
  does not exist: `https://apisidra.ibge.gov.br/values/t/74/n1/all/v/9999/p/last%201/c80/2687`

Argentina, SAGyP RENAPA register on the MAGyP CKAN portal (`ar_magyp_hives`):

* `real_renapa_package_show.json` —
  `https://datos.magyp.gob.ar/api/3/action/package_show?id=registro-nacional-de-productores-apicolas`
* `real_renapa_provincia_2026-marzo.csv` (Latin-1) —
  `https://datos.magyp.gob.ar/dataset/15fbd380-fa31-436c-9283-457c23e30ecc/resource/fcf61106-a82c-4ce7-9997-a7f0f40345b5/download/renapa-productores-apiarios-colmenas-provincia-2026-marzo.csv`
* `real_renapa_departamento_2026-marzo.csv` (Latin-1) —
  `https://datos.magyp.gob.ar/dataset/15fbd380-fa31-436c-9283-457c23e30ecc/resource/68c49b26-6953-4656-8a32-dae497315e11/download/renapa-apiarios-colmenas-provincia-departamento-2026-marzo.csv`

Chile, Odepa "Cifras apícolas nacionales" with SAG SIPEC data (`cl_odepa_hives`):

* `real_odepa_rubros_apicultura.html` — `https://www.odepa.gob.cl/rubros/apicultura`
* `real_odepa_articulo_cifras_apicolas_nacionales_sipec_2025.html` —
  `https://www.odepa.gob.cl/publicaciones/articulos/cifras-apicolas-nacionales-sipec-2025`
  (article published 19 Oct 2026).
* `real_odepa_sipec_2025_pdf_text_pages_9-10.txt` — NOT the PDF itself: the text layer of pages 9
  and 10 (the two "por región" tables) of the article PDF
  `https://bibliotecadigital.odepa.gob.cl/bitstreams/1f285eb9-7faa-41a5-8c41-b9e2cb92e895/download`
  (1,565,420 bytes, SHA-256 `9e889b66…2bf8e4f`, Last-Modified 19 Oct 2026), extracted with
  pdfplumber 0.11.10 (`page.extract_text()`), pages separated by a form feed. The PDF is too large
  to keep here; the end-to-end tests serve a small stand-in and read this text as its text layer.

## Canada, Mexico, Turkey (`ca_statcan_honey`, `mx_siap_honey`, `tr_tuik_honey`)

First captured 4 Nov 2026 (UTC) for future collectors; the collectors were written on 5 Nov 2026,
when the requests they send were replayed: the answers marked "4 Nov" below were byte-identical on
5 Nov (checked with `cmp`). Requests sent with Paladex's User-Agent.

Canada, Statistics Canada Web Data Service, table 32-10-0353-01 "Production and value of honey":

* `real_statcan_getCubeMetadata.json` (4 Nov; identical 5 Nov 21:19 UTC) — `POST
  https://www150.statcan.gc.ca/t1/wds/rest/getCubeMetadata`, body `[{"productId":32100353}]`.
* `real_statcan_data_honey_2015-2025.json` (5 Nov 2026, 21:22 UTC) — `POST
  https://www150.statcan.gc.ca/t1/wds/rest/getDataFromCubePidCoordAndLatestNPeriods`, the body the
  collector sends: 40 coordinates `"{geo}.{estimate}.0.0.0.0.0.0.0.0"` (geo 1-10, estimate 1
  Beekeepers, 2 Colonies, 4 Production, 5 Value), each with `"latestN":11` (2015-2025).
* `real_statcan_data_latest5.json` (4 Nov) — the same service for estimates 2, 4 and 5 with
  `latestN` 5; `real_statcan_data_invalid_coordinate.json` (4 Nov) — its answer for coordinate
  `1.7.0.0.0.0.0.0.0.0` (no such estimate: `"status":"FAILED"`).

Mexico, SIAP (SADER) "Cierre de la producción pecuaria", xajax query service of
`https://nube.agricultura.gob.mx/cierre_pecuario/` (ISO-8859-1 XML):

* `real_siap_cierre_pecuario.html` (4 Nov) — the query page (xajax function list, form fields).
* `real_siap_xajax_llenaAnio.xml` (4 Nov; identical 5 Nov as a GET) — the year list:
  `https://nube.agricultura.gob.mx/cierre_pecuario/?xajax=llenaAnio&xajaxargs%5B%5D=aniopec`.
* `real_siap_xajax_reporte2_miel_YYYY.xml`, 2015-2025 (2024 and 2025: 4 Nov, identical 5 Nov; the
  others 5 Nov 2026, 21:22-21:23 UTC) — the honey report of each year, national level:
  `https://nube.agricultura.gob.mx/cierre_pecuario/?xajax=reporte2&xajaxargs%5B%5D=YYYY&xajaxargs%5B%5D=undefined&xajaxargs%5B%5D=0&xajaxargs%5B%5D=0&xajaxargs%5B%5D=0&xajaxargs%5B%5D=0&xajaxargs%5B%5D=1000101&xajaxargs%5B%5D=0&xajaxargs%5B%5D=0&xajaxargs%5B%5D=1910080&xajaxargs%5B%5D=Miel`
  (the page itself POSTs the same fields; the 2024 answer is byte-identical either way).
* `real_siap_xajax_llenaOtrosProd.xml` (4 Nov) — the product list (Miel 1910080, Cera 1910090);
  `real_siap_xajax_reporte2_cera_2025.xml` (4 Nov) — the wax report (not collected);
  `real_siap_datos_abiertos_pecuario.html` (4 Nov) — the open-data page (not used).

Turkey, TÜİK data portal (`https://veriportali.tuik.gov.tr`), captured 5 Nov 2026, 21:23 UTC; the
two JSON requests carry `X-Requested-With: XMLHttpRequest` (without it the API answers 404):

* `real_tuik_press_list_tr.json` — `GET https://veriportali.tuik.gov.tr/api/tr/press` (latest
  issue of each bulletin series; "Hayvansal Üretim İstatistikleri" = id 58015).
* `real_tuik_press_58015_tr.json` — `GET https://veriportali.tuik.gov.tr/api/tr/press/58015`
  (bulletin "Hayvansal Üretim İstatistikleri, 2025", released 10 Feb 2026, with its table links).
* `real_tuik_aricilik_2025.xls` (42,496 bytes, SHA-256 `7294ebf9dc1d1180…`) — the bulletin's
  "Arıcılık" statistical table, `GET https://veriportali.tuik.gov.tr/api/tr/data/downloads?t=i&pid=58015&p=KApxb1ssWoKy0ovL00kvLoyG3R9mj7ldfibsfuYaObxKlGQs8h%2Biw45fC%2FJ%2FTCF6`
  (sheet `46_t11`, years 1991-2025).
