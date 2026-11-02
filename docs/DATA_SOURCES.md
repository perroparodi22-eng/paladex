# Data sources: what is really available

This file summarises `docs/research/*.json`, which holds the full research per source: endpoints, parameters, field names, sample responses and evidence links, each with a confidence level (`verified_from_docs`, `from_search_snippets` or `from_memory_unverified`). The research was done in November 2026. Every collector has a startup probe or a schema check that fails loudly if a source changes format.

> **Key message:** there is no free, real-time, global bulk-honey price feed. Honey market information is published monthly or annually, with lags of weeks to over a year. The platform therefore always shows the **publication date and period** of each figure and never presents an old figure as current.

## 1. Summary matrix

| Source | Access | Key / account | What we get | Frequency · lag | Licence / limits |
|---|---|---|---|---|---|
| **USDA AMS National Honey Report** (FVMHONEY) | PDF (latest URL overwritten monthly), ESMIS JSON API for the archive | none | **Bulk prices paid to importers by origin and colour** (USD/lb, duty paid, ex-dock); prices paid to US and Canadian beekeepers by state, floral source and colour; US imports by origin (CBP ACE kg/value) | monthly, at month end · import tables lag 1 month | US public domain. Layout changed in Jan 2025, so the parser is versioned |
| USDA FAS GATS (US Census) | REST JSON | free api.data.gov key | Monthly US honey imports by origin and HS-10 line (kg, customs value, CIF) giving a **customs unit value USD/kg** | monthly · ~5–6 weeks | public; 1,000 req/h |
| USDA NASS Quick Stats | REST JSON | free key | US production, colonies, yield, **price received by beekeepers** | annual (mid-March) | public; the app must show "This product uses the NASS API but is not endorsed or certified by NASS." |
| USDA MyMarketNews API (slug 2901) | REST JSON | free key | same report; structured sections unverified, history only from late 2025 | monthly | public. Optional; the PDF route is primary |
| **Eurostat Comext DS-045409** | REST JSON-stat | none | EU27 and member-state imports and exports of CN 04090000 by partner (EUR, 100 kg) giving an **EU import unit value EUR/kg by origin** | monthly (mid-month release) · ~6–7 weeks; recent months revised | CC BY 4.0 |
| EC Agri-food portal, TAXUD weekly | REST JSON | none | Weekly extra-EU honey imports by member state × origin (kg, EUR): the **freshest EU import price signal** | weekly · 1–3 weeks (provisional) | EC reuse policy; field names from third-party code, so it has a startup probe |
| DG AGRI honey market overview | HTML + PDF | none | Market presentation decks (production, member-state prices, trade) | ~2 per year | EC reuse with attribution |
| RASFF Window | undocumented JSON | none | EU food-safety notifications on honey (origin, hazard) | daily | public information; endpoint may change |
| **Osservatorio Nazionale Miele** (informamiele.it) | HTML posts, PDF reports | public summaries: none · **full price tables: MieleInforma login** | Monthly bulletin (market commentary with some price ranges), March annual report (prices by variety and **import prices by origin**), September preliminary report | monthly · ~3 weeks | © ONM, no open licence. Full tables are behind a free personal login. **Recommendation: ask ONM for a data-sharing agreement** |
| **CCIAA Cuneo** honey list | HTML / CSV / PDF | none | **Italian wholesale prices in 300 kg drums** by variety (min–max €/kg, VAT incl.) | monthly | public price list (indicative) |
| ISMEA Mercati | HTML tables | none | Italian **producer/origin prices** by variety (€/kg, VAT incl.) | weekly/monthly, seasonal gaps | terms unclear: attribute, internal use |
| CCIAA Arezzo-Siena | weekly PDF | none | local honey quotations (millefiori, selected) | weekly | indicative |
| CCIAA Bologna, Torino, Milano | PDF | — | **no honey lines found**, so not integrated | — | — |
| **UN Comtrade** | REST JSON | optional free key (500 calls/day) | World HS 0409 trade by reporter × partner (USD, kg) giving **export/import unit values** | rolling; annual data lags 6–18 months; monthly for some reporters | UN terms: internal analysis allowed, raw re-dissemination restricted |
| **FAOSTAT** | bulk CSV ZIP (no account); REST API needs a free token since 2026 | none (bulk) / account (API) | Production (t), beehives, **producer prices (USD/t)**, annual trade, trade matrix | annual · ~12–24 months | CC BY 4.0 with attribution |
| ECB reference rates | XML | none | Daily FX for EUR/USD/CNY/… conversions | daily | free reuse |
| GDELT DOC 2.0 | REST JSON | none | Multilingual news search (65 languages, rolling 3 months) | ~15 min | **commercial use allowed** with citation |
| Google News RSS | RSS | none | Search feeds per language | minutes | **personal, non-commercial use only**, so these feeds are **off by default**; the owner can switch them on |
| Trade press RSS (Bee Culture, American Bee Journal, Apimondia, Food Safety News…) | RSS (WordPress) | none | Headlines, excerpts, links | daily–weekly | copyrighted: we store headline, link and short excerpt only |
| US Federal Register | REST JSON | none | Anti-dumping notices (China, Argentina, Brazil, India, Vietnam honey), tariffs, FDA/ITC notices | every business day | public domain |
| EUR-Lex / CELLAR SPARQL | SPARQL JSON | none | EU honey legislation (Honey Directive as amended by 2024/1438, third-country lists 2021/405…) | daily | EU reuse with acknowledgement |
| Weather (Milestone 5) | Open-Meteo / Copernicus CDS / NOAA PSL | see note | monthly temperature/precipitation anomalies per honey region | daily–monthly | **Open-Meteo free tier is non-commercial only.** Use Copernicus CDS (free account, commercial use allowed) or NOAA gridded data (public domain) |

