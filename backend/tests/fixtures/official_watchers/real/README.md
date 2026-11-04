# Official watchers: REAL captures (4 November 2026)

Captured by the first live run of `in_dgft_honey` and `ar_senasa_honey` (raw downloads archived by
`ctx.fetch`) and kept here so the tests check the parsers against the real layouts. Unlike the
reconstructed files one level up, **these are real official documents**; the values in them
(minimum export prices, dates, residue rows) are real and are what the tests expect.

| File | Source URL | Notes |
|---|---|---|
| `dgft_notifications.html` | https://www.dgft.gov.in/CP/?opt=notification | **Trimmed**: only the `<table id="metaTable">` with its header ("Sl.No., Number, Year, Description, Date, CRT DT, Attachment") and 15 of its 231 rows, verbatim: the five honey MEP rows (09/2026-27, 52/2025-26, 27/2025-26, 45/2024-25, 75/2023), bare numbers whose year is in the Year column ("36", "16", "64", "57"), the FTP-2023 form "08/2023", four corrigendum rows and the newest row. The page `<title>` is kept; scripts, menus and the other rows are removed. |
| `dgft_notification_75-2023.pdf` | https://content.dgft.gov.in/Website/dgftprod/32d42ad7-3efd-4c36-9ead-1cf5e0691bf2/Notification No. 75-2023-english.pdf | Unchanged. One scanned page (JPEG), no text layer: "Imposition of Minimum Export Price (MEP) on export of Honey", dated 14 March 2024, US $ 2000 per Metric Ton till 31st December 2024, "will come into immediate effect". |
| `dgft_notification_09-2026-27.pdf` | https://content.dgft.gov.in/Website/dgftprod/1b7a5f43-e2c8-4eed-a5ff-cbdeccbf8c84/Notification NO. 09.pdf | Unchanged. Scanned page: extension of the MEP of US Dollar 1400 FOB per Metric Ton till 31st December 2026, dated 10 April 2026, "with immediate effect". |
| `ocr/dgft_notification_<no>_<dpi>dpi.txt` | the five honey notification PDFs of the list above | Text produced by `paladex.services.ocr.ocr_pdf` (Tesseract 5.3.4, `--psm 6`, page rendered at 300 and 400 dpi), unedited, including its misreadings (superscript ordinals such as "31st" read as "31*", "318'", "3154"). The PDFs of 45/2024-25, 27/2025-26 and 52/2025-26 are not stored here (about 300 KB each). |
| `senasa_creha.html` | https://www.argentina.gob.ar/node/106753 (Plan CREHA Animal) | Unchanged. Twelve PDF links, among them "Lista EAR - Productos 09-2026", "Lista EAR - Especies 09-2026", "Lista EAR Impo N° 16 - Importados, vigilancia - Año 2026" and the 2020 lists. |
| `ear_09-26_producto_p1.pdf` | https://www.argentina.gob.ar/sites/default/files/ear_09-26_producto.pdf | The list has one page; re-written with pypdf (content unchanged). Header "Coordinación General de Vigilancia ... Plan CREHA Animal 08/10/2026", title "LISTA EAR AÑO 2026 N° 09 - Por Producto", six "Miel" rows. |
| `ear_09-20_producto_p1_text.txt` | https://www.argentina.gob.ar/sites/default/files/ear_09-20_producto.pdf | The first 14 lines of page 1 as extracted by pdfplumber (the 6-page PDF is 400 KB): the 2020 layout puts the date "01/10/2020" alone on the first line. |

Expected values were read on the documents themselves (the scans were looked at, not only OCR'd).
