# Paladex: handoff report

**Last updated:** 6 October 2026 (session 3, after the polish pass in section 5b)
**Project folder:** `C:\Users\diego\Downloads\paladex` (the `casa-parodi` folder is a different project and was never touched). Not a git repository.

Upload this file at the start of the next session, together with your original brief ("THE ULTIMATE 3D PADEL RACKET DATABASE", sections 1–42). The brief is the source of truth for scope; your later redirects (section 2) override it where they conflict. This file is the source of truth for what already exists and what to do next.

---

## 1. Start here (for the next session)

Paste this as your first message in the new session, with this file attached:

> Continue building Paladex in `C:\Users\diego\Downloads\paladex`. Read `HANDOFF.md` first and follow "Remaining work" in order. Keep `HANDOFF.md` updated as you go. Don't touch the `casa-parodi` folder.

Then the agent should:

1. Read this file, `PRODUCT.md`, `AGENTS.md` and `.impeccable/surfaces/src-app-site-page-tsx.md` (the design direction). `AGENTS.md` matters: this is **Next.js 16.3.8**, and some APIs differ from older versions (section 9).
2. Start the dev server (section 3) and open `http://localhost:3100`.
3. Work through section 6 in order.

---

## 2. What the product is

**Paladex** (working name; change it in `src/config/site.ts`) is a 3D-first padel racket website. You pick a brand, turn every racket in 3D, read its specs in plain language, take a quiz to get matched to a racket, and click through to retailers (affiliate links).

**Decisions you made (keep them):**

| Topic | Decision |
|---|---|
| Name | Paladex (working name). Header subtitle: "Rackets 3D Showroom" |
| Market | English UI, prices in EUR, EU-wide |
| Approach | Code-first (Next.js), no website builder |
| Visual direction | **"Black studio"** (session 3, latest): dark and premium, black and white, no strong blue. Rackets stand on a minimal black (or white) studio sweep with a soft shadow. Smooth 3D reveal animations that play **once** and never hide again. Simple 3D controls anyone understands. Two earlier directions were rejected: "Court at Night", then a bright golden-hour/court-blue rework. |
| Navigation | A three-line menu icon opens a side drawer. No big title animation. |
| Brands | **Merged into the rackets browser**: `/rackets` starts with a rail of brand tiles, and picking one filters the rackets in place. `/brands/[slug]` still exists for SEO and shows the same browser with that brand selected. `/brands` redirects to `/rackets`. |
| Compare | **Removed from the site for now** (your call). `/compare*` redirects to `/rackets`. The code is parked, unused, in `src/components/compare/` and `src/lib/compare.ts` in case you want it back. |
| Keep | Find my racket, the 3D Showroom, the "Where do you win your points?" court, the logo mark |
| 3D models | **You send racket photos; I build the 3D model from them** and also show the photos on the site |
| More rackets | You'll send more racket photos |
| Reports | Keep this handoff file updated when the session is about to run out |

**Honesty rules from the brief (non-negotiable, already built in):**

- Never fake functionality.
- Placeholder affiliate links are `AFFILIATE_URL_HERE`. The site never pretends they work: clicking one shows a "link not active yet" page.
- Demo offers and demo prices are labelled "demo" and never go into structured data.
- Manufacturer specs are kept separate from the platform's own scores. Scores are labelled "Platform evaluation (sample)".
- Specs are marked "unverified" until checked.
- No invented reviews or star ratings.
- Every 3D model shows where it came from: official, licensed, platform-created, placeholder or none.

---

## 3. How to run it

```bash
cd C:\Users\diego\Downloads\paladex
npm install          # also copies the Draco/Basis decoders to public/decoders
npm run setup        # first time only: creates .env.local, migrates and seeds the database
npm run dev          # http://localhost:3000
```

**Dev server notes**

- **Netlify preview:** https://paladex-preview.netlify.app. It requires a Netlify login (team protection) and has no admin secrets, so `/admin` is locked.
  - Deploy from a clean copy that excludes `.env.local`, `node_modules`, `.next`, `data/*.db` and `assets/reference`, because the Netlify uploader ignores `.gitignore`.
  - The build seeds the SQLite file, and `next.config.ts` bundles it with the server code. On the server, `src/server/db/connection.ts` copies it to the temp folder on first use, because the bundle is read-only.
  - `/api/health` returns `{ ok, rackets }`, or the database error. Check it first if pages show "error".
