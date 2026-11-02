# Paladex — Architecture

Paladex is the Parodi Group Global Honey Intelligence Platform: a local application that collects official and trade information about the world honey market, stores all of it with full history, and presents it in one place.

## 1. Requirements analysis (summary)

| Requirement | Consequence for the design |
|---|---|
| Runs locally on one PC, non-technical user | One process (FastAPI) serves both the API and the built interface. A double-click launcher opens the browser. No accounts, no cloud. |
| Works offline with saved data | Everything is stored in local SQLite. The map has no tile server (it uses country shapes bundled in the app), and fonts are bundled too. Collectors detect that the PC is offline and simply skip. |
| Automatic collection | In-process APScheduler. Each source has its own cadence, plus a catch-up run at start-up if the last run is older than 6 hours. A manual "Aggiorna dati" button runs everything. |
| Accuracy and trust | Every fact carries provenance. Price types, data statuses and reliability levels are controlled vocabularies. History is append-only with revisions. A data-quality engine reports stale, missing, outlier and conflicting values. |
| Never fabricate | No synthetic values anywhere except the opt-in demo data set, which is flagged at row level and badged in the UI. AI output is labelled and never stored as a source fact. |
| Italian default, English option | Per-page dictionaries. AI-generated translations of news and summaries are stored per language. |
| Premium, easy UI | A custom design system (forest / ivory / gold / charcoal, serif headings, mono numbers), always-visible navigation, large text, and an honest empty state on every view. |

## 2. Technical architecture

```
                ┌───────────────────────────── local PC ───────────────────────────────┐
                │                                                                       │
 Browser  ◄────►│  FastAPI (uvicorn, 127.0.0.1:8765)                                    │
 (React UI)     │   ├── /api/*  JSON (overview, prices, news, trade, countries, ...)    │
                │   ├── /       built React app (frontend/dist)                         │
                │   └── APScheduler ──► collectors ──► ctx.fetch() ──► internet         │
                │                            │             └─► data/raw/<source>/...    │
                │                            ▼                 (every file archived)    │
                │                   services.ingest (append-only, revisions)            │
                │                            ▼                                          │
                │                   SQLite  data/paladex.sqlite3 (WAL)                  │
                │                            ▲                                          │
                │   post-collection hooks: FX backfill · data quality · news AI · alerts│
                │                            │                                          │
                │                   optional LLM provider (Anthropic / OpenAI) ◄── key  │
                └───────────────────────────────────────────────────────────────────────┘
```

* **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2, SQLite (WAL mode), APScheduler 3, httpx, feedparser, pdfplumber and openpyxl.
* **Frontend:** React 18, Vite, TypeScript, Tailwind, TanStack Query, Recharts, and Leaflet with world-atlas TopoJSON (no tiles).
* **AI:** a small provider-agnostic client (`services/llm.py`, plain HTTPS, no SDK). Keys come from `.env`. The browser never sees them.
* **Why SQLite:** a single local file with zero administration and easy backup (copy `data/`). The schema is plain relational, so moving to PostgreSQL later is mechanical.

## 3. Data model

All observation tables share provenance and revision columns (`_ObservationMixin` in `models.py`):

| Column | Meaning |
|---|---|
| `source_id` → `sources` | who published it (name, publisher, kind, reliability, cadence, terms) |
| `raw_document_id` → `raw_documents` | the exact downloaded file (kept on disk) it was parsed from |
| `source_url` | link to the original document / API call (keys stripped) |
| `period_start`, `period_end`, `period_label`, `frequency` | what period the value refers to |
| `published_at` | publication date by the source |
| `collected_at`, `last_seen_at` | when we first stored and last re-confirmed it |
| `data_status` | live · published · provisional · estimate · forecast · ai_assessment · user_entered · demo |
| `reliability` | official · industry · trade_press · aggregator · user · ai · demo |
| `series_key`, `revision`, `is_current`, `supersedes_id`, `value_hash` | append-only revision chain |
| `is_demo` | demonstration rows (hidden unless switched on) |

Tables:

