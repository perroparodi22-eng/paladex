# Data sources: what is really available

This file summarises `docs/research/*.json`, which holds the full research per source: endpoints, parameters, field names, sample responses and evidence links, each with a confidence level (`verified_from_docs`, `from_search_snippets` or `from_memory_unverified`). The research was done in November 2026. Every collector has a startup probe or a schema check that fails loudly if a source changes format.

> **Key message:** there is no free, real-time, global bulk-honey price feed. Honey market information is published monthly or annually, with lags of weeks to over a year. The platform therefore always shows the **publication date and period** of each figure and never presents an old figure as current.

## 1. Summary matrix

| Source | Access | Key / account | What we get | Frequency · lag | Licence / limits |
|---|---|---|---|---|---|
| **USDA AMS National Honey Report** (FVMHONEY) | PDF (latest URL overwritten monthly), ESMIS JSON API for the archive | none | **Bulk prices paid to importers by origin and colour** (USD/lb, duty paid, ex-dock); prices paid to US and Canadian beekeepers by state, floral source and colour; US imports by origin (CBP ACE kg/value) | monthly, at month end · import tables lag 1 month | US public domain. Layout changed in Jan 2025, so the parser is versioned |
| USDA FAS GATS (US Census) | REST JSON | free api.data.gov key | Monthly US honey imports by origin and HS-10 line (kg, customs value, CIF) giving a **customs unit value USD/kg** | monthly · ~5–6 weeks | public; 1,000 req/h |
| US Census Bureau International Trade API (`us_census_trade`) | REST JSON (array of arrays) | optional free key | Monthly US honey imports by origin (HS 0409, every country plus the published world total): customs value and kg (same basis as GATS), general imports, CIF value, dutiable value and **calculated duty**, HS-10 lines. Gives a **customs unit value USD/kg**. **The underlying data are the same as GATS**: every row says so (`extra.same_underlying_data_as`), and the two are never added together | monthly · ~5 weeks; annual revision in June; the API gives no release date | public domain |
| **Brazil MDIC/SECEX Comex Stat** (`br_comexstat`) | REST JSON (POST queries) | none | Monthly Brazilian honey exports (NCM 04090000) by destination and state of production (FOB USD, net kg). Gives an **export unit value USD/kg by destination** | monthly · ~1 week (a cheap daily release check; trailing 3 months re-pulled) | Brazilian open data (Lei 12.527/2011), cite MDIC/SECEX |
| USDA NASS Quick Stats | REST JSON | free key | US production, colonies, yield, **price received by beekeepers** | annual (mid-March) | public; the app must show "This product uses the NASS API but is not endorsed or certified by NASS." |
| USDA MyMarketNews API (slug 2901) | REST JSON | free key | same report; structured sections unverified, history only from late 2025 | monthly | public. Optional; the PDF route is primary |
| **Eurostat Comext DS-045409** | REST JSON-stat | none | EU27 and member-state imports and exports of CN 04090000 by partner (EUR, 100 kg) giving an **EU import unit value EUR/kg by origin** | monthly (mid-month release) · ~6–7 weeks; recent months revised | CC BY 4.0 |
| EC Agri-food portal, TAXUD weekly | REST JSON | none | Weekly extra-EU honey imports by member state × origin (kg, EUR): the **freshest EU import price signal** | weekly · 1–3 weeks (provisional) | EC reuse policy; startup probe of the sectors. Weeks are Monday–Sunday weeks inside the calendar year (week 1 starts on 1 January, a week 53 exists), not ISO weeks: verified live 2026-11-04 |
| DG AGRI honey market overview | HTML + PDF | none | Market presentation decks (production, member-state prices, trade) | ~2 per year | EC reuse with attribution |
| RASFF Window | undocumented JSON | none | EU food-safety notifications on honey (origin, hazard) | daily | public information; endpoint may change |
| **Osservatorio Nazionale Miele** (informamiele.it) | HTML posts, PDF reports | public summaries: none · **full price tables: MieleInforma login** | Monthly bulletin (market commentary; since Sept 2023 only a summary is public, rarely with price ranges), annual report (wholesale price table by variety: min/max/average €/kg, 300 kg drums, VAT incl.; import prices by origin only as a chart), September preliminary report | monthly · ~3 weeks | © ONM, no open licence. Full tables are behind a free personal login. **Recommendation: ask ONM for a data-sharing agreement** |
| **CCIAA Cuneo** honey list | HTML / CSV / PDF | none | **Italian wholesale prices in 300 kg drums** by variety (min–max €/kg, VAT incl.) | monthly | public price list (indicative) |
| ISMEA Mercati | HTML tables | none | Italian **producer prices** ("prezzi medi alla produzione") by variety (€/kg; the pages do not state VAT) | weekly/monthly, seasonal gaps | terms unclear: attribute, internal use |
| CCIAA Arezzo-Siena | weekly PDF | none | local honey quotations (millefiori, selected) | weekly | indicative |
| CCIAA Bologna, Torino, Milano | PDF | — | **no honey lines found**, so not integrated | — | — |
| **UN Comtrade** | REST JSON | optional free key (500 calls/day) | World HS 0409 trade by reporter × partner (USD, kg) giving **export/import unit values** | rolling; annual data lags 6–18 months; monthly for some reporters | UN terms: internal analysis allowed, raw re-dissemination restricted |
| **FAOSTAT** | bulk CSV ZIP (no account); REST API needs a free token since 2026 | none (bulk) / account (API) | Production (t), beehives, **producer prices (USD/t)**, annual trade, trade matrix | annual · ~12–24 months | CC BY 4.0 with attribution |
| ECB reference rates | XML | none | Daily FX for EUR/USD/CNY/… conversions | daily | free reuse |
| GDELT DOC 2.0 | REST JSON | none | Multilingual news search (65 languages, rolling 3 months) | ~15 min | **commercial use allowed** with citation |
| Google News RSS | RSS | none | Search feeds per language | minutes | **personal, non-commercial use only**, so these feeds are **off by default**; the owner can switch them on |
| Trade press RSS (Bee Culture, American Bee Journal, Apimondia, Food Safety News…) | RSS (WordPress) | none | Headlines, excerpts, links | daily–weekly | copyrighted: we store headline, link and short excerpt only |
| US Federal Register | REST JSON | none | Anti-dumping notices (China, Argentina, Brazil, India, Vietnam honey), honey-related presidential tariff documents, FDA/ITC notices. Kept only when honey is in the title/abstract, an omnibus AD notice lists a honey case number, or a presidential tariff text names honey / HTS 0409 | every business day | public domain |
| EUR-Lex / CELLAR SPARQL | SPARQL JSON | none | EU honey legislation (Honey Directive as amended by 2024/1438, third-country lists 2021/405…) | daily | EU reuse with acknowledgement |
| **EU import duties** via UK Online Trade Tariff, XI service (`eu_tariff_xi`) | REST JSON:API | none | EU TARIC measures for heading 0409 (lines 0409000010 Mānuka, 0409000090 other): third-country duty (17.30 %), preferences, additional duties, **tariff quotas with balances** from the quota search (Ukraine, Mexico, Mercosur) per origin | daily | UK government mirror of EU TARIC (OGL v3). The legal reference is the EU act, linked on every row |
| **US tariff schedule** USITC HTS (`us_hts`) | REST JSON | none | US general/special duty for 0409.00.00; Chapter 99 lines kept "da verificare" unless their country scope is unambiguous | on each HTS revision | public domain |
| Brazil MAPA notices (`br_mapa_honey`) | HTML page watcher | none | Honey notices from Brazil's agriculture ministry (e.g. EU listing status) | daily | official; page structure may change, so it fails loudly when it does |
| Argentina SENASA / Boletín Oficial (`ar_senasa_honey`) | HTML page watcher | none | Residue lists, export certification and drum rules; official-gazette items on honey | daily | official; page watcher |
| India DGFT (`in_dgft_honey`) | HTML + PDF notifications (scanned) | none; **Tesseract OCR** (optional system program) to read the scanned PDFs | **Minimum export price for honey** (USD/t FOB) and its validity | daily | official; page watcher. The MEP notifications are scanned pages: values are read by OCR at two resolutions and kept only when both readings agree; without Tesseract the notices are stored without their terms |
| **NASA POWER** weather (`nasa_power_weather`) | REST JSON, monthly + daily point APIs (community AG) | none | Monthly temperature (T2M) and rainfall (PRECTOTCORR) at 130 points in 64 honey regions (`reference/regions.py`), with anomalies against **1991-2020 normals computed from the same MERRA-2 series**; months the monthly API has not published yet are computed from complete daily near-real-time data (GEOS-IT) and stored as **provisional** until MERRA-2 replaces them | monthly API (MERRA-2) 1-2 months behind (Sept 2026 on 4 Nov 2026); daily data 2-3 days behind (POWER FAQ) | NASA open data, commercial use allowed; cite the POWER project with service, version and date accessed (shown on /raccolti); POWER asks to be told when its data are passed on. No published rate limit: HTTP 429, and repeated requests for one location may be blocked. Live 4 Nov 2026: first full run 260 requests, 8 min. One implausible cell value seen (Sibari, Feb 2026: 3,100 mm), kept as published and marked "to verify". **Open-Meteo is not used: its free tier is non-commercial only** |

