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

## Kept for possible future collectors (captured 4 Nov 2026, UTC; not used by the current module)

* `real_statcan_*.json` — Statistics Canada Web Data Service, table 32-10-0353-01
  "Production and value of honey" (getCubeMetadata, data for the latest 5 periods, and the
  answer to an invalid coordinate).
* `real_siap_*` — Mexico, Servicio de Información Agroalimentaria y Pesquera (SIAP, gob.mx/agricultura/dgsiap):
  the livestock open-data and year-end ("cierre") pages and the answers of its query service
  for honey (miel, 2024 and 2025) and wax (cera, 2025).
