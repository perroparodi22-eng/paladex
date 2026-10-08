# Paladex design system: "Black studio"

A dark, quiet product studio. Every racket stands alone on a black (or white) sweep under soft light with a contact shadow, and the page around it is calm enough that the racket is the only thing with presence.

This replaced two rejected directions: "Court at Night" (felt robotic) and a bright golden-hour/court-blue rework (too strong, too bright). Don't reintroduce strong blue, coloured gradient stages, neon accents or glass-card grids.

- **Tokens:** `src/app/globals.css` (`@theme`). Use the tokens, never raw hex values in components.
- **Direction contract:** `.impeccable/surfaces/src-app-site-page-tsx.md`. **Product context:** `PRODUCT.md`.
- **Check:** `npx impeccable detect --json src` should report no findings (it reported none on 8 Oct 2026).

## Colour

| Token | Value | Use |
|---|---|---|
| `ground` | `#0a0b0d` | Page background |
| `surface` / `surface-2` / `surface-3` | `#131519` / `#1a1d22` / `#23272d` | Plates, cards, fields, raised controls |
| `ink` / `ink-2` / `ink-3` | `#eceef1` / `#a9aeb8` / `#878d98` | Text: primary, secondary, tertiary (all pass contrast on `ground` and `surface`) |
| `court` | `#eceef1` | **The single action colour**: white pills with dark text (`on-court` `#0a0b0d`) |
| `court-tint` / `court-mist` | `#24282f` / `#3b4049` | Quiet fills and outlines |
| `ball` | `#d9f04a` | **Only** the sweet spot and match scores. Never decoration |
| `warn` / `ok` / `danger` | `#f2c26b` / `#5fd6a4` / `#ff7b6e` | Status: unverified data and placeholders / verified and published / errors |
| `series-1…4` | `#eceef1`, `#8f9bb3`, `#5f6672`, `#c7cbd3` | Charts and diagrams (e.g. the shape comparison: series-1 solid, series-2 dashed) |

Translucent tints (`badge-warn`, `bg-ok/15`) are made for dark backgrounds. On the White studio stage, give them a dark backing (see the provenance badge in `Racket3DViewer`).

Generated share images (`opengraph-image.tsx`) can't read CSS variables, so `src/lib/og.ts` repeats the values. Keep the two in step.

## Type

One variable face, **Google Sans Flex**, self-hosted from `public/fonts/` and trimmed to the axes in use (opsz, ROND, wdth 100–115, wght 400–700). Width and roundness are set with `--wdth` and `--rond`.

| Class | Settings | Use |
|---|---|---|
| `.display` | wdth 112, ROND 30, weight 620, tracking −0.035em, line-height 1 | Page and hero headings |
| `.title` | wdth 106, weight 600, line-height 1.15 | Section and card titles |
| `.label` | wdth 104, weight 500, 13 px, `ink-2` | Small data labels (never an eyebrow above a heading) |
| `.num` | Tabular, lining figures | Prices, scores, weights, dates |
| `.prose` | 17 px, line-height 1.75, max 68ch | Guides and legal pages. Embeds inside use `.not-prose` |

## Surfaces and shape

- `.plate`: the page's one container. Graphite, a 7% white hairline and a soft shadow, with an 18 px radius (`--radius-plate`). Cards use 22 px (`--radius-card`), fields 12 px.
- Buttons, chips and badges are pills. `.btn-primary` is the white action pill; `.btn-secondary` is outlined; `.btn-ghost` is text only.
- `.stage-sky`: the black studio, a near-black ground (`#070809`) with one soft spotlight. It sits behind 3D canvases and posters, so both share the same light.
- `.card-sky`: the same studio, softer, for grids and tiles.
- `.stage-light`: the White studio (`#e7e8eb` with a white spotlight).
- The body has a faint jigsaw outline pattern (about 4.5% white): a static SVG tile, no fixed background, no animation.
- No `backdrop-filter` blur over live 3D: it re-blurs the canvas every frame.

## The 3D studio

- The studio lives inside the scene (`components/three/scene/Stage.tsx`, `PALETTES.dark` and `.light`): a key softbox, two rim strips, a hemisphere fill and a contact shadow. It is never CSS decoration.
- Controls are deliberately few:
  - Drag to rotate within a clamped orbit, with gentle inertia and a slow auto-turn.
  - No panning, and a tight zoom range.
  - Named views (Front, Side, Back) instead of a free camera.
  - Reset and full screen.
  - "Details" (hotspots) is off by default.
- The "White studio" switch flips the sweep; the page around it stays dark.
- Every viewer shows the model's provenance badge in the top-left corner.

## Motion

- `[data-reveal]`: elements rise into place **once**, with a slight perspective tilt (translate3d plus rotateX), as they enter the viewport. They never hide again when scrolling back.
- Long exponential ease-outs: `--ease-out-expo`, `--ease-out-quint`. `--ease-spring` decelerates without overshoot.
- The menu drawer slides in from the left; its close button sits where the menu button was. Dialogs pop in. On phones, sheets dock to the bottom.
- 3D rendering pauses while the page scrolls and while a viewer is off screen.
- With `prefers-reduced-motion`, everything shows immediately: no reveals, no auto-turn, no smooth scrolling.

## Icons and logo

- **Icons:** a custom 24 px stroke set in `components/ui/Icon.tsx`. Add new icons there in the same style; don't mix in an icon library.
- **Logo mark:** `components/layout/Logo.tsx` (also `src/app/icon.svg`). It is the only place the ball-lime appears outside the sweet spot and match scores.

## Image provenance

Every shipped image must say where it came from. Racket photos record this in the database (`product_images`: source, licence status, attribution) and on the racket page.

| Images | Source | Licence status |
|---|---|---|
| Racket photos, adidas Metalbone 3.4 (3) | Supplied by the site owner | Supplied |
| Racket photos from the owner's catalogue (158): bullpadel.com 64, head.com 28, noxsport.com 27, adidas.com 3, babolat.com 2, wilson.com 1, and retailers padelkiwi.com 21, ipontennis.com 6, padelgids.nl 3, padelmarket.com 3 | Brand and retailer product pages, collected in the owner's catalogue | **Pending.** Get permission, or switch to affiliate-feed images, before a public launch |
| Front cutouts used as 3D face textures | Derived from the photos above with `scripts/cutout-racket-photo.ts` | Same as their source photo |
| Brand logos, `public/images/brands/` (10) | Each brand's own website; Wikimedia Commons for adidas and Wilson; Head's from head.com. Turned white by `scripts/build-brand-logos.ts` | Used only to identify the brand |
| Racket illustrations, placeholder models, share images, the shape diagram | Generated by Paladex from parametric geometry (`src/lib/racket-geometry`, `src/lib/racket-svg.ts`) | Ours |
| Platform 3D models (`public/models/platform/`) | Built by Paladex from the photos above (`npm run models:build`) | Ours; their face prints follow the source photo's status |
| Google Sans Flex (`public/fonts/`) | Google Fonts | SIL Open Font License 1.1 |

Lok, Kuikma and Drop Shot have no logo file, so their tiles show the brand name.