- **Performance checks:** see section 5b for the scripts in `.tmp/` (site check, menu check, scroll trace, shader timing). Measure performance on a production build; the dev server is much slower.
- **Screenshots:** the Browser pane is often hidden, so its screenshots go stale. Use the headless tool instead: `node .tmp/shoot.mjs <url> <out.png> [width] [height] [full=0|1] [waitMs] [reducedMotion=1] [scrollY]`. Set the `HOVER=x,y` environment variable to move the mouse before the capture, and `EVAL='<js>'` to run JavaScript and print the result (e.g. click the menu). It runs Chrome over the DevTools protocol with SwiftShader WebGL, so the 3D renders.

- In the Claude desktop app, the preview tool reads the *casa-parodi* launch config, so it can't start Paladex by name. Workaround: start it from a shell with `npx next dev -p 3100` (log to `.tmp/dev.log`), then open `http://localhost:3100` in the browser pane with `preview_start {url}`.
- If pages that use `generateStaticParams` (racket, brand, guide, collection and legal pages) suddenly return 500 with *"Jest worker encountered 2 child process exceptions"*, the dev server's worker is stuck. **Restart the dev server.** That fixed it this session; it isn't a code bug.
- **Admin password:** it is in a comment at the top of `.env.local`, created by `npm run setup`. Never paste it into chat. To set a new one, run `npm run admin:hash`, then put the output in `ADMIN_PASSWORD_HASH`.
- Useful commands:
  - `npm run typecheck`: passes (session 3).
  - `npm run lint`: 0 errors (session 3). Three React Compiler hints (`set-state-in-effect`, `refs`, `preserve-manual-memoization`) are set to warnings in `eslint.config.mjs`, because the viewer and dialogs legitimately sync state with browser APIs in effects.
  - `npm run build`: passes (session 3).
  - `npm run db:seed -- --force`: wipes and reseeds the catalog tables.
  - `npm run db:studio`: browse the database.

**Stack:**
- Next.js 16.3.8 (App Router, Turbopack), React 19.3, TypeScript 5.9, Tailwind CSS v4.
- 3D: three 0.186, @react-three/fiber 9.8, @react-three/drei 10.7, camera-controls.
- Data: Drizzle ORM 0.45 + libSQL. SQLite file `data/paladex.db` locally; Turso in production.
- Other: zod 4, sharp and gltf-transform for the 3D pipeline, aws4fetch for S3/R2 uploads.
- Node 24.

---

## 4. Status at a glance

✅ = built and checked in screenshots. 🟡 = built but not fully QA'd. ⬜ = not started.

| Area | Status | Where |
|---|---|---|
| Homepage: black-studio 3D hero, brand rail, showroom preview, popular rackets, court zones, finder prompt | ✅ desktop and mobile | `src/app/(site)/page.tsx`, `components/home/*` |
| Header (logo, subtitle, search, Menu) and side-drawer navigation | ✅ | `components/layout/SiteHeader.tsx`, `components/ui/Dialog.tsx` (variant `drawer`) |
| Rackets and brands `/rackets` (brand tiles, search, filters, sorts, URL sync, mobile filter sheet) | ✅ | `components/catalog/RacketsBrowser.tsx`, `CatalogExplorer.tsx`, `BrandTiles.tsx` |
| Racket page `/rackets/[slug]` (3D viewer, specs explained, scores, where to buy, review, photos, model info, similar rackets) | ✅ | `components/racket/RacketDetail.tsx` |
| 3D viewer (simplified): drag to rotate, turn left/right, Front/Side/Back, slow auto-turn, reset, full screen, Details (hotspots) and White/Black studio switches | ✅ | `components/three/Racket3DViewer.tsx`, `SimpleControls.tsx`, `scene/*` |
| Showroom `/showroom` | ✅ | `components/showroom/ShowroomExperience.tsx` |
| Finder `/finder` | 🟡 (question screen checked; results not re-checked in dark) | `components/finder/FinderQuiz.tsx` |
| Admin panel (rackets list and editor with live 3D preview, draft preview, brands, retailers, insights) | 🟡 (built; full click-through test still to do) | `src/app/admin/*`, `components/admin/*` |
| Guides, collections, legal, about, contact | 🟡 (return 200; not re-checked visually in dark) | `content/*`, `app/(site)/*` |
| Affiliate redirect, analytics, SEO, security headers, photo → 3D pipeline | ✅ (unchanged since session 2) | see section 8 |
| Lint, typecheck, build | ✅ | |
| Docs (README, 3D pipeline, architecture, deployment, security) | ⬜ | `docs/` doesn't exist yet |
| `DESIGN.md` and the impeccable finish review | ⬜ | |

---

## 5. What was done in session 3

