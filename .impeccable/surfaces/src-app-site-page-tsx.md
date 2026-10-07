---
version: 1
slug: "src-app-site-page-tsx"
primary_target: "src/app/(site)/page.tsx"
related_targets: ["src/app/(site)/showroom/page.tsx","src/app/(site)/rackets/page.tsx","src/app/(site)/rackets/[slug]/page.tsx","src/app/(site)/finder/page.tsx"]
---

# Surface brief: Paladex site (home first, shared world for showroom, rackets and brands, racket page, finder, admin)

Scope: the whole public site. The homepage is the lead surface. Mode: Persuade (home), Experience (showroom), Operate (rackets and brands, finder, admin), Read (guides, legal).
Audience: padel players choosing a racket, often on a phone in the evening after playing. Action: pick a brand, open a racket in 3D, take the finder, click through to a retailer.
Proof on hand: interactive 3D models (one platform model from the owner's photos, the rest labelled placeholders), sample specs labelled unverified. No reviews, ratings or live prices to show.
User redirect (session 3): the previous night-court build "looks robotic". The user asked for something aesthetic, 3D, and interactive on both PC and phone, and authorised choosing the direction without a decision round.
User redirect (session 3, second brief, pinned): colours too strong and too bright; go darker and premium, black and white (or very dark blue with white), remove the strong blue, minimal racket backdrops (full black, full white or very dark with a soft shadow), reveal-once smooth 3D motion, a simpler and more centred viewer anyone understands, a hamburger with a side drawer instead of the big title animation, brands merged into the rackets browser, compare removed. This replaces the golden-hour replay world below in full.

## Direction contract

THESIS: A black product studio. Every racket stands alone on a black (or white) sweep under soft studio light with a contact shadow, and the page around it is quiet enough that the racket is the only thing with presence. It refuses the category default (coloured gradient stages, neon accents, glass-card grids, busy 3D chrome) because the user called that too bright and too complicated.

OWN-WORLD: Near-black ground #0a0b0d with graphite surfaces, off-white #eceef1 as the single action colour (white pills, dark text), ink greys for hierarchy. Ball-lime only at the sweet spot and match scores. The studio lives inside the 3D scene (softbox, two rim strips, contact shadow), never as CSS decoration; a "White studio" switch flips the sweep. One wide variable face (Google Sans Flex, upright wide display, tabular numbers). Pill controls, 16-20px cards, soft dark shadows.

STORY: Visitors pick a brand, see its rackets stand up in the studio, turn one with a drag or the Front/Side/Back bar, read what its shape and balance mean, let the finder suggest a match, and click through to buy.

FIRST VIEWPORT: Full-height black studio. The Metalbone stands right of centre with a soft shadow beneath. Left, "Every padel racket, in 3D." with a white "Browse rackets" pill and an outline "Find my racket" pill. At the bottom, the simple viewer bar: turn left, Front, Side, Back, turn right, reset, full screen. Header: logo, "Rackets 3D Showroom", search, Menu with a three-line icon that opens a side drawer.

FORM: Studio showroom. Controls are deliberately few: drag to rotate within a clamped orbit (no pan, tight zoom range, gentle inertia, slow auto-turn), named views instead of free camera, Details hotspots off by default. Brand tiles are rackets on mini studio sweeps in a snap rail that filters the list in place.
Motion grammar: elements rise into place once with a slight perspective tilt (translate3d plus rotateX) as they enter, and never hide again; long exponential ease-outs; the drawer slides from the right; dialogs pop in. Reduced motion shows everything immediately.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
