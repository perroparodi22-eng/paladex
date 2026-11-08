# Handoff for the next working session (state on 8 Nov 2026)

Read this first, then README.md, docs/ARCHITECTURE.md, docs/DATA_SOURCES.md, docs/DEVELOPING.md and
docs/PHONE_ACCESS.md. Everything below is either in the repository or explained here; nothing from the
previous session's machine (temporary databases, scratch folders) carries over.

## 1. What Paladex is, and for whom

Private honey-market intelligence app for **Parodi Group** (bulk-honey importer, Italy/US). The owner
runs it on his Windows PC (`Avvia Paladex.bat`), his father will run it on his own PC, and a read-only
copy is published daily for the owner's phone (private Netlify project, Netlify login required).
Italian by default, English available. The owner writes short, informal messages (often in English,
sometimes Italian); answer in plain words, no jargon, and say plainly what you did and what failed.

**Hard rules (the owner insisted on all of them):**
- Never fabricate or estimate a figure. Full provenance on every figure (source, period, publication
  date, link). Never mix price types. Never present old data as current.
- Append-only history: a change is a new revision; nothing is deleted or overwritten.
- Official/government sources first; third-party sources only when labelled as such ("Altre fonti
  (non ufficiali)", each figure verified on the page it cites) and never mixed into official series,
  the map, totals or comparisons.
- Links must open a page a person can read (`frontend/src/lib/links.ts`: machine-only addresses open
  the same publisher's own page; the exact address stays in the link's description).
- Privacy: supplier quotes never leave the computer (except anonymised "Offerta A/B/C" to the AI when
  the question is about offers); the company name is never sent to external sites or the AI;
  `.env` and `data/` are git-ignored; never commit keys. User-Agent: "Paladex/0.1 (internal research tool)".
- Do not work around captchas, logins, anti-bot pages, terms of use, proxy or GitHub permission denials.
- The owner pays for Netlify (Pro, €20/month, ~3,000 credits; one deploy ≈ a few dozen credits) and
  watches usage: avoid needless deploys and oversized multi-agent runs.

## 2. Git, branches and how changes reach the owner

- Work branch: `claude/laughing-hopper-xd5urh`. **The owner's PC updates itself from git at every
  start** (`scripts/launch.py`: fetch + `merge --ff-only`). So never push unfinished or untested work:
  push only after the full checks pass.
- After each finished round, the owner has approved merging into `main` (PRs #2-#8, merge method
  "merge"); scheduled workflows run from `main`. After a merge: `git fetch origin main && git checkout
  -B claude/laughing-hopper-xd5urh origin/main && git push -u origin claude/laughing-hopper-xd5urh`.
- Commit trailers (exact):
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01GUBbpqasDs1fVteNsyDhSH` (a new session gets its
  own URL from its system reminder). No model identifiers in repository files.
- GitHub from the cloud session: use the GitHub MCP tools (PRs, merge, Actions runs and logs). Branch
  deletion is refused for the session (HTTP 403); ask the owner to do it on github.com.
- The repository has many unrelated branches of other projects (render-*, v2-*, v21-*, v3-*, pc-upload,
  aijo-nails-website, ...): never touch them.

## 3. Checking and integrating a change (what worked every round)

1. Snapshot the working tree into a clean worktree and test there:
   `git add -A && TREE=$(git write-tree) && SHA=$(git commit-tree $TREE -p HEAD -m tmp) && git reset -q`,
   then in a worktree (`git worktree add` once, then `git fetch <repo> $SHA && git reset --hard $SHA &&
   git clean -qfd -e frontend/node_modules`; symlink `frontend/node_modules` from the main checkout).
2. Backend: `cd backend && PALADEX_ENV_FILE=/nonexistent .venv/bin/python -m pytest -x -q -o addopts=""`
   (1,595 tests on 8 Nov; ~5 min). Without `-o addopts=""` the "N passed" line is hidden by the repo's
   `-q` default. Tests set `PALADEX_CORRECTIONS_SYNC=false` themselves.
3. Frontend: `npx tsc --noEmit -p .`, `node tests/run.mjs` (164 tests), `npx vite build`.
4. The built `frontend/dist` IS committed (the owner's PC has no Node): copy the build from the clean
   worktree into `frontend/dist` and commit it.
5. New or changed collectors: run them for real into a scratch data dir
   (`PALADEX_DATA_DIR=<dir> PALADEX_ENV_FILE=/nonexistent python -m paladex collect <keys>`), then
   rebuild the starter data: `python -m paladex starter-build --from <dir>/paladex.sqlite3` and test
   `python -m paladex starter-import` on an empty dir. Starter = `starter/paladex-starter.sqlite3.xz`
   (+ `.json`), merged once per version at start-up; local data always wins; corrections are stripped.
6. Never run a server of this checkout with corrections sync on (see section 6).

**Environment notes (cloud container):**
- No real database survives a new session. Get one with a full collection into a scratch dir
  (`python -m paladex collect`, ~35 min) or start from the starter (`starter-import`).
- Some Latin-American hosts need a CA bundle that combines the proxy CA and certifi:
  `cat /root/.ccr/ca-bundle.crt $(python -c 'import certifi;print(certifi.where())') > /tmp/combined-ca.pem`
  and `SSL_CERT_FILE=/tmp/combined-ca.pem`. Node's fetch behind the proxy needs `NODE_USE_ENV_PROXY=1`.
- Playwright + Chromium are preinstalled (`require('playwright')`, `chromium.launch()`).
- Hosts that refused or timed out from the dev network or GitHub: aduana.cl and dgft.gov.in (403 from
  GitHub), api.tech.ec.europa.eu and nube.agricultura.gob.mx (timeouts on GitHub 7 Nov),
  mymarketnews.ams.usda.gov (flaky; worked once from the dev network), english.vov.vn (anti-bot),
  insse.ro / inhort.pl (reset), mapa.gob.es (needs the FNMT cross-certificate embedded in
  `production_europe.py`).

## 4. The phone copy (GitHub Actions + Netlify)

- `.github/workflows/mirror.yml` ("Online copy (phone)"): check job (skips without
  `NETLIFY_AUTH_TOKEN`), then copy job: restore the CI database from actions/cache, collect all
  sources (~16-20 min), apply corrections from git (read-only), save the cache, build the read-only copy
  (`scripts/mirror/build.sh`: private-data-free DB copy, crawl of every page, report files, secret
  scan), publish to the private Netlify project `paladex-pg-mobile`
  (site id c063103b-a10a-4983-9388-abaa74eba5fe; https://paladex-pg-mobile.netlify.app, Netlify
  login required).
- Schedule: 04:17 UTC, but GitHub starts it hours late (12:11 UTC on 6 Nov, 11:08 on 7 Nov). Manual
  run: MCP `actions_run_trigger` with `workflow_id: mirror.yml`, `ref: main`.
- Secrets in the repository: `NETLIFY_AUTH_TOKEN` and 3 optional source keys (incl.
  `PALADEX_COMTRADE_API_KEY`). The owner gave Census and NASS keys in an earlier chat: they are not in
  this file on purpose; ask the owner if a local run needs them.
- **7 Nov failure (fixed in this handoff's commit):** the cache-save step's condition
  `hashFiles('ci-data/paladex.sqlite3')` hashed the 300+ MB database and exceeded the runner's 120 s
  limit, failing the job before the copy was built. Replaced by a shell existence check. **Verify the
  next run** (scheduled or manual) publishes.
- `scripts/mirror/prepare_db.py` keeps only listed tables (`KEEP`); a new table is private until added
  there (web_findings was added on 6 Nov).

## 5. What exists (state on 8 Nov 2026, main = this commit's merge)

- Sections: Panoramica, Prezzi, Notizie, Paesi (world map + country pages), Commercio, Aziende,
  Raccolti e produzione, Normative e dazi, Offerte fornitori, Avvisi, Archivio, Assistente IA,
  Fonti e qualità dati.
- **Simple / full view switch** (simple by default; `frontend/src/lib/view.tsx`, `lib/plain.ts`,
  `components/simple/`): plain words, short source chips, answer first.
- **World map**: fixed honey-market classes in tonnes; figures more than 2 years older than the newest
  are hatched "dato vecchio".
- **"2026 finora"**: year-to-date from monthly customs data vs the same months of 2025, same source
  only (`backend/paladex/api/ytd.py`).
- **Price comparisons** across a source's gap name the month compared with.
- **Other sources (non-official)**: `web_findings` (seed `backend/paladex/reference/web_findings_seed.json`,
  72 verified figures, 27 countries); each stored only if the quoted sentence and number are found on
  the cited page (`services/web_verify.py`). Optional weekly AI web search, off by default
  (`services/findings_ai.py`, Anthropic web search tool, ~$1/month at the default cap).
- **Corrections** by the owner's father (backend `services/corrections*.py`, `api/corrections.py`; UI
  `frontend/src/components/corrections/`): correct / flag / note; the AI only proposes, nothing changes
  before "Conferma"; new revision, official value kept, undo; exchange between computers through the
  `paladex-corrections` branch, **OFF until switched on, on each computer** (Fonti -> "Correzioni e
  note" -> "Scambia le correzioni con gli altri computer"). The phone copy applies them read-only.
- Collectors (21 modules, `backend/paladex/collectors/registry.py`): USDA (AMS report incl. ESMIS +
  MyMarketNews archive, FAS GATS, NASS), US Census, Eurostat Comext (EU-27), EC TAXUD weekly, DG AGRI,
  UK HMRC (trade + traders), UN Comtrade, FAOSTAT, ECB FX, Italy (ONM, CCIAA Cuneo/Siena, ISMEA),
  Argentina INDEC + MAGyP, Uruguay XXI (trade + exporters), Chile Aduanas + Odepa, Brazil Comex Stat +
  IBGE, Mexico INEGI + SIAP, Ukraine customs (data.gov.ua), Canada StatCan + CID importers, Turkey TÜİK,
  India EIC register + DGFT, Spain MAPA, Hungary KSH, Bulgaria MZH, Greece ELSTAT, tariffs (EU TARIC via
  UK XI, US HTS), regulations (Federal Register, EUR-Lex, RASFF, MAPA BR, SENASA AR), NASA POWER weather,
  news (GDELT, trade-press RSS; Google News feeds off by default for licence reasons), web findings.

## 6. Open items (in rough priority order)

1. **Phone copy refresh**: confirm the first run after the hashFiles fix publishes (deploy live, 0 failed
   requests, `{"report_links": N, "served": N}` in the build step).
2. **USDA National Honey Report gap Sep 2025 - Aug 2026**: the 12 issues exist in the official
   MyMarketNews file repository (`mymarketnews.ams.usda.gov/filerepo/reports?field_slug_id_value=2901`);
   the collector reads it automatically (right away when a month is missing, then at most daily), but
   the host timed out from the dev network and from GitHub on 6 Nov, so the starter and the phone copy
   still lack those months. Check whether the owner's PC filled them; if not, look for another official
   route. Never use the Internet Archive as the stored source.
3. **Father's PC setup** (not done yet): Python + clone of this private repository with a GitHub
   account that has access, start Paladex, set the author name ("Firmi come… cambia" -> "Papà"), paste an
   AI key (optional; without it the box works as a form), and switch on the exchange on BOTH computers.
   README section "Correzioni e secondo computer" has the steps; the owner may want them simplified.
4. Owner to paste the Comtrade key on his PC (Fonti e qualità dati); optionally switch on the weekly AI
   web search.
5. Smaller follow-ups found by the helpers:
   - USDA parser skips some rows (Nov 2025 "Dakota" rows outside the beekeeper table; "INDIAIA" May
     2026; "CanoLight Amber" Oct/Dec 2025, Jul-Aug 2026) - warned, not guessed.
   - Correction candidates keep USDA colour grades in English ("light amber") in the Italian UI.
   - Commercio page shows correction badges but has no "Segnala o correggi" buttons.
   - Panoramica (single latest USDA report) vs Prezzi (month average) can differ slightly (3,40 vs
     3,42 €/kg): both correct, maybe worth a label.
   - `docs/research/usda.json` still calls the MyMarketNews document URL pattern unverified.
   - Bulgarian bulletin's sales-price table (e.g. 4.92 BGN/kg to processors, 2025) not stored yet.
   - FranceAgriMer 2025 observatory is an image-only PDF (needs OCR to integrate).
   - Main JS bundle ~571 kB (gzip 173 kB): could be split further.
6. Known data limits (explained in the app): Uruguay publishes no weights; Chile 2025 only gross kg;
   INTA (Argentina) producer prices unreachable; Mexico SENASICA company list 403; China/India/Vietnam
   have no official 2025 production; Italy/Germany/France only association figures (in the non-official
   panel); Romania and Poland statistics hosts unreachable from the dev network.

## 7. Lessons from the last session (avoid repeating)

- **Corrections sync and the real remote**: a helper's test server pushed 9 fake "Papà" events to the
  real `paladex-corrections` branch because sync was on by default. Fixed: sync is off by default and
  switched on per computer; those 9 event ids are ignored (`IGNORED_EVENT_IDS` in
  `services/corrections_sync.py`); the owner deleted the branch. Any server you run from this checkout
  must keep `PALADEX_CORRECTIONS_SYNC=false`.
- Helpers (subagents) editing the same tree: give each its own files, tell them to re-read shared files
  before editing, never commit, and never push; the coordinator integrates.
- The container can restart mid-work (background agents stop; resume them by id) and the account has a
  5-hour usage limit (agents stop with HTTP 429; resume after the reset).
- GitHub scheduled runs can start hours late; `hashFiles()` on big files can time out.
- Check a figure's history before trusting a comparison: the empty "a month ago" column revealed the
  USDA gap.