1. **Admin panel finished:**
   - Rackets table.
   - The full racket editor (`components/admin/RacketForm.tsx`), with a live 3D preview and a publish checklist.
   - Draft preview.
   - Brands, retailers and insights pages.
2. **First redesign** (after "it looks robotic"): a bright golden-hour/court-blue "replay" world. **You rejected it** as too strong and too bright.
3. **Second redesign: "Black studio"** (your latest brief):
   - **Colours:** `src/app/globals.css` was rewritten.
     - Ground `#0a0b0d` and graphite surfaces.
     - Off-white `#eceef1` actions with dark text. The strong blue is gone.
     - The token names `court`/`on-court` were kept, so `court` now means "the action colour" (off-white).
   - **3D stage:** `components/three/scene/Stage.tsx` is now a studio.
     - A black (`#070809`) or white (`#e7e8eb`) sweep.
     - Softbox and rim lights, plus a contact shadow.
     - No sky, turf, fog or particles.
   - **Viewer simplified:**
     - New control bar (`SimpleControls.tsx`): turn left, Front/Side/Back, turn right, plus play/pause, reset and full screen.
     - Clamped camera (`scene/CameraRig.tsx`): no panning; zoom limited to between 0.45× and 1.3× of the fitted distance; limited up/down tilt; gentle inertia; slow auto-turn.
     - The hint reads "Drag to rotate".
     - Hotspots stay off until you press "Details".
   - **Animations:** `components/ui/Reveal.tsx` reveals each section once, with a soft 3D tilt (IntersectionObserver), then leaves it alone. Nothing disappears when you scroll back. Reduced motion is respected.
   - **Header:** logo, "Rackets 3D Showroom", search, and a Menu button with a three-line icon that slides a drawer in from the right.
   - **Brands merged into rackets:** `BrandTiles` sits at the top of `/rackets`; each brand is shown by one of its rackets on a mini studio sweep. Picking a tile:
     - filters the rackets in place;
     - shows a "{Brand} rackets" heading with the brand description;
     - scrolls the chosen tile into view.
   - **Compare removed** from the navigation, cards, racket pages, finder, showroom, footer, sitemap and Open Graph images. Redirects are in `next.config.ts`.
   - **Cards:** dark, with a hover lean in 3D and a soft shadow (`components/racket/RacketCard.tsx`).
4. **Bugs fixed:**
   - **Product photos in cards collapsed to 32 px tall.** Cause: the preview root had both `relative` and `absolute`, and `cn()` doesn't merge Tailwind classes. Fixed in `Racket3DPreview.tsx`.
   - **The showroom's next/previous buttons overlapped the studio switch.** They now sit under the stage, with a "Racket 3 of 16" counter.
   - The old header-wrap issue at 1024 px is gone, now that the header uses a menu button.
5. **Checks:**
   - Typecheck, lint (0 errors) and the production build all pass.
   - Headless screenshots at 1440 px and 390 px: home, racket page, showroom, finder, rackets with a brand selected, and the open drawer. They are in `.impeccable/review/`.

---

## 5b. Polish pass (session 3, after the dark redesign)

Your brief: smoother scrolling (top priority), a normal hamburger menu next to the logo, and a faint puzzle pattern in the background. Everything else was kept as it was.

**Smoothness.** These were measured with Chrome traces, not guessed:

- The 3D kept redrawing during scrolling. `components/three/scroll-activity.ts` (one passive scroll listener) pauses the idle auto-turn and pointer lean while the page scrolls, and resumes 160 ms after it stops. Draw calls during a test scroll fell from about 7,600 to about 1,100.
- Auto-turn never restarted after it stopped (when switched on after load, or 3.5 s after touching the racket). Fixed with a wake-up in `scene/CameraRig.tsx`.
- **Shader compiling froze the main thread** for about 1.2 s while the home page loaded, so early scrolling stuttered.
  - `ViewerScene` now compiles each model's shaders in the background (`WarmModel`, using `renderer.compileAsync`) before showing it. The surface-grain variant is compiled on stand-in meshes.
  - The environment light-map shader is pre-compiled in `scene/pmrem-warmup.ts`.
  - Blocking time is now about 70 ms.
