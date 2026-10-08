# Paladex

A 3D-first padel racket database. Pick a brand, turn any racket in 3D, read its specs in plain language, get matched to a racket by the Finder, and click through to retailers (affiliate links).

Paladex is a working name; change it in `src/config/site.ts`.

- **Stack:** Next.js 16 (App Router, Turbopack), React 19, TypeScript, Tailwind CSS v4, three.js through React Three Fiber, Drizzle ORM over libSQL/SQLite.
- **Design:** "Black studio", a dark showroom where the racket is the only thing that shines. See `DESIGN.md` once it exists, and `PRODUCT.md` for who the product is for.
- **More docs:** [3D pipeline](docs/3D-PIPELINE.md) · [Architecture](docs/ARCHITECTURE.md) · [Deployment](docs/DEPLOYMENT.md) · [Security](docs/SECURITY.md)

> **Next.js 16 differs from older versions.** `params` and `searchParams` are Promises, `src/proxy.ts` replaces middleware, and `next lint` is gone. The docs for the installed version are in `node_modules/next/dist/docs/`. See `AGENTS.md`.

## Setup

Node 20.9 or newer (22 or 24 recommended).

```bash
npm install      # also copies the Draco/Basis decoders to public/decoders
npm run setup    # first time: creates .env.local (with admin secrets), migrates and seeds the database
npm run dev      # http://localhost:3000
```

`npm run setup` writes the local admin password as a comment at the top of `.env.local`. Never commit that file.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` / `build` / `start` | Develop, build, serve the production build |
| `npm run typecheck` / `lint` / `test` | Type check, ESLint (flat config), unit tests (`node:test` through tsx) |
| `npm run db:migrate` / `db:seed` | Apply migrations / load the catalogue. `db:seed -- --force` wipes and reseeds the catalogue tables |
| `npm run db:reset` | Delete the local database and run setup again |
| `npm run db:generate` | Generate a migration after editing `src/server/db/schema.ts` |
| `npm run db:studio` | Browse the database |
| `npm run admin:hash -- "password"` | Hash a new admin password for `ADMIN_PASSWORD_HASH` |
| `npm run models:trace` / `models:build` | Trace a racket photo / build every platform and placeholder model |
| `npm run models:optimize -- --in x.glb --slug <slug>` | Compress a supplied (official or licensed) model and make its light version |

## Environment variables

Copy `.env.example` to `.env.local` (`npm run setup` does it for you). The ones that matter:

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_SITE_URL` | Public URL, used for canonical links, Open Graph and the sitemap |
| `NEXT_PUBLIC_ALLOW_INDEXING` | Keep `false` until launch: robots then block everything |
| `DATABASE_URL`, `DATABASE_AUTH_TOKEN` | `file:./data/paladex.db` locally, or `libsql://<db>.turso.io` plus a token |
| `DATABASE_TEMPLATE` | Serverless only: the bundled database file to copy into the temp folder |
| `ADMIN_PASSWORD_HASH`, `ADMIN_SESSION_SECRET` | Admin sign-in. Without both, `/admin` stays locked |
| `ASSET_STORAGE` | `local` (development) or `s3` (any S3-compatible bucket, e.g. Cloudflare R2) |
| `S3_ENDPOINT`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_PUBLIC_BASE_URL` | Bucket for admin uploads |
| `ALLOW_LOCAL_UPLOADS` | `true` only on a production server with a persistent disk |
| `ASSET_ORIGINS` | Extra origins allowed to serve models and images (feeds the CSP and `next/image`) |
| `NEXT_PUBLIC_ANALYTICS_PROVIDER` | `none`, `console`, `first-party` (stored in the database, no cookies or IPs) or `plausible` |
| `NEXT_PUBLIC_PLAUSIBLE_DOMAIN`, `NEXT_PUBLIC_ANALYTICS_SCRIPT_ORIGIN` | Plausible only |

## Content and data

The catalogue is seeded from TypeScript files and can then be edited in the admin.

- **Rackets and brands:** `src/data/seed/brands.ts`, `rackets.ts` (hand-written entries), `brand-catalogue.ts` (rackets from brand catalogues), `pro-players.ts` (who plays what) and `racket-research.ts` (spec gaps filled from published reviews, and the "What reviewers say" summaries).
- **Retailers:** `src/data/seed/retailers.ts` (three demo stores).
- **Guides and legal pages:** `src/content/guides/index.ts` and `src/content/legal.ts`.
- After editing seed files, run `npm run db:seed -- --force`. It wipes the catalogue tables, including anything edited in the admin. Analytics events and affiliate clicks are kept.

**Honesty rules.** These are built in; keep them when you add content:

- Specs stay "unverified" until checked against the brand.
- Platform scores are labelled as Paladex's own sample evaluations, never as manufacturer data.
- Demo prices are labelled "demo" and kept out of structured data.
- Placeholder affiliate links (`AFFILIATE_URL_HERE`) lead to a "link not active yet" page, never to a dead end.
- Every 3D model says where it came from: official, licensed, platform-created (built by us from photos), placeholder, or none.
- No invented reviews or star ratings.

### Adding a racket with a 3D model

The short version, for one racket (the full workflow, including batch imports from a brand catalogue, is in [docs/3D-PIPELINE.md](docs/3D-PIPELINE.md)):

1. Put the photos in `assets/reference/<slug>/`: a straight-on front view, plus angled views.
2. Run `npm run models:trace -- --slug <slug> --image assets/reference/<slug>/front.png`.
3. Write the design file `src/data/designs/<slug>.ts`, starting from `adidas-metalbone-3-4.ts`, and register it in `src/data/designs/index.ts`.
4. Run `npm run models:build`.
5. Add the racket, its photos (`public/images/rackets/<slug>/`) and, if new, its brand to the seed files.
6. Run `npm run db:seed -- --force` and open `/rackets/<slug>`.

Got an official or licensed model instead? Run `npm run models:optimize`, then paste the two URLs it prints into the admin (3D model section). Set "Where the model comes from" to match the licence.

### Hotspots and offers

- **Hotspots** (the points on the model that explain a spec) are generated from the specs when a racket is seeded or created. Edit them in the admin under "Hotspots", or press "Regenerate from specs". Positions are fractions of the model's bounding box: u across, v butt → tip, w back → front.
- **Offers:** one per retailer per racket, edited on the racket page in the admin. Leave the affiliate link empty or `AFFILIATE_URL_HERE` until you have a real one. A real link must be on one of the retailer's allowed domains, or the save is refused.

## Admin

Open `/admin` and sign in with the password from `.env.local`.

- Rackets: create, preview drafts, publish, edit specs, scores, colours, 3D model, hotspots, photos and offers. Upload a GLB (up to 25 MB) or paste a model URL.
- Brands and retailers (including each retailer's allowed affiliate domains).
- Clicks and events: affiliate clicks and first-party analytics for the last 30 days.

Five wrong passwords from one address lock sign-in for 15 minutes. Sessions last 12 hours.

## Deploying

The recommended setup is Vercel or Netlify for the app, Turso for the database and Cloudflare R2 for uploads. The current preview runs on Netlify with the SQLite file bundled into the build. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Before a public launch

- Replace the demo retailers and `AFFILIATE_URL_HERE` links with real affiliate links.
- Get permission for brand and shop photos (they are marked "licence pending"), or switch to affiliate-feed images.
- Have the legal drafts in `src/content/legal.ts` reviewed, and set the real contact address in `src/config/site.ts`.
- Set `NEXT_PUBLIC_ALLOW_INDEXING=true`.
