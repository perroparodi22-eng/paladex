# Paladex — Architecture

Paladex is the Parodi Group Global Honey Intelligence Platform: a local application that collects official and trade information about the world honey market, stores all of it with full history, and presents it in one place.

## 1. Requirements analysis (summary)

| Requirement | Consequence for the design |
|---|---|
| Runs locally on one PC, non-technical user | One process (FastAPI) serves both the API and the built interface. A double-click launcher installs, updates itself and opens the browser. No accounts. The only cloud part is optional: a read-only copy of the market pages for the phone, built from public data (`docs/PHONE_ACCESS.md`). |
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
* `tariff_measures` holds import duties on honey by origin (EU TARIC through the UK XI service, US HTS): measure type, duty as published, ad valorem rate, tariff quotas and their balances, with the same revision columns.
* `company_records` (`models_companies.py`) holds honey exporters and importers by company, only from official sources that publish them (Uruguay XXI SIE, HMRC, India EIC, Canada CID): name and location as published, role, product code, period and what the figure is (`exact_value`, `value_band`, `exact_volume`, `rank` or `none` for a names-only list), with the same provenance and revision columns.
* `supplier_quotes`, `alert_rules`, `alert_events` and `briefings` hold user and business data (Milestones 6–7).
* `data_quality_issues` tracks stale, missing, outlier, discrepancy, parse_warning and collection_failed issues, with auto-resolution.
* `sources`, `collection_runs`, `raw_documents`, `countries` and `app_settings` support the system itself.

**Revision rule:** when a source re-publishes a figure with a different value, the old row is kept (`is_current=False`) and the new one points to it. Queries read `is_current=True`. The archive view can show the full revision history.

**Corrections by a person** (`models_corrections.py`, `services/corrections.py`, `corrections_sync.py`, `corrections_ai.py`, `api/corrections.py`). `correction_events` is an append-only log of events with a global id (uuid4): `value_correction`, `revert`, `flag_wrong`, `note`, each with author (`PALADEX_USER_NAME` or the name chosen on screen), the installation's random `device_id`, the target (table, source key, `series_key`, period, unit/currency as stored, the official row's `value_hash` and values at the time), the value as typed and as stored, reason and the AI's reading of the sentence; plus local state (`status`, `applied_row_id`, `sync_status`, `synced_at`, `sync_error`). A value correction (price_observations, trade_flows, production_stats; more tables need only a model, a value field and a normaliser) is written through `ingest.add_revision` as a NEW revision of the same series: reliability `user`, status `user_entered`, the value converted to the series' own unit and currency (exact mass factors; a currency at the ECB rate of the period, `fx.conversion_factor`), derived fields recomputed as the collectors do (`ingest.per_kg`, `fx.normalise_price` / `normalise_trade`, trade unit value), `extra.correction` = {event_id, author, created_at, reason, official value, official row id and hash}, plain-words `notes`. A revert is another new revision holding a copy of the official row. Demo rows are never corrected. **Ingest policy** (`ingest.record`): when the current row of a series is a correction, a re-read with the official values the correction replaced is "unchanged" (the official revision's `last_seen_at` moves, the correction stays current); any other value is the source publishing anew: it becomes current over the correction, the event turns `superseded_by_source` (or `confirmed_by_source` when it equals the corrected value) and an alert event (rule-less, `correction:<id>:source`) tells the owner. A flag opens a `user_flag` data-quality issue; notes are kept for the country pages. Every API answer that shows a corrected figure carries a `correction` object (author, created_at, official_value, reason, event_id, unit/currency): price points and series, latest, compare, observations, archive and revisions, trade provenance (from two extra aggregate columns, `corr_n`/`corr_id`, with `rows` and `part_of_total` when a total includes a corrected row), country profile, production tables and overview tiles; it is read from the row itself, so memo.py's cache (keyed on the database state) stays right and the phone copy needs no events table. **Synchronisation** goes through git, with no new service or secret: one JSON file per event, `events/<YYYY>/<event-id>.json`, on the branch `paladex-corrections` of the repository's own `origin`, written with plumbing only (`hash-object`, `update-index` on a temporary `GIT_INDEX_FILE`, `write-tree`, `commit-tree` with the fetched tip as parent or an orphan commit the first time, `push origin <sha>:refs/heads/paladex-corrections`, never forced; on a rejected push the new tip is fetched, applied and the commit rebuilt) so the working tree, index and checked-out branch are never touched; non-interactive (`GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, ssh batch mode, time limits). The server pulls shortly after start-up and every `PALADEX_CORRECTIONS_SYNC_MINUTES` (default 15) and pushes after each new event; `PALADEX_CORRECTIONS_SYNC=false` opts out; without git, a checkout, network or push rights events stay `pending_sync` with the error. Received events are applied oldest first, idempotently by event id; a correction whose official value differs from this computer's is not applied (`conflict`, with a notice; retried at each sync, or `superseded_by_source` when this computer has seen the source move on). The phone copy's workflow runs `python -m paladex corrections-apply --from-git` (read-only) after the collection; `scripts/mirror/prepare_db.py` keeps the corrected rows (series tables) and drops `correction_events`. The starter snapshot never carries corrections (`strip_from_snapshot`). The assistant keeps a corrected figure with the market data (status `corrected`, labelled "Corretto da <name> il <date>", its block stating the source's official value), never with the supplier offers (status `user`, private, "Offerta A/B/C" for the model). Alert rules never fire on a corrected row or on a figure that includes one (price and trade rules), since an event names the source; an undo restores the official row with its original `collected_at`, so it is not new data either. **AI interpretation** (`POST /api/corrections/interpret`): the configured provider (services/llm.py) only turns the sentence into a structured request whose numbers must appear in the sentence; the backend resolves it against the database (up to five real candidates with their current value, provenance and proposed change); nothing is written until the person confirms. Sentences about supplier offers (words, or a supplier name held in the Offerte page) are answered `route: "quotes"` without calling the AI, and the company name is replaced before the call.

