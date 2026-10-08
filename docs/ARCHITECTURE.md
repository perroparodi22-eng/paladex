# Architecture

Paladex is a single Next.js 16 app (App Router). Public pages are rendered on the server and cached; the catalogue browser, the Finder and the 3D viewer run in the browser. Data lives in SQLite/libSQL through Drizzle ORM. A password-protected admin edits it.

## Folder map

```
src/
  app/
    layout.tsx               root: fonts, metadata, noindex until NEXT_PUBLIC_ALLOW_INDEXING
    globals.css              Black studio tokens (@theme) and shared component classes
    (site)/                  public site, inside the header/footer layout
      page.tsx               homepage
      rackets/ rackets/[slug]/   browser and racket pages (plus opengraph-image)
      brands/[slug]/         the rackets browser with one brand selected (SEO address)
      showroom/ finder/ pros/ collections/[slug]/ guides/ guides/[slug]/ legal/[slug]/
      about/ contact/ link-unavailable/
      [...missing]/          sends unknown URLs to the site 404 (not-found.tsx)
    admin/                   admin panel: (auth)/login, (panel)/*, actions.ts (server actions)
    api/search-index/        racket list for the header search (cached for an hour)
    api/events/              first-party analytics endpoint
    api/admin/upload/        model and image uploads (outside the proxy on purpose)
    go/[offerId]/route.ts    affiliate redirect
    uploads/[...path]/       serves local admin uploads from data/uploads
    sitemap.ts robots.ts manifest.ts opengraph-image.tsx not-found.tsx
  proxy.ts                   /admin guard (Next 16's successor to middleware)
  components/
    three/                   Racket3DViewer and its controls, model loader, quality tiers
    three/scene/             ViewerScene (Canvas), Stage (studio), RacketObject, CameraRig, overlays
    racket/                  racket page sections, cards, spec table, provenance badge, where to buy
    catalog/                 RacketsBrowser (server) → CatalogExplorer (client), brand tiles, filters
    home/ finder/ showroom/ search/ layout/ ui/ admin/
    compare/                 parked, not used (compare was removed from the site)
  domain/                    types.ts (enums and interfaces), vocab.ts (plain-language explanations)
  lib/                       pure logic: catalog filters, recommend engine, racket geometry,
                             model defaults, collections, SEO, formatting, URL safety, analytics
  server/
    db/                      schema and connection (migrations run from scripts/migrate.ts)
    repositories/            rackets, brands, affiliate, events, popularity, admin
    auth/                    password hashing, session tokens, requireAdmin guard
    storage/                 upload checks and storage (local disk or S3/R2)
    validation/admin.ts      zod schemas for every admin write
    rate-limit.ts            in-memory limiter
  data/
    seed/                    brands, rackets, brand catalogue, pro players, research, retailers
    designs/                 platform model designs and traces
    models.generated.json    model sizes, bounds and versions (written by models:build)
  content/                   guides and legal drafts
  config/site.ts             name, tagline, navigation, footer, contact
  test/                      test fixtures
scripts/                     setup, migrate, seed, models (trace, build, optimize), photo tools
drizzle/                     SQL migrations
public/models/               platform/, placeholders/, official/ GLB files
public/images/               racket photos and brand logos
assets/                      reference photos and brand logo sources (not served)
```

## Data model

18 tables, defined in `src/server/db/schema.ts`:

- **Catalogue:** `brands`, `products` (one row per racket, with status, levels, colours, indicative price, pro players and the review round-up as JSON), `racket_specs` (manufacturer specs, kept apart from our scores, with a verification state and source), `platform_evaluations` (Paladex's sample scores), `playing_styles` and `product_playing_styles`, `product_categories`, `product_images`.
- **3D:** `model_assets` (URL, light version, poster, status, licence and provenance), `model_hotspots`, `model_annotations`, `model_overlays`.
- **Commerce:** `retailers` (with allowed affiliate domains), `offers` (one per retailer per racket), `affiliate_clicks`.
- **Content and analytics:** `editorial_reviews`, `user_reviews` (not used yet), `analytics_events`.

Money is stored in integer cents. Migrations are in `drizzle/`. After changing the schema, run `npm run db:generate`, then `npm run db:migrate`.

## How a page gets its data

1. Server components call repository functions in `src/server/repositories/`.
2. Catalogue reads are wrapped in `unstable_cache` with the tag `catalog` and a one-hour revalidation: `listRacketSummaries`, `getRacket(slug)` (also tagged `racket:<slug>`) and `listBrands`. Popularity (views and clicks over the last 30 days) has its own `popularity` tag.
3. Racket, brand, guide, collection and legal pages are pre-rendered with `generateStaticParams`.
4. Admin writes call `updateTag("catalog")` and `revalidatePath("/", "layout")`, so the public site shows a change on the next request.

The project uses this classic caching model, not `cacheComponents`. After a schema change, clear `.next/cache/fetch-cache` (or `.next/dev/cache` in development), because cached objects from older builds can lack new fields.

## Client-side features

- **Catalogue browser:** the server sends every racket summary once; `CatalogExplorer` filters, searches and sorts them in the browser with the pure functions in `src/lib/catalog/filters.ts`. The filter state round-trips through the URL, so every view can be shared and the first render is crawlable.
- **Finder:** `src/lib/recommend/engine.ts` scores each racket against the answers with fixed, documented weights and explains each match (reasons, strengths, drawbacks, how it differs from your current racket). The answers live in the URL.
- **3D viewer:** React Three Fiber with camera-controls. It picks a quality tier for the device, loads the light model first, compiles shaders in the background, and pauses rendering while the page scrolls or the viewer is off screen.
- **Search:** the header search loads `/api/search-index` on first use.

Both `filters.ts` and `engine.ts` have unit tests (`npm test`).

## Affiliate flow

Buttons link to `/go/<offerId>`. The route logs the click (racket, retailer and source page; no personal data) and then:

- redirects (302) to the affiliate URL if it is https and on one of the retailer's allowed domains, or
- sends the visitor to `/link-unavailable` with the reason (placeholder link, unsafe link, inactive offer, missing offer).

The admin refuses to save a live link that is off the retailer's allowed domains, and offers keep their ids across edits, so `/go` links on cached pages stay valid.

## Analytics

`NEXT_PUBLIC_ANALYTICS_PROVIDER` picks `none`, `console`, `first-party` or `plausible`. First-party events (racket viewed, viewer opened, model loaded, Finder completed, affiliate clicked…) are posted to `/api/events` and stored in `analytics_events`, without cookies, IP addresses or user agents. The admin's "Clicks and events" page summarises the last 30 days.

## Honesty rules (enforced in code)

- Specs carry a verification state (`verified`, `unverified`, `placeholder`) and a source; the page shows it.
- Platform scores are always labelled as Paladex's sample evaluation, never as manufacturer data.
- Demo offers and prices are labelled "demo" and never go into structured data.
- Placeholder affiliate links never pretend to work.
- Every 3D model shows its provenance; a placeholder model can't pass for the real racket.
- Hotspots, notes and overlays each show their basis (manufacturer data, platform evaluation or illustration).
- There are no invented reviews or ratings. "What reviewers say" summarises published reviews and links to them.
