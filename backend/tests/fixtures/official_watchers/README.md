# Origin-country notice watcher fixtures: RECONSTRUCTED, not captured live

These files test `paladex/collectors/official_watchers.py` (`br_mapa_honey`, `ar_senasa_honey`,
`in_dgft_honey`). They were **reconstructed from documentation**. None was downloaded from
`gov.br`, `in.gov.br`, `argentina.gob.ar`, `boletinoficial.gob.ar` or `dgft.gov.in`, because the
development sandbox could not reach those hosts.

**Every page, notice, number, price and date is illustrative and invented. Never read these files
as real notices or market data.** Each HTML file says so in a comment on its second line. Each
PDF says so on its first lines ("ILLUSTRATIVE TEST FIXTURE - NOT A REAL DOCUMENT").

The invented values are deliberately different from the real events listed in the research notes
(for example, the Indian minimum export price, the notification that set it, the EU regulation that
de-listed Brazil, and the SAGyP quota resolution). The tests check that every value stored comes
from these pages, and that none of the real events appears in the module.

On the first live run, compare these fixtures with the real pages archived under
`data/raw/<source>/`, and update them (and the parsers) where they differ.

## What each file reconstructs, and from what

| File | Collector / feed | What it exercises |
|---|---|---|
| `mapa_noticias_p1.html` | `br_mapa_honey`, MAPA news listing (page 1) | Plone listing on gov.br: `ul.noticias` items with `h2.titulo` link, `p.subtitulo-noticia` section, `span.descricao` with a leading `span.data` date. Includes a honey item, an EU third-country-list item that does not name honey (body check), a fish EU-list item (body has no honey), a "melhoria" decoy, a "lua de mel" decoy, a PNCRC residue item, a "Mais lidas" link outside `#content-core`, and a `b_start:int=30` next-page link. |
| `mapa_noticias_p2.html` | same (page 2) | The first item of page 1 again (listing shifted: stored once), an undated honey item whose link ends in `/view` (date read on the article page), and a non-honey item. No next page. |
| `mapa_noticia_lista_ue.html` | MAPA article | EU-listing article whose body names "mel": `article:published_time` meta, `documentDescription`, `#parent-fieldname-text`. |
| `mapa_noticia_lista_ue_pescado.html` | MAPA article | EU-listing article about fish only: opened, no honey, remembered as checked. |
| `mapa_noticia_apicultura.html` | MAPA article | Article without meta date: date from `span.documentPublished` ("Publicado em 29/10/2026 10h05"). |
| `mapa_noticias_drift.html` | drift probe | Listing rendered client-side (no article links): `SchemaDrift`. |
| `dou_busca_mel.html`, `dou_busca_apicola.html`, `dou_busca_apicultura.html` | `br_mapa_honey`, DOU search | Results JSON in `<script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">` with `jsonArray` rows (`urlTitle`, `title`, `pubDate`, `content` with highlight spans, `artType`, `hierarchyStr`, `pubName`, `editionNumber`, `numberPage`), as read by the open-source DOU client Ro-DOU. One act appears in two queries (stored once), one matches only "Melo" (not honey), one is from ANVISA (not MAPA). `apicultura` is a valid empty answer. |
| `dou_busca_drift.html` | drift probe | Results script renamed: `SchemaDrift`. |
| `senasa_noticias.html` | `ar_senasa_honey`, SENASA news | argentina.gob.ar (Poncho theme) card listing: `a.panel` with `<time datetime>`, `h3` title, `p.text-muted` summary. Includes honey, drum-varnish (BPA) and residue items, a non-honey item and a "luna de miel" decoy. |
| `senasa_creha.html` | Plan CREHA page (`/node/106753`) | Four PDF links, two of them "Lista EAR" (`ear_NN-YY_producto.pdf`, the file-name shape cited in the research), each with its listed date. |
| `ear_91-26_producto.pdf`, `ear_90-26_producto.pdf` | Lista EAR PDFs | Table "Producto, Analito, Valor hallado, LMR, Fecha de muestreo, Identificación" (shape from the research `sample_response`). N° 91 has two honey rows; N° 90 has none. |
| `bo_primera.html` | Boletín Oficial, latest first section | `div.linea-aviso` blocks linking `/detalleAviso/primera/<id>/<yyyymmdd>`, with organism, norm and GDE number, under `h5` rubro headings. Two agriculture notices (opened), one health notice and one tax notice (not opened). |
| `bo_primera_20261102.html` | Boletín Oficial, dated edition (catch-up) | A missed edition read through the unverified `/seccion/primera/<yyyymmdd>` URL. |
| `bo_aviso_999090.html`, `bo_aviso_999101.html`, `bo_aviso_999102.html` | Boletín Oficial notice pages | `#cuerpoDetalleAviso` body. 999090 and 999101 name honey (residue limits; quota procedure with NCM 0409.00.00); 999102 does not (rejected). |
| `bo_primera_drift.html` | drift probe | Notices loaded client-side (no `detalleAviso` link): `SchemaDrift`. |
| `dgft_notifications.html` | `in_dgft_honey`, DGFT notifications list | Table with header "Notification Number, Year, Description, Date, Attachment" and PDF links on `content.dgft.gov.in`. Three honey rows (MEP extension, MEP revision, export-policy change) and three decoys: almonds, onion MEP, live honey bees. |
| `dgft_notif_91_2026-27.pdf` | DGFT notification PDF | Gazette layout. One MEP (US$ 1,111 per MT FOB), one validity date written twice ("up to 30th June, 2027", "till 30.06.2027"), "with immediate effect". |
| `dgft_notif_93_2025-26.pdf` | DGFT notification PDF | MEP revised "from US$ 1,234 per MT to US$ 1,111 per MT", "valid up to 31.03.2026", "with effect from 01.12.2025". |
| `dgft_notif_94_2026-27.pdf` | DGFT notification PDF | Export-policy amendment without any price. |
| `dgft_notifications_drift.html` | drift probe | List loaded client-side; only a layout table without notification rows: `SchemaDrift`. |
| `build_fixtures.py` | all PDFs | Rebuilds the five PDFs with `fpdf2` (`cd backend && python tests/fixtures/official_watchers/build_fixtures.py`). The HTML files are written by hand. |

## Documentation used

* `docs/research/official_south_america.json`: entries "MAPA: EU listing status, PNCRC ...",
  "SENASA: residue alerts (Plan CREHA, Lista EAR) ..." and "Boletín Oficial: honey trade rules ..."
  (URLs, keywords, Lista EAR table shape). Confidence: `from_search_snippets`.
* `docs/research/official_asia_turkey.json`: entry "DGFT Notifications – Minimum Export Price (MEP)
  on Natural Honey" (list URL marked REMEMBERED, ITC-HS 04090000, gazette wording). Confidence:
  `from_search_snippets`.
* Ro-DOU (github.com/gestaogovbr/Ro-dou): DOU search parameters and the results `<script>` JSON.
* The public markup conventions of Plone on gov.br (`documentPublished`, `documentDescription`,
  `#parent-fieldname-text`, `b_start:int` paging) and of the Poncho theme on argentina.gob.ar.

The real layouts are **unverified** (see "Verification status" in the module docstring). The
parsers look for structure rather than exact CSS, and fail loudly (`SchemaDrift`) when it is not
there; the `*_drift.html` files exercise that.