- **Phones:** the full-screen hero blocked vertical swipes, because camera-controls sets `touch-action: none`. It is now `pan-y`: vertical swipes scroll the page and horizontal drags turn the racket. Full screen keeps every gesture.
- The mouse wheel over the showroom stage no longer zooms; it scrolls the page. Wheel zoom works in full screen or after clicking the viewer.
- Removed the `backdrop-blur` from the sticky header and the viewer controls (they blurred the live canvas on every frame), and the `filter: blur` shadows on cards.
- Pixel ratio is capped at 1.5 (high tier) and 1.25 (standard).
- The home showroom viewer warms up about 1.5 screens before it is seen, so it doesn't start mid-scroll.
- **Font:** Google Sans Flex is now self-hosted from `public/fonts/` and trimmed to the axes in use (opsz, ROND, wdth 100–115, wght 400–700). It used to be 816 KB + 627 KB; latin is now 220 KB. The `@font-face` rules are in `globals.css`.
- Removed `(site)/loading.tsx`. It caused a layout shift on `/rackets` and made unknown racket URLs return 200; they now return 404.
- Smooth scrolling: native `scroll-behavior: smooth` for anchors and jumps (off with reduced motion). There is no scroll-hijacking library, because it would cost frames.

**Menu.**

- The three-line button now sits at the top left, next to the logo.
- The drawer slides in from the left. Its close button sits exactly where the menu button was, followed by the logo and a "Menu" heading. "Home" is the first entry.
- Escape, clicking outside and following a link all close it, and focus returns to the menu button.

**Background.** A jigsaw outline pattern at about 4.5% white is set on `body` in `globals.css`. It is a static SVG tile that scrolls with the page, with no fixed background and no animation.

**Other fixes found in the checks:**

- Filter chips with zero matches failed contrast; they now use readable grey with a dashed outline.
- Heading order on `/rackets`, collections and the showroom.
- The footer link now reads "Read the affiliate disclosure" instead of "Read more".
- `themeColor`/`colorScheme` were still set for the old light theme.

**Results (production build, Lighthouse 13.5):**

| Page | Desktop before → after | Mobile before → after |
|---|---|---|
| Home | 68 → 99 | 46 → 76 |
| Racket page | 63 → 100 | 36 → 81 |
| Rackets | 91 → 99 | 76 → 86 |

- Accessibility and best practices score 100 on home, rackets, racket, showroom, finder, collection, guide and other pages.
- SEO is 69 only because indexing is blocked until `ALLOW_INDEXING=true`.

**Test tools in `.tmp/`** (run against `npm run build && npx next start -p 3200`):

- `sitecheck.mjs`: every sitemap page at 390 and 1440 px. Checks console errors, failed requests, horizontal overflow, h1 count, unnamed controls, and every internal link.
- `menucheck.mjs`: Tab order and focus rings, plus menu open and close by Enter, Escape, ×, clicking outside and following a link, on 7 pages at 2 widths.
- `trace.mjs <url>`: scroll trace with draw-call counts and busy time per thread.
- `shaders.mjs <url>`: main-thread time spent waiting on shader compiles.
- `shoot.mjs` also takes `GPU=1`, `DPR=2`, `SWIPE=x,y,dx,dy` (touch drag) and `EVAL`.

---

## 5c. Pro players batch, brand logos and the brand rail (session 3)

**Pro players** (`padel_pro_players_catalogue.pdf`):

- Data lives in `src/data/seed/pro-players.ts`:
  - `proRackets`: 13 rackets that weren't on the site yet, plus the Hack 04 2026 update.
  - The player → racket map, in the catalogue's order.
- The players are stored in a new column, `products.pro_players` (migration `drizzle/0001_*.sql`).
- **Where they show:**
  - A "Played by …" pill on racket pages.
  - A player line on racket cards.
  - A new **`/pros`** page (men's and women's tours), added to the menu, footer and sitemap.
- Eight players use rackets that were already on the site, so those got their player added.
- New brands: Lok, Kuikma and Drop Shot (Tactical exists, but has no racket yet).
- **Not added:**
  - **Lucas Bergamini's Tactical El Jefe:** the two sources disagree on shape, balance and core, and there are no reliable photos.
  - **Kuikma Coki Nieto:** added, but with no photos it has a placeholder model.
- **Data quality:**
  - Specs from retailers (padelkiwi, ipontennis, padelmarket, padelgids, decathlon) stay "Specs unverified" and say where they came from.
  - Missing values are stated in the description: Electra and Fenix weight, and the Arrow Hit's shape, weight and face.
  - The Arrow Hit's shape filter falls back to teardrop because the source doesn't list one.
- **3D:**
  - Same pipeline as before.
  - The cutout tool gained `--close <px>`, which fills notches in pale frames on pale backgrounds (used for the Drop Shot Axion and Head Extreme Motion).
  - The Metalbone HRD+ gets the Metalbone side weight screws (override list in `scripts/build-catalogue-designs.ts`).
  - The Wilson Defy's source photo is only 400 px, so its print is softer.

