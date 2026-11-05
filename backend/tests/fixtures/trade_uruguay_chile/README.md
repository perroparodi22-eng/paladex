# Uruguay and Chile official honey exports: real captures of 5 November 2026

Every file here was downloaded from the official source on **2026-11-05** (from the development
sandbox, ~14:20-14:50 UTC). Where a file is trimmed or rebuilt, this README says exactly how; the
numbers are never edited. Tests that need a variant (a revision, a withdrawal, a broken layout)
derive it from these files in the test code, and say so.

## Uruguay: Uruguay XXI, Sistema de Información Estadística (SIE)

Query: `https://herramientas.uruguayxxi.gub.uy/sistema_de_estadistica/filtros.php?t=<t>&pr=&e=&a=2026&pa=<pa>&cat=Todos&ncm=0409`
(`t=mes`: months; `t=pais`: destinations; `pa`: ISO 3166-1 numeric code of the destination, empty
for all; `e`, the company, is always empty).

| File | What it is |
|---|---|
| `real_sie_mes_total_2026_page.html` | The whole answer page of `t=mes&pa=` (1,842,858 bytes) **minus** the three autocomplete lists in its scripts (`source: [...]` emptied: every exporting company and private person with an ID, and the product names) and the default company in `#empresa_auto` (blanked): 91,143 bytes, everything else byte for byte. Shows the parser works on the real page (menus, selectors, `<select id="anio">`). |
| `real_sie_mes_total_2026.html` | What the collector archives of `t=mes&pa=` (`sie_extract`): the `<h3>Sistema de Información Estadística</h3>` caption and the result `<table>`, byte for byte. |
| `real_sie_pais_total_2026.html` | Same for `t=pais&pa=`, plus the `<select id="pais">` country selector (code -> Spanish name). |
| `real_sie_mes_<code>_2026.html` | Same for `t=mes&pa=<code>`, one per destination with honey exports 2022-2026: 840 USA, 724 Spain, 276 Germany, 203 Czech Republic, 380 Italy, 124 Canada, 756 Switzerland, 528 Netherlands, 56 Belgium, 826 United Kingdom, 250 France, 376 Israel, 620 Portugal, 616 Poland, 784 United Arab Emirates, 682 Saudi Arabia, 208 Denmark. |

The 19 extracts are the raw documents the collector archived during the first live run.

What the real pages showed:

* Caption `Exportaciones por NCM: '0409', pais: Estados Unidos de América, Período: 2022 - 2026`; the
  year columns are `2022 ... 2025` and `2026 (ene - oct)` (the running year states its months); the
  November and December 2026 cells hold `0`, which is not data (those months had not happened).
* Amounts in US$ with dot thousands and decimal comma (`1.662.275,70`); **no weights anywhere** (not
  in the tables, not in the Excel/PDF downloads of the same queries).
* A `Total Detalle` row; it equals the sum of the rows shown. A destination table **leaves out a
  month that is zero in all five years** (Czech Republic: 9 month rows).
* With the category filter instead of the NCM filter (`cat=27`, "Miel") the caption reads
  "Importaciones con categoria uruguay XXI: 'Miel'" although the data are exports (a label bug); the
  collector uses the NCM filter, whose caption is right.
* Real figures: total 2025 = 27,928,748.53 USD; 2026 January-October = 33,100,409.13 USD; United
  States 2025 = 21,395,839.31 USD; the total of October 2026 was 113,064.65 USD on 5 November
  (a month that had just ended; stored as provisional).
* The sum of the 17 destinations equals the published total in every one of the 58 months.

## Chile: Servicio Nacional de Aduanas

