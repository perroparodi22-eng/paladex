# Real captures for the European official-production collectors

Used by `collectors/production_europe.py` and `tests/test_production_europe.py`. Every file is a real
answer of the official source, captured 5-6 Nov 2026 (UTC) with Paladex's User-Agent
(`Paladex/0.1 (internal research tool)`), saved unmodified unless stated below. Files marked `.gz` are
the unmodified answer, gzip-compressed to keep the repository small. Variants (drift, revisions) are
built in the tests from these files and say what they change.

## Spain, MAPA "Estadística de Miel y Cera" (`es_mapa_honey`)

* `real_mapa_estadistica_miel_y_cera.html` — the statistic's page,
  `https://www.mapa.gob.es/es/estadistica/temas/estadisticas-agrarias/ganaderia/estadistica_de_miel_y_cera`
  (links to the workbooks 2013-2025).
* `real_mapa_mielycera-25-web.xlsx` —
  `https://www.mapa.gob.es/es/dam/jcr:16c4ff63-7e45-4bb7-a8e2-8772fe041560/mielycera-25-web.2026-08-24-13-38-18.xlsx`
  (Last-Modified: Mon, 24 Aug 2026 11:38:18 GMT; ESPAÑA honey 29,349.593722… t, 2,751,777 hives).
* `real_mapa_mielycera-24-web.xlsx` —
  `https://www.mapa.gob.es/dam/mapa/contenido/estadisticas/temas/estadisticas-agrarias/3.ganaderia/estadistica-de-lana--miel-y-huevos/2024/mielycera-24-web.xlsx`
  (Last-Modified: Wed, 02 Jul 2025 11:33:55 GMT; 33,180.63… t).
* `real_mapa_mielycera-15.xls` — the 2015 workbook (old .xls format, "Colmenas movilistas / fijistas"
  columns), `.../2015/mielycera-15.xls` (Last-Modified: Mon, 02 Jun 2025 16:27:25 GMT, as for every
  file 2013-2023: a website migration date, not a release date).
* `real_mapa_tls_chain_as_served.pem` — the five certificates www.mapa.gob.es sent (5 Nov 2026), in
  the order sent: leaf, "AC Componentes Informáticos", the self-signed "AC RAIZ FNMT-RCM SERVIDORES
  SEGUROS G2R", "AC SERVIDORES SEGUROS TIPO2 G2R", and the same G2R root cross-signed by "AC RAIZ
  FNMT-RCM" (the certificate embedded in the collector). Public certificates only.

## Hungary, KSH STADAT (`hu_ksh_honey`)

* `real_ksh_stadat_mez0034_en.html` — `https://www.ksh.hu/stadat_files/mez/en/mez0034.html`, table
  19.1.1.34 "Production of milk, eggs, wool, feather and honey" (Last updated: 14 October 2026; honey
  2025: 25,000 t). Two fetches a minute apart were byte-identical.

## Bulgaria, MZH Agrostatistics (`bg_mzh_honey`)

* `real_mzh_danni_page1.html.gz` — `https://www.mzh.government.bg/bg/statistika-i-analizi/izsledvane-zhivotnovdstvo/danni/`
  (no beekeeping bulletin on page 1 in November).
* `real_mzh_danni_page2.html.gz` — the same list, `?page=2` (bulletin No 466, 2025).
* `real_mzh_ra466_beeshoney2025_words_p1-3.json.gz` — NOT the PDF: the word layer of the first pages
  (the PDF has 4; pages 1-3) of
  `https://www.mzh.government.bg/media/filer_public/2026/02/27/ra466_beeshoney2025-26022026.pdf`
  (671,334 bytes, SHA-256 `41c7b8102627c0f6…`, Last-Modified 27 Feb 2026), as returned by
  `production_europe.pdf_page_words` (pdfplumber 0.11 `extract_words(x_tolerance=1.5)`: text, x0, x1,
  top, bottom, rounded to 0.001 pt), one list per page. The PDF (0.7 MB, 0.5 MB even without images)
  is too large to keep; the end-to-end tests serve a stand-in PDF and read these words as its layer.
* `real_mzh_ra449_beeshoney2024_words_p1-3.json.gz` — the same for the 2024 bulletin
  `https://www.mzh.government.bg/media/filer_public/2025/02/28/ra449_beeshoney2024-25022025.pdf`
  (613,385 bytes, SHA-256 `a4eb16fe90ea0328…`): its text layer prints the South-East average as
  "101." (a digit missing from the PDF itself), the case of a garbled derived cell.

## Greece, ELSTAT SPK33 (`gr_elstat_honey`)

* `real_elstat_spk33.html.gz` — `https://www.statistics.gr/en/statistics/-/publication/SPK33/-`
  ("Livestock Capital and Production"; its table links are those of reference year 2024).
* `real_elstat_spk33_2024_table7c.xlsx` — the "7c. Production of other primary livestock
  by-products" link of that page (documentID=595840, served as
  `A1005_SPK33_TB_AN_00_2024_07C_F_BI.xlsx`; Greece Total honey 25,595.792 t).
* `real_elstat_spk33_2024_table04.xlsx` — the "04. Poultry, rabbits (all ages) and beehives" link
  (documentID=595834, `A1005_SPK33_TB_AN_00_2024_04_F_BI.xlsx`; beehives on 31 Dec 2024: 3,641 local +
  2,157,445 European).