## 4. Collection framework

`collectors/base.py` defines `Collector` (metadata + `collect(ctx)`) and `CollectContext`:

* `ctx.fetch()` waits at least 1.5 s between requests to the same host, retries on 429/5xx and connection errors, archives raw bytes under `data/raw/<source>/`, and reports `unchanged` when the bytes are identical to a previous download.
* `ctx.add_price / add_trade / add_production / add_report / add_regulation / add_news` are the only write paths. They enforce provenance and revisions and normalise units and FX.
* `ctx.warn()` records non-fatal parse problems, which give the run the status **partial**. `ctx.checkpoint()` commits batches.
* The runner records a `collection_runs` row per run with one of these statuses: success, partial, no_change, failed, offline, or skipped (e.g. missing key). It also updates the source's status fields and then runs the post-collection hooks (FX backfill, quality checks, AI enrichment, alerts).

## 5. Milestone plan

| # | Milestone | Status |
|---|---|---|
| 1 | Foundation: architecture, schema, collector framework, scheduler, CLI, design system, navigation, start-up scripts, automatic DB column migration | **done** |
| 2 | Official data collection: USDA (National Honey Report PDF, FAS GATS, NASS), EU (Eurostat Comext, TAXUD weekly, DG AGRI decks, RASFF), Italy (CCIAA Cuneo, ISMEA, Osservatorio Nazionale Miele, CCIAA Siena), UN Comtrade, FAOSTAT, ECB FX, Federal Register, EUR-Lex, Brazil Comex Stat, EU TARIC / US HTS duties, origin-country notices (MAPA, SENASA, DGFT) | **done; every collector verified live against the real sources (4 Nov 2026, see DATA_SOURCES.md)** |
| 3 | Price intelligence: price database, explorer (M/Q/A, USD/EUR, per kg/lb), history, origin and variety comparisons, discrepancies, CSV export | **done** |
| 4 | Global news: GDELT (10 languages) + trade-press RSS (+ opt-in Google News), honey gate, dedup, relevance, AI summaries/translation (optional key), search and filters | **done** |
| 5 | Map (offline), country profiles and trade leaders/flows; regulations and duties UI; harvest & production: FAOSTAT production plus NASA POWER monthly weather and anomalies vs 1991-2020 for 64 honey regions (130 points), transparent rule-based signals (drought watch, heat stress, wet season) labelled as automatic assessments (Open-Meteo not used: its free tier is non-commercial) | **done** |
| 6 | AI assistant (database-grounded, cited answers, number and citation post-check; retrieval-only answers without an AI key), daily AI briefing (only with an AI key; the rule-based daily summary, labelled "not AI", stays otherwise) | **done** |
| 7 | Supplier quotes and landed-cost calculator (official EU/US duties incl. tariff quotas, ECB rates), alert center (5 rule types, no flood on bulk imports), historical archive (year-on-year views, revision history) | **done** |
| 8 | Polish, source verification on the live machine, performance, installer | in progress. Done: real starter data shipped with the app (`starter/`, merged once per version at start-up so a new installation opens with data); first-run notice; start scripts that install, check the Python version and update the program at every start (`scripts/launch.py`); keys pasted on the Sources page; responsive layout and a private read-only copy for the phone (GitHub Actions + Netlify, `docs/PHONE_ACCESS.md`); local server protection (§6) |

## 6. Security and privacy

* The server binds to `127.0.0.1` only, so it is not reachable from the network.
* It answers only the owner's own Paladex tab (`main.LocalOnlyGuard`): requests addressed to another host name are refused (a web page elsewhere that points its own domain at 127.0.0.1, "DNS rebinding", reads nothing); `/api` requests that the browser marks as sent by another site (`Sec-Fetch-Site`), and changing requests (POST, PUT, PATCH, DELETE) whose `Origin` is another site, are refused, so a page elsewhere cannot start a collection, load demo data or spend AI credits. No CORS header is ever sent, and the pages cannot be shown inside another site's frame (`X-Frame-Options`, CSP `frame-ancestors`). Anything that changes data or calls a paid service is a POST, PUT or DELETE, never a GET.
* API keys live in `.env` (git-ignored) and are only used server-side: in a request header where the source allows it, otherwise as a query parameter whose value is replaced by `REDACTED` in stored URLs, error messages and the log. A key pasted on the Sources page is written to `.env` (readable by the owner only) and never sent back to the browser.
* Supplier quotes, alerts, the assistant's questions and the settings never leave the PC. The only thing exchanged between the owner's installations is the corrections log (§3, "Corrections by a person"), through the `paladex-corrections` branch of the program's own git repository. The starter data (`services/starter.py`) and the online copy for the phone (`scripts/mirror/prepare_db.py`) are built without them, and the copy is checked for every key value before it is published (`scripts/mirror/scan_secrets.py`).
* Outbound data: requests to the public sources (generic client name `Paladex/0.1 (internal research tool)`, never the company name) and, only when an AI key is set, what the configured AI provider needs: news headlines and excerpts (summaries, translations), the database facts behind an assistant answer or the daily briefing, and the owner's question. Offers are included only when the question is about offers, as "Offer A/B/C", never with the supplier's name or the notes.