| File | Source | What was done |
|---|---|---|
| `real_cl_dus_listing.html` | https://www.aduana.cl/base-de-datos-operaciones-de-salida/aduana/2024-11-12/153724.html | unmodified. Yearly links: 2026 `salida_da_09_2026.csv`, 2025 `salidas2025.rar`, 2024 `salidas_2024.csv`, 2023 `salidas_dic_2023.zip`...; the code tables link; the export operation types "200, 201, 202, 203, 204, 205, 206, 207, 210, 211, 212, 213 y 216". |
| `real_cl_stats_listing.html` | https://www.aduana.cl/exportacion-por-pais-y-codigo-arancelario/aduana/2018-12-14/101258.html | unmodified. Monthly workbooks per year, FOB ("monto") and weight ("peso"). |
| `real_cl_tablas_de_codigos_v2_0.xlsx` | `.../20241112153724/tablas_de_codigos_v2_0.xlsx` (Last-Modified Tue, 08 Sep 2026 13:31:01 GMT, ETag `"13204-65af8bee9813f"`) | unmodified. Sheet `Países` (Anexo 51-9: 563 Alemania, 515 Holanda, 902 ships' stores, 905 Zona franca Iquique, 997 Chile...), `Unidades de Medida` (6 = KN, KILO NETO). |
| `real_cl_salida_da_09_2026_trimmed.csv` | `.../salida_da_09_2026.csv` (19,784,114 bytes, 255,077 rows, January-September 2026; Last-Modified Wed, 21 Oct 2026 12:59:10 GMT, ETag `"12de1b2-65e5950277f67"`) | trimmed to the header, all 101 rows with `ITEM_SA` 0409*, the first 25 other rows, one other row per further month, and 3 rows where "0409" appears in another field (e.g. `13220409,22`); rows unmodified, CRLF kept. |
| `real_cl_salidas_2024_trimmed.csv` | `.../salidas_2024.csv` (26,528,081 bytes; Last-Modified Tue, 07 Jan 2025 14:27:56 GMT, ETag `"194c951-62b1e8d1b611b"`) | same rule: 137 honey rows. |
| `real_cl_salidas_dic_2023_trimmed.zip` | `.../salidas_dic_2023.zip` (5,261,037 bytes, member `Salidas_dic_2023.csv` of 24,626,727 bytes, every text field quoted; Last-Modified Tue, 12 Nov 2024 18:37:25 GMT, ETag `"5046ed-626bb8232ed65"`) | same rule: 86 honey rows; re-zipped (the container is new, the CSV lines are the real ones). |
| `real_cl_expo_pais_sa_monto_0112_2025_trimmed.xlsx`, `real_cl_expo_pais_sa_peso_0112_25_trimmed.xlsx` | `.../20181214101258/expo_pais_sa_monto_0112_2025.xlsx` (3,440,051 bytes, Last-Modified Wed, 14 Jan 2026 15:26:29 GMT, ETag `"347db3-6485abb720512"`) and `expo_pais_sa_peso_0112_25.xlsx` (3,226,245 bytes, Wed, 14 Jan 2026 15:26:43 GMT, `"313a85-6485abc47a0aa"`) | rebuilt with openpyxl from the real cells: the header rows, the first country (Albania, no honey), every country with a 0409 line with its honey lines (and one other line), the `Total` and `Fuente` rows. A number may differ in its last binary digit (1088068.3399999999 -> 1088068.34): identical at the cent. |
| `real_cl_expo_pais_sa_monto_0109_2026_trimmed.xlsx`, `real_cl_expo_pais_sa_peso_0109_2026_trimmed.xlsx` | the January-September 2026 workbooks (Last-Modified Wed, 07 Oct 2026) | same rule. |

What the real files showed:

* The DUS base columns: `PERIODO;MES;COD_ADUANA_TRAMITACION;COD_TIPO_OPERACION;...;COD_PAIS_DESTINO;
  COD_MODALIDAD_VENTA;MONEDA;CLAUSULA_VENTA;COD_TIPO_CARGA;ITEM_SA;FOB_US_DUSLEG;FOBUS_AJUSTADO_IVV;
  PESO_BRUTO_KG;CANTIDAD_MERCANCIA;COD_UNIDAD_MEDIDA`, decimal comma, no exporter field. Every
  honey row is in unit 6 (KN, net kilos): the statistical unit of heading 04.09 is KN-06 in the
  Arancel Aduanero 2022, where 0409.0010 is "Orgánica" and 0409.0090 "Las demás".
* The statistics workbooks state "Monto FOB en dólares" and **"Peso en Kilos Brutos"** (gross).
* The DUS base reproduces the statistics workbooks exactly (adjusted FOB and gross kg by
  destination, month and line), checked on every honey cell of January-September 2026.
* `salidas2025.rar` starts with `Rar!\x1a\x07\x01\x00` (RAR 5); Python cannot open it without an
  external tool, so 2025 is read from the statistics workbooks (no net weight).
* Real figures: Germany January 2026, 04090010 82,921.20 USD / 21,456 kg net / 22,572 kg gross and
  04090090 715,266.47 USD / 259,166 kg net / 272,794 kg gross; all destinations 2024 = 14,680,630.19
  USD and 5,790,457.5 kg net (UN Comtrade republishes 14,677,655.25 USD and 5,790,439.9 kg).

## Routes not captured (and why)

* Uruguay DNA open data (`ftp://ftp.aduanas.gub.uy/DUA Diarios XML/`): FTP only; the host does not
  resolve for plain FTP from the sandbox and has no HTTPS service (connection reset). Not used.
* Uruguay BCU (source of INE yearbook table 7.1.14, monthly totals with net kg but no destinations):
  www.bcu.gub.uy sends an incomplete TLS chain ("unable to verify the first certificate").
* Chile ODEPA: same TLS problem; it republishes Aduana's figures.