**Brand tiles:**

- Each tile shows the brand's logo (white), not a racket photo.
  - `scripts/build-brand-logos.ts` turns the official files in `assets/brand-logos/` into `public/images/brands/<slug>.png`.
  - Sources: the brands' own sites; Commons for adidas and Wilson; Head's logo is inline SVG from head.com.
- Lok, Kuikma and Drop Shot have no reachable logo, so they show the brand name.
- **Horizontal scrolling on PC:**
  - Arrow buttons appear for mouse users when the rail can scroll, and dragging with the mouse scrolls it. A drag never selects a tile; a normal click still does.
  - Touch and trackpad work as before.

**Fixes:**

- `--ease-spring` no longer overshoots, so impeccable's detector reports zero findings.
- Components read `proPlayers` defensively, because cached data from older builds lacks it. Clear `.next/cache/fetch-cache` after a schema change.

---

## 5d. Researched specs and "What reviewers say" (session 4, 7 Oct 2026)

All 62 rackets were researched against published reviews and retailer listings. The sources were Padelful, PadelSpeak, Padel Verdict, padel.fyi, Padelshop's measured hardness and swingweight, retailer staff tests and Decathlon buyer reviews.

- **Data:** `src/data/seed/racket-research.ts`, one entry per slug.
  - `fill`: fills only empty spec fields, mostly frame material, balance point, thickness, hardness and finish.
  - `set`: replaces a finish name with the face material, e.g. Nox "Dual Spin" becomes "Carbon 12K Alum Xtrem, Dual Spin finish".
  - `roundup`: summary, liked, watch-outs, who it suits, facts, `ourRead` and linked sources.
  - Wired in through `withResearch()` in `rackets.ts`. The spec source note says which fields came from retailers ("not checked against the brand").
  - Where sources disagreed (shape, face carbon grade, balance), nothing was changed and the brand listing was kept.
- **Schema:** `products.roundup` JSON column (migration `drizzle/0002_familiar_the_twelve.sql`). The `ReviewRoundup` type is in `domain/types.ts` and mapped in `repositories/rackets.ts`.
- **UI:** `RoundupBlock` in `RacketDetailSections.tsx`.
  - It renders a "What reviewers say" section (`#reviews`) after "Who is this racket for?".
  - The hero has a "What reviewers say" button.
  - The "Paladex's read" box is labelled as our opinion drawn from the sources, not a play test.
  - Status `early` is used for the 2027 Bullpadel line, the EA10 Hybrid and the Arrow Hit Pro EDT (no independent review yet). Revisit these when reviews appear.
  - "Our take" (sample editorial) now only renders when a racket has one.
- **Remaining spec gaps:** mostly the balance point in mm and hardness. They stay "—" rather than guessed.
- **Admin:** the admin form does not edit `roundup` yet. Edit the research file and reseed.

## 6. Remaining work, in order

### 6.1 Visual QA of the remaining pages in dark

- Public pages:
  - Finder **results** screen.
  - Guides, including the `.prose-court` styles and their 3D embeds.
  - Collections, legal, about, contact, 404 and the "link not active yet" page.
- Admin pages: they were built under the earlier light theme. They use the same tokens, so they should read fine, but check contrast (e.g. `bg-court-tint text-court-deep` notices).
- The White studio switch on the racket page (light sweep with dark UI around it).
- Tablet width (768 px).

### 6.2 Admin click-through test

- Wrong password and the rate limit.
- Create a draft, preview it, publish it, and check it appears on `/rackets` under its brand.
- Edit specs and check the public page updates.
- Upload a GLB (try a renamed `.txt` too: it must be refused).
- Delete the racket.
- Retailer CRUD and its effect on `/go`.
- Sign out.

### 6.3 Missing script and tests

- `scripts/optimize-model.ts` is referenced by `npm run models:optimize` but **doesn't exist**. It should take a user-supplied GLB and run gltf-transform `weld → dedup → prune → resample → meshopt → textureCompress (webp, max 2048)`, writing the full version plus a `.preview.glb` LOD (simplify to about 35%, textures at 1024).
- `npm run test` points to `src/**/*.test.ts`, but there are no tests. Add at least `src/lib/recommend/engine.test.ts` and `src/lib/catalog/filters.test.ts` (round-trip parse/serialize) using `node:test`.

### 6.4 Docs (deliverables B–F from the brief)

