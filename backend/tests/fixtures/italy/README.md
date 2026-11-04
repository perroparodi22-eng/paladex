# Italian honey sources — test fixtures

## Real captures (`real_*`)

**The `real_*` files are REAL captures of the official sources, downloaded on 4 November 2026**
(during the first live run of the collectors, or right after it with `curl`, ≥ 1.5 s between
requests). The numbers in them are the published values and the tests assert them.

Some captures are trimmed so the fixtures stay small. Trimming only removes content; it
never edits what is left:

* **HTML**: `<script>`, `<style>`, `<noscript>`, `<svg>`, `<iframe>`, `<link>`, comments and
  `<meta>` tags other than `og:`/`article:` are dropped. Where marked "chrome removed", the
  site `<header>`, `<footer>` and `<nav>` are dropped too. In the Cuneo chapter page the
  "Data della rilevazione" menu keeps its newest 26 and oldest 2 of 343 entries.
* **RSS**: whole `<item>` blocks are removed; the kept items are byte-identical.
* **PDF**: selected pages are kept with `pypdf`, and images and embedded font programs are
  dropped. Text, glyph widths and positions are unchanged; the tests check that the parsers
  read the same rows as from the full original.

| File | Real URL | Trimming | Real values asserted |
|---|---|---|---|
| `real_cuneo_category_miele.html` | https://www.cuneoprezzi.it/ingrosso/alimentari/?category=11 | HTML + list cut | chapter "Miele"; newest list `listCategory=20353` "rilevazione mensile del 30 settembre 2026" |
| `real_cuneo_list_20353.html` | https://www.cuneoprezzi.it/dataentry/site/ingrosso/lists/download/html?listCategory=20353 | none | 30 Sept 2026: Acacia (fusto da 3 q.li) 7,00–8,00, Millefiori 4,50–5,50, Castagno 4,50–5,50, Tarassaco/Tiglio/Alta Montagna/Rododendro (secchio da 25 kg), €/kg, IVA 10 %, "IVA compresa"; Melata di Bosco, Ciliegio, Melata d'abete "n.q."; Polline (not honey) 22,00–25,00 |
| `real_cuneo_list_20353.csv` | https://www.cuneoprezzi.it/dataentry/site/ingrosso/lists/download/csv?category=20353 | none | same list, `;`-separated |
| `real_cuneo_list_18861.html` | https://www.cuneoprezzi.it/dataentry/site/ingrosso/lists/download/html?listCategory=18861 | none | 30 Sept 2025: "Acacia (quantitativi >10 q.li)" 7,50–8,50 |
| `real_cuneo_medie_2025.pdf` | https://www.cuneoprezzi.it/dataentry/site/ingrosso/medie/download/pdf?category=11&mYear=2025 | font programs dropped only | "Miele - medie 2025": Acacia Magg.–Dic. 8,25/8,00, Anno 8,09; Millefiori Dic. 5,55, Anno 5,83 |
| `real_cuneo_medie_2025_rewritten_norules.pdf` | same document | **derived**: the same page re-written by `pypdf` (images and fonts dropped, content streams recompressed); pdfplumber no longer finds its ruled table, so it exercises the word-position fallback on the real layout | same values as above |
| `real_ismea_11024_settimanali_varieta.html` | https://www.ismeamercati.it/flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/11024 | HTML, chrome removed | week 2026-6-4: Acacia 8,00, Agrumi 5,70, Castagno 4,90, Eucalipto 5,25, Millefiori 4,20, Sulla 4,50, Tiglio 4,90 €/Kg; no VAT statement |
| `real_ismea_11026_mensili_varieta.html` | https://www.ismeamercati.it/flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/11026 | HTML, chrome removed | month 2026-6, same values; heading "… alla produzione - f.co azienda" |
| `real_siena_prezzi.html` | https://www.as.camcom.it/pubblicazioni-e-listini-prezzi/prezzi | HTML, chrome removed | the 2019 page: its own PDF links stop at n. 06 del 12.02.2020; yearly archive links 2018–2026 |
| `real_siena_anno_2026.html` | https://www.as.camcom.it/listini-settimanali-provincia-siena-anno-2026 | HTML, chrome removed | 44 lists, newest "Listino prezzi n. 44 del 04.11.2026" |
| `real_siena_listino_n44_2026_p1_p5.pdf` | https://www.as.camcom.it/sites/default/files/contenuto_redazione/pagina_base/allegati/listino_prezzi_n_44_del_04_11_2026.pdf | pages 1 and 5 of 8 | "VARIE - IVA esclusa": Miele (millefiori) al Kg. 6,00–7,00; Miele (selezionati) al Kg. 6,50–10,00 |
| `real_onm_feed.xml` | https://www.informamiele.it/feed/ | 3 of 10 items kept | Settembre 2026 (20 Oct 2026) and Agosto 2026 (17 Sept 2026) bulletins; "Report di Prime Valutazioni della stagione 2026" |
| `real_onm_post_settembre_2026.html` | https://www.informamiele.it/settembre-2026-rilevazione-mensile/ | HTML, chrome removed | market text without price ranges |
| `real_onm_post_agosto_2026.html` | https://www.informamiele.it/agosto-2026-rilevazione-mensile/ | HTML, chrome removed | "offerte d'acquisto (attorno ai 4,00 €/kg per il millefiori)": a single value, never stored |
| `real_onm_report_archive.html` | https://www.informamiele.it/report-annuali-produzione-e-mercato/ | HTML, chrome removed | newest annual report: `…/2026/10/Report-annuale-Monitoraggio-produzione-e-mercato-del-miele-stagione-2025.pdf` |
| `real_onm_report_annuale_2025_p42_p46.pdf` | https://www.informamiele.it/wp-content/uploads/2026/10/Report-annuale-Monitoraggio-produzione-e-mercato-del-miele-stagione-2025.pdf | pages 42 and 46 of 52 | p. 42 wholesale table (fusti da 300 kg, Euro/kg Iva inclusa, franco produttore): Acacia 7,5/8,5/8,0 (+2,6 %), Agrumi 5,6/6,0/5,7, Castagno 4,8/5,0/4,9, Millefiori 4,0/4,5/4,2 (−6,7 %); p. 46 swarm/queen price table (not honey, must be ignored) |

