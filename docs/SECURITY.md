# Security

Paladex has one privileged user (the admin) and no visitor accounts. The main risks are someone taking over the admin, a hostile upload, an affiliate link being turned into an open redirect, and collecting more data about visitors than we need. This page lists what is in place and the trade-offs that remain.

## Headers and Content-Security-Policy

Set for every response in `next.config.ts`:

- **Content-Security-Policy** (production only):
  - `default-src 'self'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'`, `upgrade-insecure-requests`.
  - `connect-src` adds the hosts in `ASSET_ORIGINS` (model downloads) and the analytics origin.
  - `img-src` allows any https image, for retailer and brand images.
- **Strict-Transport-Security**: two years, with subdomains (production only). Add `preload` only when you deliberately submit the domain to hstspreload.org.
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Cross-Origin-Opener-Policy: same-origin`.
- A Permissions-Policy that turns off camera, microphone, geolocation, payment, USB and topics, and keeps fullscreen and XR for this origin.
- `/admin/*`: `no-store` and `noindex`. `/go/*`: `noindex`.

**The CSP trade-off.** Pages are statically generated, so per-request nonces aren't available. `script-src` therefore includes `'unsafe-inline'` for the inline scripts Next.js emits for hydration. `'wasm-unsafe-eval'` is needed by the Meshopt, Draco and Basis decoders. There is no user-generated HTML on the site, which keeps the XSS risk low. To tighten this, render pages dynamically and switch to nonces (generated in `src/proxy.ts`); this costs static caching.

## Admin authentication

- **Password:** scrypt (N = 32768, r = 8, p = 1, 64-byte key, random salt), stored only as a hash in `ADMIN_PASSWORD_HASH`. Make one with `npm run admin:hash`. The comparison is constant-time.
- **Session:** an HMAC-SHA256 signed token (expiry, random id, signature) in a cookie named `paladex_admin`. The cookie is `HttpOnly`, `SameSite=Strict`, `Secure` in production, and lasts 12 hours. `ADMIN_SESSION_SECRET` must be at least 32 characters; without it, or without the hash, the admin stays locked.
- **Checks in two places:** `src/proxy.ts` redirects requests to `/admin` without a valid session. Every admin page and server action also calls `requireAdmin()`, so the proxy is never the only defence. The upload API checks the session itself.
- **Signing out** deletes the cookie. Tokens are stateless, so a stolen token stays valid until it expires. To sign out every session at once, change `ADMIN_SESSION_SECRET`.
- **Writes** are server actions: Next.js checks their origin, and every input is validated with zod (`src/server/validation/admin.ts`) before it reaches the database.

## Rate limits

| What | Limit |
|---|---|
| Sign-in | 5 wrong passwords per address per 15 minutes, and 30 attempts overall per 15 minutes. A successful sign-in clears that address's counter |
| Uploads | 30 per address per 10 minutes |
| Analytics events | 120 per address per 10 minutes |

- The limiter (`src/server/rate-limit.ts`) keeps its counters **in memory**. That is enough on one server. With several instances or serverless functions, each one counts separately, so move it to Redis/Upstash behind the same `rateLimit()` function.
- The overall sign-in limit stops password guessing spread over many addresses. Its cost: someone could keep the owner locked out by spending 30 attempts every 15 minutes. If that ever happens, put the admin behind a second gate (an IP allow-list, Cloudflare Access or basic auth at the host).
- The client address comes from the last entry of `X-Forwarded-For` (or `X-Real-IP`). That is the hop added by Vercel's and Netlify's own proxies. Behind another proxy, check what it sets.

## Uploads

`/api/admin/upload` and `src/server/storage/index.ts`:

- Admin session required, same-origin `Origin` header required, rate limited.
- Extension allow-list: `.glb` and `.gltf` for models (25 MB), PNG, JPEG, WebP and AVIF for images (8 MB).
- The **file signature must match the extension**: a GLB must start with `glTF`, images are checked against their magic bytes. A renamed text file is refused.
- A `.gltf` must be self-contained: external references are refused.
- File names are generated on the server (slug + random suffix); the visitor's name is never used as a path.
- In production, local-disk uploads are off unless `ALLOW_LOCAL_UPLOADS=true`; use S3/R2. Local uploads live in `data/uploads/`, outside `public/`, and are served by a route that only accepts generated names.
- Model and image URLs pasted into the admin must be a local path (no `..`, no `//`) or https on a host in `ASSET_ORIGINS`.

## Affiliate redirect (`/go/<offerId>`)

- The route only redirects to an https URL on one of the retailer's **allowed domains**. Anything else goes to the "link not active yet" page, so `/go` can't be used as an open redirect.
- The admin also refuses to save a live link outside those domains.
- Placeholder links (`AFFILIATE_URL_HERE` or empty), inactive offers, inactive retailers and unpublished rackets never redirect.
- Redirect responses are `no-store` and `noindex`.

## Personal data

- No visitor accounts, no advertising trackers, and no cookies for visitors. The only cookie is the admin session.
- First-party analytics store the event name, racket, page path and a few values. No IP address, user agent or identifier is stored. IP addresses are used only in memory for rate limiting.
- Affiliate clicks store the offer, racket, retailer, source page and time.
- The privacy and cookie policies in `src/content/legal.ts` are drafts and must be reviewed before launch.

## Secrets

- `.env.local` holds the local admin password (as a comment) and secrets. It is git-ignored. It must never be uploaded: the Netlify uploader ignores `.gitignore`, so deploy from a clean copy (see DEPLOYMENT.md).
- Use a different admin password and session secret in production.

## Reporting a problem

Write to the contact address in `src/config/site.ts`. It is a placeholder: set the real one before launch.