* `price_observations` has `price_type` (wholesale_bulk / producer / import_unit_value / export_unit_value / retail), origin and market country, variety (normalised plus raw text), colour grade, organic, terms/Incoterm, low/high/value as published (currency and unit), plus normalised `price_per_kg`, `usd_per_kg` and `eur_per_kg` with the FX date used.
* `trade_flows` holds HS 0409 flows with reporter, partner (`WLD` = world), flow, net weight in kg, value, currency, CIF/FOB basis, and unit value.
* `production_stats` holds production, colonies, yield and producer price, with the publisher flag (e.g. FAOSTAT A/E/I).
* `weather_observations` holds monthly temperature and precipitation and their anomalies per honey region (Milestone 5).
* `fx_rates` holds ECB reference rates. Conversions never guess: when a rate is missing, they return nothing.
* `reports` lists official publication releases (e.g. USDA National Honey Report, October 2026), with extracted narrative and AI summary fields.
* `news_articles` stores the canonical URL, publisher, language, snippet, image, countries, topics, relevance, AI title/summary in IT/EN, and the duplicate chain.
* `regulations` covers EU/US/IT measures with reference (CELEX, Federal Register number), type, status, dates, URL and affected countries.
* `supplier_quotes`, `alert_rules`, `alert_events` and `briefings` hold user and business data (Milestones 6–7).
* `data_quality_issues` tracks stale, missing, outlier, discrepancy, parse_warning and collection_failed issues, with auto-resolution.
* `sources`, `collection_runs`, `raw_documents`, `countries` and `app_settings` support the system itself.

**Revision rule:** when a source re-publishes a figure with a different value, the old row is kept (`is_current=False`) and the new one points to it. Queries read `is_current=True`. The archive view can show the full revision history.

## 4. Collection framework

`collectors/base.py` defines `Collector` (metadata + `collect(ctx)`) and `CollectContext`:

* `ctx.fetch()` waits at least 1.5 s between requests to the same host, retries on 429/5xx and connection errors, archives raw bytes under `data/raw/<source>/`, and reports `unchanged` when the bytes are identical to a previous download.
* `ctx.add_price / add_trade / add_production / add_report / add_regulation / add_news` are the only write paths. They enforce provenance and revisions and normalise units and FX.
* `ctx.warn()` records non-fatal parse problems, which give the run the status **partial**. `ctx.checkpoint()` commits batches.
* The runner records a `collection_runs` row per run with one of these statuses: success, partial, no_change, failed, offline, or skipped (e.g. missing key). It also updates the source's status fields and then runs the post-collection hooks (FX backfill, quality checks, AI enrichment, alerts).

## 5. Milestone plan

| # | Milestone | Status |
|---|---|---|
| 1 | Foundation: architecture, schema, collector framework, scheduler, CLI, design system, navigation, start-up scripts | **done** |
| 2 | Official data collection: USDA (National Honey Report, FAS GATS, NASS), EU (Eurostat Comext, DG AGRI), Italy (Osservatorio Nazionale Miele / price lists), UN Comtrade, FAOSTAT, ECB FX | **in this delivery** |
| 3 | Price intelligence: price database, explorer, history, origin and variety comparisons, discrepancies | **in this delivery** |
| 4 | Global news: feeds, dedup, relevance, AI summaries and translation, search and filters | **in this delivery** |
| 5 | Map, country profiles and trade (basic versions shipped early); harvest/weather (Open-Meteo / Copernicus); regulations UI | partially started |
| 6 | AI assistant (database-grounded, cited answers), daily AI briefing | planned |
| 7 | Supplier quotes, landed-cost calculator, alerts, historical archive views | schema ready, planned |
| 8 | Polish, source verification on the live machine, performance, installer | planned |

## 6. Security and privacy

* The server binds to `127.0.0.1` only, so it is not reachable from the network.
* API keys live in `.env` (git-ignored) and are only used server-side. They are stripped from stored URLs.
* Supplier quotes and business data never leave the PC. The only outbound data are requests to public sources and, if enabled, the article titles and snippets sent to the configured LLM provider for summaries. Supplier data is never sent.