## Source priority

Government and intergovernmental sources are the primary sources: USDA, US Census, USITC, the Federal Register, the European Commission and Eurostat, EUR-Lex, RASFF, the UN, FAO, the ECB, Brazil's MDIC and MAPA, Argentina's SENASA and Boletín Oficial, and India's DGFT. Industry bodies come next: the Osservatorio Nazionale Miele, ISMEA and the Chambers of Commerce. Trade press and news aggregators come last. Every row carries its reliability level. The Sources page lists official sources first in each category, and the interface never mixes reliability levels without showing which is which. More official sources were researched and are queued: Argentina INDEC/ARCA customs files, Uruguay customs, Mexico INEGI/SIAP, Japan e-Stat, India TradeStat, Turkey TÜİK and China GACC (manual import). See `research/official_*.json`.

## 2. Which sources have APIs, which need documents

* **Official APIs (JSON):** Eurostat Comext, EC TAXUD weekly, UN Comtrade, USDA FAS GATS, US Census International Trade API, Brazil Comex Stat, USDA NASS, ESMIS (USDA archive), FAOSTAT (token), Federal Register, CELLAR SPARQL, ECB, GDELT.
* **RSS / Atom:** trade press, Google News (opt-in), and WordPress sites (Informamiele, if its feed is enabled).
* **Document extraction (PDF / HTML):** USDA National Honey Report (PDF tables), ONM bulletins and annual report, CCIAA Cuneo (HTML/CSV), ISMEA (HTML), CCIAA Siena (PDF), DG AGRI market overview (PDF).