- `README.md`: overview, setup, environment variables, adding rackets, models, hotspots and offers, the admin, deploying.
- `docs/3D-PIPELINE.md`:
  - The photo → trace → design file → `models:build` workflow.
  - Orientation convention: metres, +Y from butt to tip, +Z is the front face.
  - Part names: `part_face_front`, etc. Grep `generate-models.ts` for `part_`.
  - LODs and compression, `ASSET_ORIGINS`, and how to bring in official models later.
- `docs/ARCHITECTURE.md`: folder map (section 8), data model, caching (`unstable_cache` tag `catalog`), honesty rules.
- `docs/DEPLOYMENT.md`:
  - Recommended setup: **Vercel (or Netlify) + Turso (database) + Cloudflare R2 (models and images)**.
  - Environment variables, `ALLOW_INDEXING`, the custom domain.
  - Note: serverless request bodies are capped at about 4.5 MB on Vercel, so upload big models to R2 directly and paste the URL into the admin.
- `docs/SECURITY.md`: the CSP trade-off (`'unsafe-inline'` because pages are static), admin auth, rate limits (in-memory: move them to Upstash when there are several instances), upload checks, affiliate allow-list, no personal data in analytics.
- Final summary to the user covering deliverables A–F: project, structure, setup, content/data instructions, deployment, roadmap.

### 6.5 Design finish (impeccable)

1. Run `impeccable detect --json` on `src/` and fix what it finds. The launcher is in the impeccable skill folder (`scripts/impeccable`; `impeccable.cmd` on Windows).
2. Run the finish review on the homepage, racket page, rackets browser and mobile drawer.
3. Write **`DESIGN.md`** from the Black studio tokens (section 10), with provenance for the photos.

### 6.6 When you send new racket photos

For each racket (slug like `brand-model-year`):

1. Put the photos in `assets/reference/<slug>/`: a front photo with a transparent or plain background, plus angled photos.
2. Run `npm run models:trace -- --slug <slug> --image assets/reference/<slug>/<front>.webp`. This writes `src/data/designs/<slug>.trace.json`.
3. Copy `src/data/designs/adidas-metalbone-3-4.ts` to `<slug>.ts`. Adjust thickness, colours, face bottom, bevel, screws and `sweetSpotV`, then register it in `src/data/designs/index.ts`.
4. Run `npm run models:build`. This writes `public/models/platform/<slug>.glb` and `.preview.glb`, and updates `models.generated.json`.
5. Copy the display photos to `public/images/rackets/<slug>/` (front, angle, throat as WebP) and add them to the racket's `images` in `src/data/seed/rackets.ts`. Add the racket and brand there too if they're new.
6. Run `npm run db:seed -- --force`, then check `/rackets/<slug>`.
7. Once the admin is finished, steps 5–6 can be done in the admin instead.

**Faster path for a brand catalogue (used for the 34 rackets added on 6 Oct 2026):**

1. Add the rackets to `src/data/seed/brand-catalogue.ts` (specs as the brand lists them, image URLs, product page). Reuse an existing slug to update a racket that is already on the site.
2. `npx tsx scripts/import-brand-catalogue.ts`: downloads the photos to `assets/reference/<slug>/a.*, b.*, …`.
3. Pick the straight-on front view for each racket, then run `npx tsx scripts/cutout-racket-photo.ts --in <photo> --out assets/reference/<slug>/front.png`.
   - Add `--symmetric` to drop wrist straps and cast shadows.
   - Lower `--tolerance` (e.g. 7) for white rackets.
4. `npm run models:trace -- --slug <slug> --image assets/reference/<slug>/front.png`.
   - If the neck (the green line in `.tmp/trace-<slug>.png`) is wrong, re-run with `--neck-y <px>` (about 137 mm from the butt).
5. `npx tsx scripts/build-catalogue-designs.ts`: writes `src/data/designs/catalogue.generated.ts` (colours sampled from the photo, face bottom 4 mm above the throat, sweet spot by shape).
6. Publish the photos as WebP in `public/images/rackets/<slug>/` and list them in `src/data/seed/catalogue-photos.generated.json` (the front is the cutout).
7. `npm run models:build`, then `npm run db:seed -- --force`.
   - Clear `.next/dev/cache/fetch-cache` or restart the dev server so lists refresh.

**How the catalogue rackets are shown:**

- `brand-catalogue-convert.ts` maps the brand terms to the site's filters. For example, Bullpadel's "Geometric" counts as diamond, a balance given in cm becomes low…high, and "Feel" becomes hardness.
- It derives the sample scores and "who is it for" lines from those specs with fixed rules.
- Prices are left empty ("Not listed yet"), so these rackets have no demo offers.
- There are no editorial reviews for them.
- Specs with full brand data are marked "verified" and link to the official product page.
- Photos are recorded as "Brand product photo (<site>), from the owner's catalogue" with licence status *pending*. **Get the brands' permission (or use retailer/affiliate feed images) before a public launch.**
- **Not traced:**
  - **Wilson Bela Pro V3:** the only photo is at an angle, so it keeps the placeholder model (the photo is shown).
  - **Babolat Technical Viper Soft 3.0 and Technical Veron 3.0:** no photos, so they have placeholder models.
