# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

delegated: Next.js 16 (App Router) + TypeScript + Tailwind CSS v4; three.js through React Three Fiber and drei for every 3D surface; Drizzle ORM over libSQL/SQLite (a local file in development, Turso or a persistent-disk host in production). The brief preferred Next.js, TypeScript, React, Tailwind, R3F, and "PostgreSQL or another appropriate relational database, Prisma or equivalent" and left the final call to us; libSQL was chosen for zero-setup local development and cheap hosting, with a documented path to Postgres.

## Users

- **Padel players choosing their next racket**, from first-time buyers to advanced club players, very often on a phone. Their job: work out which racket fits their level, style, and budget, trust the reasoning, then buy from a retailer.
- **The owner/admin** (a single person at launch) who maintains racket data, 3D assets, scores, prices, retailers, and affiliate links without touching code.

## Product Purpose

A 3D-first database for discovering, inspecting, comparing, and getting recommendations on padel rackets. It earns money through affiliate commissions when visitors click through to external retailers. Success means a real padel player trusts the site enough to decide here and click through.

## Positioning

Every racket can be explored as an interactive 3D model. The things that decide a purchase (shape, balance, thickness, sweet spot, grip) are explained on the model itself. Rackets can be compared side by side in synchronized 3D, and the finder quiz shows its matches in 3D. Neighbouring products are photo catalogs, shop listings, and blogs.

## Operating Context

- Main path: search, then a racket page, then the 3D viewer, specs, comparison, and a retailer. Mobile users must be able to do all of it with touch alone.
- A protected admin panel is used by the owner to add rackets, replace models, and update prices and affiliate links.
- Launch market: EU-wide, English UI, prices in EUR. The structure stays ready for translation.

## Capabilities and Constraints

- The site never processes payments. Purchases happen at external retailers through affiliate links, which stay marked as placeholders (`AFFILIATE_URL_HERE`) until real ones exist.
- Browsing never requires an account. Accounts are a future feature.
- There are no licensed product photos or official 3D models yet. The site uses platform-created placeholder models and illustrations, labelled clearly. Every asset records its provenance (manufacturer, licensed, platform-created, placeholder, unavailable) and its license status.
- Manufacturer specifications and platform evaluations are kept separate in the data and in the UI. Scores are the platform's own evaluation, not certified measurements.
- SEO matters. Specs, descriptions, comparisons, and recommendations must exist as semantic HTML, not only inside a canvas.
- The 3D experience has to degrade gracefully: posters first, models when the visitor shows intent, an image fallback without WebGL, and reduced motion when the visitor asks for it.
- Later product categories (shoes, balls, bags, grips, apparel) must fit the data model without a rewrite.

## Brand Commitments

- Name: **Paladex** (working name, trademark not yet checked).
- Aesthetic: dark and premium. In session 3 the owner first rejected the night-court build as "robotic", then rejected the bright golden-hour/court-blue rework as "too strong and too bright". Current pinned direction: a black product studio, black and white (off-white actions), minimal racket backdrops with a soft shadow, smooth reveal-once 3D motion, simple 3D controls anyone understands. Keep: premium, sporty, not childish, not "gaming", not cluttered. Compare is parked for now; discovery and 3D viewing come first.
- Voice: credible and educational. Every technical term is translated into a plain consequence for the player.

## Evidence on Hand

None yet. There are no real 3D models, product photos, retailer prices, affiliate accounts, user reviews, or verified specifications. All seed data is sample data and must be labelled as such. Never fabricate user ratings or reviews, lab-style measurements, prices presented as live, testimonials, or claims that a model is official.

## Product Principles

1. Answer "Is this racket right for me?" Translate specs into decisions instead of listing them.
2. 3D earns its place. Every control does something real and helps a decision.
3. Honesty beats polish. Placeholder, sample, illustrative, and affiliate content is always labelled.
4. Mobile and performance first. Show posters before models, and load models only when the visitor shows intent.
5. Crawlable truth. What a search engine needs is plain HTML.

## Accessibility & Inclusion

- WCAG 2.2 AA target.
- Every 3D action has a keyboard and button alternative to gestures.
- `prefers-reduced-motion` is respected everywhere, including auto-rotation.
- Touch targets are at least 44px.