## 3. What is realistically available

* **Bulk wholesale prices by origin:**
  * the USDA National Honey Report gives US importer prices for Argentina, Brazil, Uruguay, India, Vietnam, Mexico and Canada, by colour, monthly;
  * Italian price lists give Italian honey in drums, monthly;
  * the ONM annual report gives import prices by origin into Italy, annually.
* **Customs unit values (a proxy, never a quote):**
  * EU by origin: monthly (Comext) and weekly provisional (TAXUD);
  * US by origin: monthly (GATS, and the same Census data directly from the Census API, kept as a separate source and never added to GATS);
  * Brazil by destination: monthly, about one week after the month (Comex Stat export unit values);
  * world: annual (Comtrade, FAOSTAT).
* **Production:** FAOSTAT (annual, ~1–2 years old), NASS (US, annual), ONM (Italy, annual plus a preliminary report).
* **Not available from any free source:** real-time spot prices, supplier offers (entered manually in the Supplier quotes tool, Milestone 7), and Chinese domestic prices.

## 4. Costs

Everything integrated is **free**. Optional costs:

* an LLM provider for summaries, translation and the assistant (pay per use; a few euros a month at the default caps);
* Open-Meteo commercial plan, only if chosen for weather;
* Comtrade Premium, only if raw data were to be redistributed, which is not planned.

## 5. Verification status (live run, 4 November 2026)

Every collector was run against the real sources on 4 Nov 2026. Parsers were corrected on the real responses, and real captured files replaced the reconstructed test fixtures (see each `tests/fixtures/<module>/README.md`).

**Rows stored in a fresh database from real sources:**

| Source | Rows |
|---|---|
| ECB | 221,789 |
| EU TAXUD weekly | 23,155 |
| FAOSTAT | 20,900 |
| Eurostat Comext | 15,182 |
| UN Comtrade (keyless quota reached) | 5,116 |
| USDA National Honey Report | 2,719 |
| Brazil Comex Stat | 1,411 |
| CCIAA Cuneo | 447 |
| RASFF | 48 |
| US Federal Register | 33 |
| US HTS | 34 |
| EUR-Lex | 21 |
| EU duties (UK XI mirror) | 16 |
| ISMEA | 14 |
| Osservatorio Nazionale Miele | 7 |
| Brazil MAPA | 5 |
| India DGFT | 5 |
| CCIAA Siena | 2 |
| Argentina SENASA | 2 |
| Trade press (ABJ, Apimondia, Bee Culture) | 28 |

**Waiting for free keys:** USDA FAS GATS, USDA NASS and the US Census trade API.

**Limits seen from the development network:** GDELT throttles shared IPs heavily; the Argentine Boletín Oficial and the European Parliament refused connections; the UN Comtrade keyless quota runs out after about 5,000 rows a day. All of these are expected to behave better from the owner's own PC and connection.

**Gaps in the sources themselves:**
* The USDA ESMIS archive has no National Honey Report issues between Oct 2025 and Aug 2026; only the latest issue is reachable.
* ISMEA's honey series has not been updated since June 2026.
* The Osservatorio's full monthly tables require a MieleInforma login.

**OCR:** India's minimum-export-price notices are scanned images. Their terms are read only if the free Tesseract OCR program is installed, and are kept only when two readings agree.