- **Head's holes:** Head photographs its holes as dark dots, so Head models have printed holes, not cut-through ones.

---

## 7. Known issues (not fixed yet)

1. Mobile Lighthouse LCP is still about 4 s (simulated slow 4G with a 4× slower CPU). The hero photo and the 3D engine download are what remain. Desktop is about 0.8 s.
2. Console warning: `THREE.Clock` is deprecated, from R3F internals (harmless).
3. `npm run models:optimize` has no script, and `npm run test` has no tests (6.3).
4. The rate limiter is in memory (one server). Use Redis/Upstash for several instances.
5. Parked compare code (`src/components/compare/*`) still triggers a few lint warnings. Delete the folder if you decide compare is gone for good.
6. Lint shows 30 warnings, none blocking. Most are React Compiler hints about state set inside effects.
7. `scene/pmrem-warmup.ts` uses three.js private fields (`PMREMGenerator._setSize`, `_allocateTargets`, `_ggxMaterial`). It is guarded and falls back to normal behaviour if they change. After a three.js upgrade, re-run `node .tmp/shaders.mjs http://localhost:3100/` and check the "total blocking" figure stays under ~100 ms.

---

## 8. File map

```
src/
  app/
    layout.tsx                 root: fonts (Google Sans Flex), metadata, noindex until ALLOW_INDEXING
    globals.css                Black studio tokens (@theme) + components (.btn .chip .badge .field .label .display .num .card-sky .stage-sky .stage-light) + reveal/dialog/drawer motion
    (site)/                    public site (header, footer)
      page.tsx                 homepage
      rackets/ rackets/[slug]/ (page + opengraph-image)
      showroom/ finder/
      brands/[slug]/           same browser as /rackets, brand preselected (SEO address)
      collections/[slug]/ guides/ guides/[slug]/ legal/[slug]/
      about/ contact/ link-unavailable/ error.tsx loading.tsx not-found.tsx
    admin/
      layout.tsx  actions.ts
      (auth)/login/page.tsx
      (panel)/ page.tsx rackets/ rackets/[id]/ rackets/[id]/preview/ brands/ retailers/ insights/
    api/search-index/  api/events/  api/admin/upload/
    go/[offerId]/route.ts      affiliate redirect
    uploads/[...path]/route.ts serves local admin uploads from data/uploads
    sitemap.ts robots.ts manifest.ts icon.svg opengraph-image.tsx not-found.tsx
  proxy.ts                     /admin guard (Next 16 "proxy", successor of middleware)
  components/
    three/                     Racket3DViewer, SimpleControls, Racket3DControls (compact), Hotspots, Overlay, Annotations, LoadingState, Fallback, Preview, ViewerBridge, model-loader, quality, views, webgl, types
    three/scene/               ViewerScene (Canvas), Stage (studio), RacketObject, CameraRig, Overlays3D, Projector
    racket/                    RacketDetail, RacketDetailSections, RacketCard, RacketPoster, RacketIllustration, SpecTable, ShowOnModel, ScoreBar, ProvenanceBadge, WhereToBuy, TrackView
    catalog/                   RacketsBrowser (server), CatalogExplorer, BrandTiles, FilterPanel
    home/ (HomeHero, CourtZones)  finder/  showroom/  search/  layout/ (SiteHeader, SiteFooter, Logo)
    ui/                        Icon, Popover, Dialog (center/sheet/full/drawer), Reveal
    admin/                     RacketForm, fields, EntityForms, AdminNav, LoginForm
    compare/                   PARKED, not used
  domain/types.ts vocab.ts     enums, interfaces, plain-language explanations
  lib/                         racket-geometry, model-defaults, catalog/(filters, brand-tiles), recommend/engine, collections, seo, scores, format, urls, analytics, cn
  server/
    db/ (schema, 18 tables)   repositories/ (rackets, brands, affiliate, events, popularity, admin)
    auth/   storage/   validation/admin.ts (zod)   rate-limit.ts
  data/seed/ (brands 9, rackets 16, retailers 3 demo)  data/designs/  data/models.generated.json
  content/guides/index.ts (7 guides)  content/legal.ts (5 legal drafts)
  config/site.ts               name, tagline2, nav (with notes), footer, contact email (placeholder)
scripts/  setup-env, migrate, seed, reset-db, hash-admin-password, copy-decoders, trace-racket-photo, generate-models, preview-geometry, lib/
assets/reference/adidas-metalbone-3-4/   your original photos
public/models/platform/ public/models/placeholders/ public/images/rackets/ public/decoders/(generated)
.tmp/shoot.mjs               headless screenshot tool (section 3)
PRODUCT.md  HANDOFF.md  .impeccable/ (design contract + review screenshots)  .env.example  .env.local (secrets)
```

