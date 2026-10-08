# Start here: Paladex, next session

**FIRST: this session must be remote-controlled from the phone.** If the Remote Control badge in the title bar is off, switch it on (or ask Claude: "turn Remote Control on for this session"). New sessions now connect to Remote Control by default (Code tab setting).

Paste this into the new session:

> Continue building Paladex in `C:\Users\diego\Downloads\paladex`. Turn Remote Control on for this session first. Read `NEXT_SESSION.md`, then `HANDOFF.md` (sections 5b–5e are the latest work). Don't touch the `casa-parodi` or `promo` folders. First task: the Black Crown Piton 5.0 (see "Remaining work", item 1).

## Where things stand (8 Oct 2026)

- **Site:** dark "Black studio" 3D padel racket showroom. Next.js 16, SQLite.
- **Size:** 62 rackets from 13 brands. 61 have 3D models traced from real photos. 1 (Black Crown Piton 5.0) still has a generic placeholder.
- **Local:** `npx next dev -p 3100`.
- **Live preview:** https://paladex-preview.netlify.app (last deploy `6ac772dc`, 8 Oct)
  - Requires a Netlify login, as perroparodi22@gmail.com.
  - Health check: `/api/health` should return `{"ok":true,"rackets":62}`.
- **How to deploy:** stage a clean copy, then run the Netlify MCP `deploy-site`.
  - The exact steps are in HANDOFF.md section 3.
  - **Exclude** `.env.local` (the admin password), `node_modules`, `.next`, `.tmp`, `.claude`, `data/*.db*`, `assets/reference`, `assets/brand-logos`, `public/decoders`, **`promo/` (4 GB) and `.git/`**. With the last two included the upload fails with a 500 error.

## What was done in the sessions so far

- **Earlier:**
  - The dark redesign, smooth scrolling and the hamburger side menu.
  - Brands merged into rackets, with logo tiles and a rail that scrolls on PC.
  - The faint jigsaw background.
  - The brand catalogue (34 rackets) and the pro players catalogue (13 rackets, a `/pros` page, "Played by" lines).
  - The Netlify database fix for phones.
  - The 3D quality check of all traced models.
- **7 Oct:** every racket page now has a researched **"What reviewers say"** section.
  - It holds a summary, what testers like, watch-outs, who it suits, extra details, "Paladex's read", and linked sources.
  - Spec gaps were filled from retailer listings, and the spec note says which fields came from shops.
  - The data lives in `src/data/seed/racket-research.ts` (HANDOFF 5d).
- **8 Oct:** 13 of the 14 placeholder rackets got **real 3D designs and photos** from shop listings (`RACKETS_WITHOUT_DESIGN.md`, HANDOFF 5e).
  - Wrong specs were corrected: HEAD Vibe and Evo Speed are teardrops, the Nox ML10 Pro Cup has an even balance, the Babolat Veron 3.0 is a diamond.
  - New options were added to the cut-out and trace scripts (`--keep`, `--hole-tolerance`, `--mask-contrast`, `--cut`, `--smooth`, `--mirror-outline`).
  - **Lesson:** do not use `--close` of 6 or more on the front cut-out. It can make parts of the face disappear.

## Remaining work

1. **Black Crown Piton 5.0** is the only racket without a real 3D design.
   - It is discontinued, probably from around 2021 (the site says 2025), and no shop still shows a photo.
   - Options: get a straight-on photo, swap it for a current Piton, or remove it. Ask the owner.
2. **Bergamini (Tactical El Jefe):** not added; the sources disagree. It needs confirmed specs and a photo.
3. **Review round-ups:**
   - The 2027 Bullpadel line, the Nox EA10 Hybrid and the adidas Arrow Hit Pro EDT are marked "Too new for a full review". Refresh them when independent reviews appear.
   - The admin form can't edit round-ups yet (edit `racket-research.ts` and re-seed).
4. **Photo licences:** brand and shop photos are marked "licence pending". Get permission, or use affiliate-feed images, before a public launch.
5. **Known model limits:**
   - HEAD models have printed holes (older ones) or see-through holes (new ones from white backgrounds).
   - The Wilson Defy's print is soft (400 px source).
   - The back face repeats the front print. Possible upgrade: real back photos.
   - The Wilson Bela Pro V3 and Babolat Viper Soft photos are slightly off-axis.
6. Everything else is in HANDOFF.md section 6: docs, tests, `DESIGN.md`, and the admin click-through test.

## Rules that still apply

- English UI, EUR prices. Be honest: no fake functionality, and label sample data.
- Never paste the admin password (it's in a comment in `.env.local`) into chat. Never upload `.env.local`.
- Don't touch `casa-parodi` or `promo`.
- Downloading files needs the owner's explicit permission.
- Keep HANDOFF.md updated.