## Reconstructed fixtures (still used)

These were written before the sources could be reached, from `docs/research/italy.json`. They
are **not** captures and their numbers are **test data**, never market prices. They are kept
only for rules the real captures above do not exercise.

| File | Kept for | Notes |
|---|---|---|
| `onm_feed.xml`, `onm_wp_posts.json`, `onm_listing_comunicati.html` | discovery fallbacks (RSS feed → WP REST API → HTML listing) | the real feed works; the REST and listing paths are unverified |
| `onm_post_luglio_2026.html`, `onm_post_agosto_2026.html` | price extraction from bulletin prose | the ranges millefiori 5,00–6,50, monoflora 6,00–7,50 and acacia 8,00–10,00 €/kg are documented; the other sentences are illustrative test sentences. Since September 2023 the real posts carry only a summary (see `real_onm_post_*`) |
| `siena_listino_drift.pdf` | schema-drift refusal | a list with renamed price columns, generated by `make_pdf_fixtures.py` (needs `reportlab`, not a Paladex dependency) |

Removed on 4 Nov 2026 because real captures replace them: `cuneo_index_alimentari.html`,
`cuneo_list_15948.*`, `cuneo_list_15702.html`, `cuneo_medie_2025.pdf`,
`cuneo_medie_2024_unruled.pdf`, `ismea_11024_settimanali.html`, `ismea_11025_mensili.html`,
`siena_prezzi.html`, `siena_listino_n14_2026.pdf`, `onm_report_archive.html`,
`onm_report_annuale_2024.pdf`.
