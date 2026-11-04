# Reference-data fixtures: REAL captures

| File | Captured | What |
|---|---|---|
| `faostat_areas.csv` | 4 November 2026, from the FAOSTAT bulk extracts read by the `faostat` collector (`Production_Crops_Livestock_E_All_Data`, `Prices_E_All_Data`, `Trade_DetailedTradeMatrix` / honey item 1182), https://bulks-faostat.fao.org/production/ | The distinct `Area Code`, `Area Code (M49)` and `Area` triples of the honey rows (reporter and partner columns of the trade file included), verbatim. Used to check every FAO code and M49 code in `paladex/reference/countries.py`. |
| `real_rasff_origins.json` | 4 November 2026, RASFF Window search (`POST https://webgate.ec.europa.eu/rasff-window/backend/public/notification/search/consolidated/en/`, product category "honey and royal jelly") | Eight notifications of the real first page, unchanged: the six whose origin was missing from the country table (Nepal NP, Syria SY, Singapore SG) and two controls with origins already in the table (China; Germany + Türkiye). `totalPages` / `totalElements` are those of the full search. |
