# Handoff for the next working session (state on 10 Nov 2026)

Read this first, then README.md, docs/ARCHITECTURE.md, docs/DATA_SOURCES.md, docs/DEVELOPING.md and
docs/PHONE_ACCESS.md. Everything below is either in the repository or explained here; nothing from the
previous session's machine (temporary databases, scratch folders) carries over.

## 1. What Paladex is, and for whom

Private honey-market intelligence app for **Parodi Group** (bulk-honey importer, Italy/US). The owner
runs it on his Windows PC (`Avvia Paladex.bat`), his father will run it on his own PC, and a read-only
copy is published daily for the owner's phone (private Netlify project, Netlify login required).
Italian by default, English available. The owner writes short, informal messages (often in English,
sometimes Italian); answer in plain words, no jargon, and say plainly what you did and what failed.

**The GitHub repository is PUBLIC since 16 Nov 2026 (the owner switched it and, asked, chose to keep it
public so his father's Mac downloads and updates without a GitHub sign-in).** Everything committed is
readable by anyone, on every branch (the repository also holds other projects of his on other
branches). So: never commit a name, an e-mail address, a key, a supplier, a quote or anything from
`data/` or `.env`; the corrections exchange would publish every correction on the
`paladex-corrections` branch (not created yet: tell the owner before it is switched on). A scan of
`main`'s whole history on 16 Nov found no key or password.

**Hard rules (the owner insisted on all of them):**
- Never fabricate or estimate a figure. Full provenance on every figure (source, period, publication
  date, link). Never mix price types. Never present old data as current.
- Append-only history: a change is a new revision; nothing is deleted or overwritten.
- Official/government sources first; third-party sources only when labelled as such ("Altre fonti
  (non ufficiali)", each figure verified on the page it cites) and never mixed into official series,
  the map, totals or comparisons.
- Links must open a page a person can read (`frontend/src/lib/links.ts`: machine-only addresses open
  the same publisher's own page; the exact address stays in the link's description).
- Privacy (headline translation): the public headlines of foreign-language news go to MyMemory when no AI key
  is set; nothing else does. Keep it that way: never excerpts with the owner's notes, never questions.
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
- Commit trailers: the `Co-Authored-By:` line the session's own system reminder gives (10 Nov, desktop
  session: `Co-Authored-By: Claude <noreply@anthropic.com>`), plus `Claude-Session: <url>` when the
  session has one (cloud sessions do). No model identifiers in repository files.
- On the owner's Windows PC the session uses `gh` (logged in as the owner) instead of the GitHub MCP
  tools: `gh run list --workflow mirror.yml`, `gh run view --job <id> --log`, `gh pr create`, `gh pr merge --merge`.
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
   (1,818 tests on 10 Nov; 6-9 min). Without `-o addopts=""` the "N passed" line is hidden by the repo's
   `-q` default. Tests set `PALADEX_CORRECTIONS_SYNC=false` themselves.
3. Frontend: `npx tsc --noEmit -p .`, `node tests/run.mjs` (180 tests), `npx vite build`.
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
  limit, failing the job before the copy was built. Replaced by a shell existence check (step id
  `keepdb`; the first version reused the id `db` and made the file invalid until fixed on 8 Nov).
  **Verify the next run** (scheduled or manual) publishes.
- `scripts/mirror/prepare_db.py` keeps only listed tables (`KEEP`); a new table is private until added
  there (web_findings was added on 6 Nov).
- **9 and 10 Nov failures = Netlify credits used up, not a bug.** The copy was built and checked, then
  Netlify refused the deploy: HTTP 403 "Account credit usage exceeded - new deploys are blocked until
  credits are added". Only the owner can fix it (add credits on app.netlify.com -> Billing, or wait for
  the billing period to renew); the balance is not visible from here. Since 10 Nov the Publish step
  recognises that answer and ends the run with a **warning** (run summary: "NOT published: the Netlify
  account has used up its credits") instead of a failed run and an e-mail every morning; any other
  Netlify error still fails the run. The phone keeps showing the last published copy (8 Nov 00:43 UTC)
  with its own date. Several deploys were made on 5-8 Nov while the copy was being set up; if credits stay tight, ask the owner whether to
  publish less often (the cron line) rather than deciding for him.
- **8 Nov scheduled run:** GitHub "lost communication with the runner" 45 minutes into the build step
  (normally 12 minutes); no log survived, so the cause is unknown and it has not happened again. The
  build step now has `timeout-minutes: 40`, so a stuck build ends with its log.

## 5. What exists (state on 10 Nov 2026)

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
- **Fixing a number = tap it and type the right one (11 Nov, owner: "not like a comment, like fixing the
  price to the real one", "for everything"):** `components/corrections/QuickFix.tsx`. `FixValue` wraps a
  number (small pencil) and opens `QuickFixDialog`: one input prefilled with the number as shown, Save /
  Enter, no reason asked. The value is typed in the unit on screen (`FigureRef.shown`, e.g. EUR/kg for a
  USD/lb row; big weights in tonnes) and `services.corrections.normalize` converts it. `parseTyped` reads
  Italian numbers ("69.298" = 69298 for tonnes, "1.775" = 1,775 for a price: the reading closer to the
  current value wins); a change of more than 5 times asks once. "Rimetti il numero della fonte" in the
  same window. A price averaged from a few rows of one period (two USDA lines of a month) is fixed by
  writing the value on each row (`row_ids` on overview tiles and `/prices/latest` points, max 6).
  Wired: simple and full Panoramica, Prezzi (simple, latest and records tables), country page (KPI
  tiles, production table), Commercio leaders (tonnes), Raccolti production table. NOT fixable by tap:
  sums of several rows (year-to-date figures, "12 m" totals, mirror data), trade values in USD, charts,
  the Archivio. The old drawer (flag a doubt / note) is one small link away in the window; without an
  AI key "Scrivi a Paladex" only offers the note on a country.
- **Companies found on the web (15 Nov, owner: "do the business part per each country, the first Google
  results, no need for them to update"):** a FIXED, non-official list, `reference/companies_web_seed.json`
  (169 companies, 60 countries: every European and every South American country has at least one
  since the owner's "do for ALL European countries and South American, do not stop until you do" of
  15 Nov; Italy has 12), served by `api/companies.py` as `web` (country) and `web_companies` /
  `web_searched_on` (overview), shown by `components/companies/WebCompanies.tsx` on the Aziende page and
  on every country page (simple view: under the prices), always apart from the official lists and
  labelled "Non ufficiale" with the search date; alphabetical, no figures, no ranking. Rules in
  `reference/companies_web.py`: a company is listed only with its OWN website, and only if
  `scripts/check_companies_web.py` could open that site and found the company's name and honey on it
  (17 of 72 candidates were left out: site refused automated readers or did not open; never worked
  around). `--recheck` says which entries still pass. The web search tool returned mostly directories,
  so many lists are short (one or two companies). How the European / South American round was done,
  to repeat it elsewhere: research helpers collected company NAMES seen in search results (run two
  or three helpers at a time: eight at once exhausted a shared web-search allowance), with any
  website address written in a result; where no address was shown, likely addresses of the name were
  tried by script and one was kept only when the page opened, carried the company's name and spoke
  of honey, and (for a generic .com) named the country. That last check matters: it threw out a New
  Zealand honey brand found for Malta, a Brazilian firm found for Croatia and a jewellery shop found
  for Bolivia. 45 entries found this way carry a generic one-line description ("Azienda che vende
  miele."). Pages in Cyrillic need the name in Cyrillic for the check. Never add a name from memory.
- **Asia (15 Nov, owner: "fill in India, Vietnam and Thailand, make sure Asian countries have all
  information needed"):** what the three pages lacked was news for Thailand and companies. Added: Google
  News searches `news_google_th_honey` (English, headline must name Thailand), `news_google_th_nam_phueng`
  (Thai) and `news_google_jp_hachimitsu` (Japanese; Japan is Asia's main honey importer and had no
  news source). An English search for Japan was tried and dropped: it returned only product listings.
  Read on the first real runs and now filtered: product pages, menus and social posts returned by any
  Google search (`services.news.is_shop_listing`, applied to the whole `google_news` family); Thai
  "น้ำผึ้ง" counts only next to a sector word (it is also a nickname, a TV show and an idiom);
  Japanese honey words count only with a sector word, and a shop or event story only with a market
  word. `tag_countries` now knows Japan. After the filters the three searches kept about 3, 3 and 15
  articles. Companies: India, Vietnam and Thailand have three web companies each. Not done, no free
  source found: wholesale or producer prices for Thailand (customs average values only), official
  2025 exports for Vietnam and Thailand (partner declarations are shown instead).
- **Country page shows everything (15 Nov, owner: "when I click on Italy or Vietnam I want to see EVERYTHING
  related to that country, also the business"):** the simple view of `/paesi/<ISO3>` no longer hides
  anything behind "Mostra dettagli". Order: top tiles, a "Vai a:" index (`SectionIndex`, buttons that
  scroll to `#prezzi`, `#aziende`, `#commercio`, `#produzione`, `#notizie`, `#normative`), prices (all
  the rows the profile carries, `SIMPLE_PRICE_ROWS = 10`), companies (web panel + the official block),
  trade (year so far + year by year and partners), production and web findings, news (full list),
  regulations, notes, what is missing, context, sources. The page is long on purpose.
- **Thailand official trade, Vietnam 2025 exports (15 Nov, owner: "try to find other sources"):** new
  collector `th_customs_honey` (`collectors/trade_thailand.py`): Thai Customs statistic report, honey
  04090000000, exports and imports by partner, monthly, kg and baht; first run from January two years
  back, then the last 4 months again. Verified live: 1,390 rows, 2025 exports 12,216 t, Jan-Sep 2026
  10,905 t; its 2024 totals equal FAOSTAT's. Thailand's page now shows its own 2025 and year-to-date
  figures and customs unit values by destination (the nearest thing to a bulk price: no Thai farm or
  wholesale honey price list was found in Thai or English searches). Vietnam: its customs does not
  publish honey separately; a newspaper figure was added to the web findings (Đại Đoàn Kết, 6 Aug 2026:
  nearly 32,000 t in 2025, honey together with pollen, royal jelly and propolis; quote checked with
  `services.web_verify`).
- **News for every country (16 Nov, owner: "make the news bigger, add more countries' news, about honey
  and honey companies of each country, make sure they also update live"):** 70 of the 130 countries
  had no news source (Central America and the Caribbean, most of Asia, the Middle East, Africa, New
  Caledonia). Each now has one Google News search, `GOOGLE_WORLD_FEEDS` in `collectors/news_feeds.py`
  (keys `news_google_<iso3>_honey`, built from `WORLD_NEWS_COUNTRIES`: language and the country's
  words), ON by default, read every 3 hours like the other feeds. The headline must carry the honey
  word (English, Spanish, French or Portuguese) and the query asks for beekeepers, exports, prices,
  production, companies or cooperatives. An item is kept when it names the country: by the country
  tagger, by the search's own words (`FeedSpec.country_words`, e.g. "Omani", "Kurdistan"; the item is
  then tagged with the country), or when the paper itself carries the country's name ("Jamaica
  Observer") and the text names no other country. Words that are also something else are left out
  (Georgia the US state, Jordan the first name, Sidr honey for Yemen).
  Read on the real feeds before keeping them: 68 searches answered, 50 countries had news, about 190
  articles of the last year. Filtered after reading: trade-data directory pages (Tridge, OEC), honey
  beer / tea / BBQ sauce / mustard, the bakery "Honey Bun", fast-food menus, "miel del amor",
  honey in Egyptian tombs, cane syrup ("miel de caña"), the band Miel San Marcos, Portuguese and
  French honeymoons. 18 countries had nothing recent (El Salvador, Honduras, Dominican Republic,
  Haiti, Armenia, Azerbaijan, Tajikistan, Mongolia, Cambodia, Singapore, Hong Kong, Laos, Kuwait,
  Central African Republic, Angola, Malawi, Mozambique, Madagascar): their searches stay on and
  will show news when it is published. Georgia and Saudi Arabia answered on the first read (2 and 8
  articles) and were refused on the second.
  **Google refuses bursts:** after about 45 searches one second apart it answered 429 for a while.
  All Google searches of the program are now spaced 4 seconds apart (`_google_pause`, not in tests);
  a refused search shows as failed on the Fonti page and is read again at its next turn. Do not
  shorten the gap or add many more Google searches without reading the answers on a real run.
  Tried on a copy of the owner's database: 8 searches, 57 new articles, Oman's and Jamaica's pages
  show their news.
- **Phone copy dropped by the owner (15 Nov: "forget about the phone app, forget everything about
  that"):** do not work on it or report on it unless he raises it again. `.github/workflows/mirror.yml`
  and `docs/PHONE_ACCESS.md` are still in the repository (he has not asked to remove or disable them).
- **Does the data update? (checked 15 Nov):** yes, while Paladex is open. The owner's database had no
  collection run after 11 Nov because the app had not been started since; a full run on a copy brought
  about 2,400 new rows. It does not collect while closed (no service, no start with Windows).
- **After an update (11 Nov, owner: "Germany did not update, I cannot see their prices"):** two causes, both
  fixed. (1) A source brought by a new version waited for its own schedule when the last collection was
  less than 6 hours old: `scheduler.start` now collects at once the registered sources that have never
  run (`never_collected_keys`). (2) `index.html` was served without `Cache-Control`, so a browser could
  keep the old page (and the old script names) for hours: it is now `no-cache`. When checking a new
  build in a browser that has seen the old one, do not trust a page opened before this fix. The "304"
  lines in the terminal are normal ("not modified" answers), not errors.
- **Prices on the country page (11 Nov):** simple view shows `CountryPricesSimple`
  (`components/countries/CountryPrices.tsx`) right under the top tiles: per kind of price, up to 4 lines in
  EUR/kg, one per market (`pickCountryPrices`), FAO's copy of a Eurostat price left out, each number
  fixed by tapping it; the full view's price table got the same tap-to-fix. Data: `profile.prices` (it
  already carried `row_id` and `correction`).
- **Price chart (full Prezzi, 11 Nov, owner: "Italy: they appear but when I click them they do not"):**
  the legend refused a ninth series with a small note. `useSeriesSlots.toggle` now shows it in place of
  the series shown longest (same colour slot); a lone point (a yearly figure among monthly lines) is
  drawn bigger; legend names wrap on two lines instead of being cut.
- **European prices (11 Nov, owner: "all European countries should have their prices listed"):** new collector
  `eurostat_honey_prices` (`collectors/prices_europe.py`, Eurostat `apri_ap_anouta`, honey, EUR per 100 kg,
  annual producer price, 17 countries; verified live: 358 rows). The simple Prezzi page has a new block
  "Europa, paese per paese" (`EuropeTable` in `components/simple/SimplePrices.tsx`): every country of
  region "Europe" with its newest producer price (Eurostat preferred over FAO's copy unless FAO is newer,
  `preferEurostat`), old figures named with their year, and the countries with no price said in words
  (on the owner's data: Belgium, Denmark, Finland, France, Ireland, Malta, Montenegro, Netherlands).
  Searched and NOT found: a free monthly bulk price list for any European country other than Italy.
  Spain's MAPA weekly workbook (`precios_medios_nacionales_<year>-s<week>.xlsx`) has no honey row; MAPA
  publishes honey prices once a year per campaign as a PDF ("Precios sector miel", monthly figures
  inside): not integrated. DG AGRI's deck (`ec_honey_market`, already collected) stored no price rows on
  the owner's data; its site answered 429 to one request on 11 Nov, not retried.
- **Simpler look (11 Nov, owner: "more simplistic, easier to view"):** one place, `tailwind.config.js` and
  `styles/index.css`: rounder corners, soft card shadow, labels and table headers in normal letters (no
  spaced capitals), numbers in the text font (`.num` is no longer monospace), badges as small pills,
  the "Fonte" chip as a quiet line of text. Keep new components on these classes.
- **Corrections** by the owner's father (backend `services/corrections*.py`, `api/corrections.py`; UI
  `frontend/src/components/corrections/`): correct / flag / note; the AI only proposes, nothing changes
  before "Conferma"; new revision, official value kept, undo; exchange between computers through the
  `paladex-corrections` branch, **OFF until switched on, on each computer** (Fonti -> "Correzioni e
  note" -> "Scambia le correzioni con gli altri computer"). The phone copy applies them read-only.
- Collectors (23 modules, `backend/paladex/collectors/registry.py`): USDA (AMS report incl. ESMIS +
  MyMarketNews archive, FAS GATS, NASS), US Census, Eurostat Comext (EU-27), EC TAXUD weekly, DG AGRI,
  UK HMRC (trade + traders), UN Comtrade, FAOSTAT, ECB FX, Italy (ONM, CCIAA Cuneo/Siena, ISMEA),
  Argentina INDEC + MAGyP, Uruguay XXI (trade + exporters), Chile Aduanas + Odepa, Brazil Comex Stat +
  IBGE, Mexico INEGI + SIAP, Ukraine customs (data.gov.ua), Canada StatCan + CID importers, Turkey TÜİK,
  India EIC register + DGFT, Spain MAPA, Hungary KSH, Bulgaria MZH, Greece ELSTAT, tariffs (EU TARIC via
  UK XI, US HTS), regulations (Federal Register, EUR-Lex, RASFF, MAPA BR, SENASA AR), NASA POWER weather,
  news (GDELT, trade-press RSS; Google News feeds off by default for licence reasons), web findings.
- **News per country (10 Nov):** 93 country feeds for 57 countries, all 39 European and all 10 South
  American countries included (third batch; next regions not done: Central America & Caribbean,
  Asia, Middle East, Africa). South American honey feeds are `archive` feeds (entries up to 10
  years old are stored): the owner asked that every country there shows its latest honey article
  even when it is old. The page then says the month of that article (`news.latest_at`, note after
  120 days) and `news.highlights` falls back to the newest trade stories of any age. Five feeds
  that were live for a few hours are retired by `reference/seed.py` (`RETIRED_SOURCES`).
  (first batch: 28 feeds, 20 countries; second batch the same day: 48 feeds for the 31 European
  countries still missing, see the comment above the list for the sites that refused) (`COUNTRY_FEEDS` in
  `collectors/news_feeds.py`, table row in docs/DATA_SOURCES.md): the publisher's honey tag feed, its
  search feed for "honey", or a sector association's feed; a general farm/business feed filtered by the
  honey gate where nothing better exists (Brazil, India, Vietnam, China, Turkey). Items carry the feed's
  country (`home_tag` -> `home_country` in `services.news.analyse`). The honey gate now also reads
  Hungarian (unfolded "méz", never "mez"/"mező"), Romanian ("miere"), Polish, Czech, Slovak, Slovenian,
  Dutch, Swedish, Danish, Norwegian, Finnish, Lithuanian, Latvian, Estonian, Greek and Albanian honey
  words. A word that is honey in one language and something else in another counts only in items of
  its own language (`_GATE_LANGUAGE_ONLY`: Slavic "med", Dutch "honing", Polish "pasieka", Albanian
  "mjaltë"; found by reading real feeds: Lithuanian "pasiekė" = reached, Icelandic "mjaltir" = milking).
  Before adding a language, run its real feeds through `analyse` and read what passed. First real run: 28 of 28 feeds answered, about 140 honey articles stored
  (the database had 29). GDELT stays registered but has refused every request since 5 Nov, on the PC
  and on GitHub: the RSS feeds are what fills the news now.
- **Headline translation without an AI key (10 Nov):** `services/title_translate.py` fills `title_it` with a
  machine translation from MyMemory (free, no key; only the headline is sent), run after each collection
  (`collectors/runner.py`), labelled "Traduzione automatica" (`ai_model = "mymemory"`, `display.title_by =
  "machine"`, `MtBadge` / `TranslatedBadge` in `components/ui`). About 55 headlines a day per computer
  (5,000 characters), unreadable languages and relevant articles first; ten times more with
  `PALADEX_TITLE_TRANSLATION_EMAIL`. **16 Nov, owner: "translate the headlines of the news, all of them
  and always", and yes to his address as the service's contact:** the address is in the `.env` of his
  PC only (never in the repository, which is public; his father's Mac needs the same line in its own
  `.env` or stays at 55 a day). Tried on a copy of his database: no allowance notice past 5,000
  characters, about 55 headlines a minute. Chinese and Japanese headlines were all being rejected by
  the checks, though the translations were right: the length limit now allows for compact scripts and
  the number check reads full-width digits and the units 万 / 億 / 千 / 割 (`_numbers_source`; "10万" is
  100,000, and a translation saying 10,000 is still refused). `RULES` in the module is raised when
  the checks change, and the headlines rejected before are then asked again once. Still refused, by
  design: a one-word headline for which the service has only someone's translation memory
  ("OKTOBER" came back as "14 Ottobre"). Does nothing when an AI provider is configured (the AI translates and
  replaces machine translations). Tests switch it off (`conftest.py`); `test_title_translate.py` mocks it.
  English titles are not produced (the allowance goes to Italian, the default language).
- **China, India, Vietnam news = Google News searches (10 Nov, owner's explicit request: "use normal Google"):**
  `GOOGLE_COUNTRY_FEEDS` in `collectors/news_feeds.py`, keys `news_google_*`, ON by default (the generic
  `news_gn_*` searches stay opt-in). English searches keep only items whose own text names the country;
  the Vietnamese and Chinese ones tag the country. First real run: India 4, Vietnam 13, China 12 articles.
  Article links are Google redirect links (never resolved by the app); in a browser without Google
  cookies the first visit shows Google's consent page.
- **Brazil exports (Comex Stat) and failed name look-ups (10 Nov):** the owner's router fails DNS look-ups
  for seconds at a time (Windows then answers "not found" from memory for ~5 s): ten sources failed in one
  round with "getaddrinfo failed". `CollectContext.fetch` now retries a failed look-up 4 times, 6 s apart,
  without counting it against `retries`. Comex Stat itself answered 429 to a query sent right after the
  run's look-up requests and 200 twelve seconds later: the run pauses 12 s before its query and is
  scheduled 4 times a day instead of once. Verified live: 41 new rows on a copy of the owner's database.
  Still broken and not touched: ISMEA (the page no longer has a table; data stuck at June 2026).
- **Most important news:** `services.news.importance` = relevance score + 3 per further outlet (max 3)
  - 1.5 per day of age. `/api/news?sort=top&days=30` (window counted by the server, so the phone copy
  can answer it) feeds "Le più importanti" at the top of Notizie (5 stories, hidden while filters are
  on; `components/news/TopNews.tsx`). Country pages: `news.highlights` = the one or two stories of the
  last 365 days tagged with the country AND a trade topic (trade, prices, tariffs, import
  restrictions), shown first in "Notizie recenti" and, in the simple view, as their own panel. Two
  outlets on one story count once in these short lists (`services.news.same_story`).

## 6. Open items (in rough priority order)

1. **(Dropped by the owner on 15 Nov: see section 5, do not work on it.)** Phone copy: blocked by Netlify credits since 9 Nov (section 4). Nothing to fix in the code; the
   owner must add credits or wait for the renewal, then the next run publishes by itself (or trigger
   one). The workflow change that stops the daily failure e-mails only takes effect once it is on
   `main` (scheduled workflows run from `main`). After the first successful run, check that the crawl
   still reports 0 failed requests with the new news requests (`/news?sort=top&days=30...`) and that
   the 28 new feeds collect from GitHub's network.
2. **USDA gap Sep 2025 - Aug 2026: filled in the phone copy** (run 10 read every issue from 31 Oct 2025 to
   30 Sep 2026 from the MyMarketNews file repository). The shipped starter data still lacks those months
   (rebuild it from a database that has them at the next starter rebuild); the owner's PC fetches them
   by itself. GDELT news: rate-limited on GitHub ("one request every 5 seconds", a few searches postponed
   per run) and refused from the dev network since 4 Nov; worth a look if the news section thins out.
3. **Father's PC setup** (in progress on his MacBook Air through GitHub Desktop, 16 Nov; the repository is
   public now, so downloading needs no account, but the automatic update at start needs the `git`
   command on the Mac and the corrections exchange needs an account allowed to write): Python + clone
   of this repository, start Paladex, set the author name ("Firmi come… cambia" -> "Papà"), paste an
   AI key (optional; without it the box works as a form), and switch on the exchange on BOTH computers.
   README section "Correzioni e secondo computer" has the steps; the owner may want them simplified.
4. Owner to paste the Comtrade key on his PC (Fonti e qualità dati); optionally switch on the weekly AI
   web search.
5. Smaller follow-ups found by the helpers:
   - USDA parser skips some rows (Nov 2025 "Dakota" rows outside the beekeeper table; "INDIAIA" May
     2026; "CanoLight Amber" Oct/Dec 2025, Jul-Aug 2026) - warned, not guessed.
   - Correction candidates keep USDA colour grades in English ("light amber") in the Italian UI.
   - (done 11 Nov) Commercio: the leaders' tonnes are fixed by tapping them. Still without a tap-to-fix:
     sums (year-to-date, "12 m"), trade values, the flows table, the Archivio.
   - (fixed 10 Nov) Panoramica vs Prezzi: the tile took ONE of two USDA rows of the same month by row
     id, so its figure and month-on-month change disagreed with Prezzi (India: -16,4% shown, -8,4%
     real). Rows of one series, product and period are now averaged (`overview.AveragedPoint`,
     `averaged_rows` on the tile, `row_id` null).
   - From the 10 Nov review, not done: `trade.Candidate.complete/uses_world` could count a year as
     complete from 11 World months + 12 partner months (read from the code, not reproduced);
     `/api/trade/flows` top-level freshness is source-level; `POST /api/quotes` accepts currencies
     without an ECB rate; headlines stay in their own language without an AI key (the country lines
     now say the topic in words).
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
- Validate workflow edits with actionlint (`pip install actionlint-py`, then `actionlint -shellcheck= .github/workflows/mirror.yml`), not only a YAML parser: on 8 Nov a duplicate step id (`db`) made GitHub reject the whole file (instant "failed" runs on every push, emails to the owner, no daily run) although it parsed as YAML.
- Check a figure's history before trusting a comparison: the empty "a month ago" column revealed the
  USDA gap.
- 10 Nov review (two read-only helpers, backend by API probing on a database copy, frontend by code
  reading) found real bugs the 1,595 tests did not: a month Eurostat published with 6 partners and no
  total was charted as Italy's total (-87% alert), a source line showed a period end as "published
  on", page numbers beyond 64 bits answered HTTP 500, a failed filter on Notizie removed the filters.
  All fixed with tests in `backend/tests/test_round_nov10.py` and `frontend/tests/country-news.test.tsx`.
  A review against real data is worth repeating after each large round.
- The owner's Windows PC: the app's own `.venv` has no pytest (make a separate venv outside the
  repository); two tests failed only on Windows (symlink right, read-only git objects) and now pass;
  the frontend tests are pinned to UTC (`tests/run.mjs`) because a fixture stamped 23:19 UTC is the
  next day in Italy. Never touch `data/` there: it is the owner's real database (copy it read-only).