## 2. Which sources have APIs, which need documents

* **Official APIs (JSON):** Eurostat Comext, EC TAXUD weekly, UN Comtrade, USDA FAS GATS, USDA NASS, ESMIS (USDA archive), FAOSTAT (token), Federal Register, CELLAR SPARQL, ECB, GDELT.
* **RSS / Atom:** trade press, Google News (opt-in), and WordPress sites (Informamiele, if its feed is enabled).
* **Document extraction (PDF / HTML):** USDA National Honey Report (PDF tables), ONM bulletins and annual report, CCIAA Cuneo (HTML/CSV), ISMEA (HTML), CCIAA Siena (PDF), DG AGRI market overview (PDF).

## 3. What is realistically available

* **Bulk wholesale prices by origin:**
  * the USDA National Honey Report gives US importer prices for Argentina, Brazil, Uruguay, India, Vietnam, Mexico and Canada, by colour, monthly;
  * Italian price lists give Italian honey in drums, monthly;
  * the ONM annual report gives import prices by origin into Italy, annually.
* **Customs unit values (a proxy, never a quote):**
  * EU by origin: monthly (Comext) and weekly provisional (TAXUD);
  * US by origin: monthly (GATS);
  * world: annual (Comtrade, FAOSTAT).
* **Production:** FAOSTAT (annual, ~1–2 years old), NASS (US, annual), ONM (Italy, annual plus a preliminary report).
* **Not available from any free source:** real-time spot prices, supplier offers (entered manually in the Supplier quotes tool, Milestone 7), and Chinese domestic prices.

## 4. Costs

Everything integrated is **free**. Optional costs:

* an LLM provider for summaries, translation and the assistant (pay per use; a few euros a month at the default caps);
* Open-Meteo commercial plan, only if chosen for weather;
* Comtrade Premium, only if raw data were to be redistributed, which is not planned.

## 5. Verification status

The development sandbox could not reach any of these hosts. Collectors were built from official documentation, official client code and indexed examples, and tested against reconstructed fixtures (each fixture folder has a README saying so). **The first run on the target PC is the real verification.** The *Fonti e qualità dati* page shows each source's status, errors and data counts after the first collection.