**Catalogue content:**

- 62 rackets from 12 brands (13 brand records): the original 16 (specs from public listings, unverified) plus 34 from your brand catalogue PDF (brand-listed specs, verified, with photos). 35 have platform 3D models traced from real photos.
- The **adidas Metalbone 3.4** has a platform model built from your photos.
- 14 rackets have labelled placeholder models.
- The adidas Drive Black has no model on purpose.
- Retailers are 3 demo stores, with `AFFILIATE_URL_HERE` links.

---

## 9. Next.js 16 specifics (to avoid wasted time)

- `params` and `searchParams` are **Promises**: `const { slug } = await params`.
- `src/proxy.ts` replaces middleware. It runs on Node.js by default, so `node:crypto` is fine there.
- Cache invalidation: in server actions use `updateTag(tag)`; elsewhere use `revalidateTag(tag, "max")`, which takes two arguments.
- The project uses the classic caching model (`unstable_cache`, tag `catalog`), **not** `cacheComponents`.
- `next lint` is gone. Use `npm run lint` (ESLint flat config).
- Server action bodies are capped at 1 MB by default; uploads therefore use the `/api/admin/upload` route instead. With a proxy, bodies are buffered up to 10 MB (`experimental.proxyClientMaxBodySize`); the upload route is outside the proxy matcher on purpose.
- The docs bundled with the installed version are in `node_modules/next/dist/docs/`. Read them before using an unfamiliar API.

---

## 10. Design system quick reference ("Black studio")

- **Colours** (`src/app/globals.css`, `@theme`):
  - ground `#0a0b0d`, surface `#131519`, surface-2 `#1a1d22`.
  - ink `#eceef1`, ink-2 `#a9aeb8`, ink-3 `#878d98`.
  - **court `#eceef1` = the action colour** (white pills); `on-court` `#0a0b0d` is the text on it. court-tint `#24282f`, court-mist `#3b4049`.
  - **ball `#d9f04a`: only the sweet spot and match scores.**
  - warn `#f2c26b`, ok `#5fd6a4`, danger `#ff7b6e`.
- **Type:** Google Sans Flex (variable). `.display` is upright and wide (wdth 112, weight 620); also `.title`, `.label` and `.num` (tabular figures).
- **Surfaces:**
  - `.stage-sky`: the black studio, with a soft spotlight.
  - `.stage-light`: the white studio.
  - `.card-sky`: the mini studio behind cards and tiles.
  - Cards have a 16–20 px radius; buttons and chips are pills.
- **Motion:** `[data-reveal]` rises once with a slight perspective tilt; dialogs pop in; the drawer slides from the right. Everything respects reduced motion.
- **3D studio:** `PALETTES` in `scene/Stage.tsx` (dark and light).
- **Icons:** a custom 24 px set in `components/ui/Icon.tsx`.
- **Contract:** `.impeccable/surfaces/src-app-site-page-tsx.md` and `PRODUCT.md`.

---

## 11. Environment variables (`.env.example`)

| Variable | Purpose / value |
|---|---|
| `SITE_URL` | public URL; used for canonical URLs, Open Graph and the sitemap |
| `ALLOW_INDEXING` | `false` until launch; robots blocks everything |
| `DATABASE_URL` / `DATABASE_AUTH_TOKEN` | `file:./data/paladex.db` locally, or `libsql://…turso.io` |
| `ADMIN_PASSWORD_HASH` | made by `npm run admin:hash` |
| `ADMIN_SESSION_SECRET` | 32+ characters |
| `ASSET_STORAGE` | `local` or `s3` |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION`, `S3_PUBLIC_BASE_URL` | R2/S3 storage |
| `ALLOW_LOCAL_UPLOADS` | only for a server with a persistent disk |
| `ASSET_ORIGINS` | external hosts allowed to serve models and images (feeds the CSP and next/image) |
| `NEXT_PUBLIC_ANALYTICS_PROVIDER` | `none`, `console`, `first-party` or `plausible`, plus the Plausible variables |
