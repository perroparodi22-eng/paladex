# Developer guide

This guide covers the conventions every contributor follows (human or AI). For the overall design, see `ARCHITECTURE.md`. For what each source really provides, see `DATA_SOURCES.md` and `research/*.json`.

## Layout

```
backend/                     Python 3.11+ (FastAPI, SQLAlchemy 2, SQLite, APScheduler)
  paladex/
    config.py                settings from env / .env (PALADEX_*). Secrets never reach the browser
    db.py, models.py         schema (see ARCHITECTURE.md §Data model)
    enums.py                 PriceType, DataStatus, Reliability, Variety, ... (controlled vocabularies)
    reference/               countries (ISO3/M49/FAO codes, names IT/EN), varieties (multilingual normalisation)
    collectors/              one module per source; base.py = framework; registry.py lists modules
    services/                ingest (append-only revisions), fx, news, llm, quality, demo ...
    api/                     one router module per section; __init__.py lists them
  tests/                     pytest; fixtures/ holds recorded/reconstructed source files
frontend/                    React 18 + Vite + TypeScript + Tailwind + Recharts + Leaflet
  src/components/ui          design-system primitives (Panel, Badge, SourceLine, StatTile, ...)
  src/components/<area>/     area-specific components
  src/pages/<Page>.tsx       one file per route (routes are in App.tsx)
  src/i18n/pages/<ns>.ts     per-page dictionaries {it:{}, en:{}} -> keys "<ns>.<key>"
scripts/launch.py            start step run by the launchers: git update, requirements, serve
scripts/mirror/              read-only online copy for the phone (docs/PHONE_ACCESS.md)
scripts/dev/                 preview.sh (isolated backend+vite pair), screenshot.cjs
starter/                     real starter data merged at start-up (services/starter.py; rebuild with starter-build)
```

## Non-negotiable data rules

1. **Never fabricate data.** If a source has not been fetched or a value is missing, the UI says *"Dato non disponibile"* and does not interpolate or invent anything.
2. **Every fact carries provenance**: source, original URL, publication date, collection date, period, unit, currency, country, type and reliability/status. API responses include them, and the UI shows them through `<SourceLine>`.
3. **Never mix price types.** Wholesale quotes, producer prices, customs unit values and retail prices are different series (`PriceType`). Charts plot one price type at a time, or split them clearly into separate panels with labels.
4. **Append-only history.** Collectors write only through `ctx.add_*` and `services.ingest.record`, which keep revisions. They never `UPDATE` or `DELETE` observations.
5. **Old data never looks current.** Show the publication date and period. Use `freshness()` / `<FreshnessBadge>`, and say "latest published" rather than "current".
6. **Disagreement is shown, not resolved.** When two sources report the same thing differently, show both and flag the discrepancy.
7. **Demo data** is opt-in (`seed-demo`) and always has `is_demo=True`. API queries use `demo_clause()`, and the UI shows `<DemoBadge>`.
8. **AI output is labelled** (`<AiBadge>`, `summary_is_ai`, `DataStatus.AI_ASSESSMENT`) and never stored as a source fact.

## Writing a collector

* Create `backend/paladex/collectors/<module>.py` with `Collector` subclasses. Set all metadata attributes; see `fx_ecb.py` for a complete small example.
* `requires_key = "<settings attr>"`. Set `key_optional = True` if the collector still does something useful without the key.
* Fetch with `ctx.fetch(url, params=..., headers=...)`. It is polite (≥1.5 s per host), retries, archives the raw bytes and returns `.unchanged` when the bytes are identical to an earlier download. Skip re-parsing unchanged documents unless `ctx.force` is set.
* Write with `ctx.add_price / add_trade / add_production / add_report / add_regulation / add_news`. Set `data_status` (`published`, `provisional`, `estimate`, ...) and `published_at` whenever the source gives them.
* Parse defensively. When a row is malformed, call `ctx.warn(...)` and continue. Raise `CollectorError` only when the whole document is unusable. Call `ctx.checkpoint()` between independent batches (for example, one per country), so a late failure does not discard valid data.
* Keep parsing in pure functions (`parse_xxx(bytes) -> list[dict]`) so tests can call them directly.
* Tests go in `backend/tests/test_<module>.py`, using fixtures in `backend/tests/fixtures/<module>/`. Use the `run_with_routes` fixture (respx) to run the collector end to end offline. A fixture that is reconstructed from documentation rather than captured from the live source says so in a `README.md` next to it.

## Writing an API section

* Create `backend/paladex/api/<section>.py` with `router = APIRouter(tags=[...])`. Paths are relative to `/api`. Register the module in `api/__init__.py` (most sections are already listed).
* Use `Depends(get_db)`, filter demo rows with `demo_clause(Model, db)` and current revisions with `Model.is_current.is_(True)`.
* Return provenance: `source` (via `source_brief`), `source_url`, `published_at`, `collected_at`, `period_label`, `period_start`, `period_end`, `data_status`, `reliability`, `is_demo`.
* Anything that changes data or calls a paid service (AI) is a POST, PUT or DELETE, never a GET: the server refuses those methods from other websites (`main.LocalOnlyGuard`), which a GET cannot be protected against in every browser.
* An aggregate that reads a whole table (trade totals, every price row of a type) goes through `memo.cached(db, name, params, compute)`: it is reused until the next commit to the database (SQLite `PRAGMA data_version`, also seen from other processes) or the next day. The cached value is shared between requests: never modify it. Large answers can return `common.json_response(...)` (same bytes, without FastAPI's slow encoder pass).
* Tests use the `api` fixture (FastAPI TestClient on a fresh database, addressed as `http://127.0.0.1:8765`: the server answers loopback host names only).

## Frontend conventions

* Tone: premium financial research. Use the forest/ivory/gold/charcoal tokens (`tailwind.config.js`), serif headings, mono tabular numbers, 1px borders, small radii, no gradients, no decorative animation.
* Text is large and readable (base size 17px). Labels are clear Italian (default) with English, and there are no technical terms in the UI.
* Use `useI18n()` for strings and keep a dictionary in `src/i18n/pages/<ns>.ts`. Use `useLabels()` for country, variety and price-type names, and `lib/format.ts` for numbers and dates (`it-IT` locale by default).
* Use `@tanstack/react-query` for data, `api.get()` from `lib/api.ts`, and `<QueryState>` / `<EmptyState>` / `<ErrorBlock>`.
* Every number on screen should be one click (or one hover) away from its source.
* Desktop first; every page must also work on a tablet and on a phone (the online copy is read on the phone): check with `screenshot.cjs ... 390 844 mobile`.

## Running

```bash
cd backend && source .venv/bin/activate && pip install pytest respx && python -m pytest
cd frontend && npx tsc -b --noEmit && npx vite build
scripts/dev/preview.sh 9200 --demo        # isolated preview; prints the URL
node scripts/dev/screenshot.cjs http://127.0.0.1:9201/prezzi /tmp/claude-0/shots/x.png
scripts/dev/preview.sh 9200 --stop
```
