# Deployment

## Recommended production setup

| Part | Service | Why |
|---|---|---|
| App | Vercel or Netlify (Next.js runtime) | Server rendering, image optimisation and the API routes, with no server to manage |
| Database | Turso (hosted libSQL) | The app already speaks libSQL; local development keeps the plain SQLite file |
| Models and images | Cloudflare R2 (S3-compatible) behind a custom domain | Large GLB files stay out of the app bundle and serverless request limits; R2 charges nothing for downloads |
| Rate limiting (later) | Upstash Redis | The built-in limiter is in memory, so it only covers one server instance |

A single server with a persistent disk (a VPS, Fly.io, Railway) also works. Keep the SQLite file and set `ALLOW_LOCAL_UPLOADS=true`.

## Step by step

1. **Database.** Create a Turso database. Run the migrations and the seed against it from your machine:
   ```bash
   DATABASE_URL=libsql://<db>-<org>.turso.io DATABASE_AUTH_TOKEN=<token> npm run db:migrate
   DATABASE_URL=libsql://<db>-<org>.turso.io DATABASE_AUTH_TOKEN=<token> npm run db:seed
   ```
   Seed once only: after that, the admin is the source of truth. `db:seed -- --force` would wipe admin edits.
2. **Storage.** Create an R2 bucket and give it a public custom domain (e.g. `assets.paladex.example`). Create an API token with write access to that bucket.
3. **App.** Import the repository into Vercel or Netlify. The build command is `npm run build` (Netlify: see `netlify.toml`). Set the environment variables below.
4. **Domain.** Add the custom domain, then set `NEXT_PUBLIC_SITE_URL` to it and redeploy, so canonical links, Open Graph images and the sitemap use it.
5. **Check.** Open `/api/health`, which should return `{"ok":true,"rackets":<n>}`. Then sign in at `/admin`, save a racket and check the public page updates.
6. **Launch.** When the catalogue has real data, real affiliate links and cleared photo licences, set `NEXT_PUBLIC_ALLOW_INDEXING=true` and redeploy.

## Environment variables

| Variable | Production value |
|---|---|
| `NEXT_PUBLIC_SITE_URL` | `https://<your domain>` |
| `NEXT_PUBLIC_ALLOW_INDEXING` | `false` until launch, then `true` |
| `DATABASE_URL`, `DATABASE_AUTH_TOKEN` | The Turso URL and token |
| `ADMIN_PASSWORD_HASH` | From `npm run admin:hash -- "<a long, unique password>"`. Never reuse the local one |
| `ADMIN_SESSION_SECRET` | 32+ random characters: `node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"` |
| `ASSET_STORAGE` | `s3` |
| `S3_ENDPOINT` | `https://<account id>.r2.cloudflarestorage.com` |
| `S3_REGION` | `auto` |
| `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | The bucket and its token |
| `S3_PUBLIC_BASE_URL` | `https://assets.<your domain>` |
| `ASSET_ORIGINS` | The same origin, plus any other host that serves models or images |
| `NEXT_PUBLIC_ANALYTICS_PROVIDER` | `first-party` (or `plausible` with its two variables) |

Variables starting with `NEXT_PUBLIC_` are built into the browser code, so redeploy after changing them.

## Large models and upload limits

Serverless platforms cap request bodies: about 4.5 MB on Vercel and about 6 MB on Netlify Functions. The admin accepts models up to 25 MB, but on those platforms large uploads fail before they reach the app. For big models:

1. Compress them first with `npm run models:optimize` (racket models usually end up well under 1 MB).
2. If a file is still too large, upload it to the bucket directly (the R2 dashboard or `rclone`), then paste its URL into the admin. The URL's host must be in `ASSET_ORIGINS`.

## The current Netlify preview

https://paladex-preview.netlify.app requires a Netlify login (team protection). It is a preview, not production:

- The build (`netlify.toml`) runs the migrations and the seed into `data/paladex.db`. `next.config.ts` bundles that file with the server code.
- On the server, `src/server/db/connection.ts` copies the bundled file to the temp folder on first use, because the bundle is read-only. Clicks and events written there last only as long as that server instance.
- Admin secrets are deliberately not set, so `/admin` stays locked. Edits wouldn't persist there anyway.
- Runtime variables (e.g. `NEXT_PUBLIC_SITE_URL`, and `DATABASE_URL`/`DATABASE_TEMPLATE` if the defaults need overriding) are set in the Netlify UI.

**Deploying the preview:** the Netlify uploader ignores `.gitignore`, so deploy from a clean copy of the project. Leave out:

- `.env.local` (it holds the admin password)
- `node_modules`, `.next`, `.tmp`
- `data/*.db` and `data/uploads`
- `assets/reference`
- `promo/` and anything else not needed by the site

Then deploy that folder with the Netlify CLI (`netlify deploy --prod --dir .` from the clean copy) or the Netlify MCP `deploy-site` tool. Check `/api/health` afterwards. If pages show "error", the database is the first thing to check.

## Moving to Postgres later

Drizzle supports Postgres. Switching means porting `src/server/db/schema.ts` to `pg-core` (the JSON text columns become `jsonb`), regenerating the migrations and swapping the client in `connection.ts`. The repositories use Drizzle's query builder, so most of them carry over unchanged.
