# Real captures for the planned official-production collectors

Captured on 4 Nov 2026 (UTC) from the official sources, unmodified, for the planned
`production_official` collectors (not written yet; see docs/ARCHITECTURE.md):

* `real_statcan_*.json` — Statistics Canada Web Data Service, table 32-10-0353-01
  "Production and value of honey" (getCubeMetadata, data for the latest 5 periods, and the
  answer to an invalid coordinate).
* `real_siap_*` — Mexico, Servicio de Información Agroalimentaria y Pesquera (SIAP, gob.mx/agricultura/dgsiap):
  the livestock open-data and year-end ("cierre") pages and the answers of its query service
  for honey (miel, 2024 and 2025) and wax (cera, 2025).
