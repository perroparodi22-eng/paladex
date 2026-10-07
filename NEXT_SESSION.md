# Start here: Paladex, next session

**FIRST: this session must be remote-controlled from the phone.** If the Remote Control badge in the title bar is off, switch it on (or ask Claude: "turn Remote Control on for this session"). New sessions now connect to Remote Control by default (Code tab setting).

Paste this into the new session:

> Continue building Paladex in `C:\Users\diego\Downloads\paladex`. Turn Remote Control on for this session first. Read `NEXT_SESSION.md`, then `HANDOFF.md` (sections 5b, 5c and 5d are the latest work). Don't touch the `casa-parodi` folder. First task: finish the 3D design quality check below.

## Where things stand (6 Oct 2026)

- **Site:** dark "Black studio" 3D padel racket showroom. Next.js 16, SQLite.
- **Size:** 62 rackets from 13 brands, of which 47 have 3D models traced from real photos.
- **Local:** `npx next dev -p 3100`.
- **Live preview:** https://paladex-preview.netlify.app
  - Requires a Netlify login, as perroparodi22@gmail.com.
  - Health check: `/api/health` should return `{"ok":true,"rackets":62}`.
- **Done this session:**
  - The dark redesign.
  - Smooth scrolling (the 3D pauses while you scroll; shaders compile in the background).
  - A hamburger side menu.
  - Brands merged into rackets, with logo tiles. Horizontal scrolling now works on PC (arrows and mouse drag).
  - A faint jigsaw-pattern background.
  - The brand catalogue: 34 rackets added.
  - The pro players catalogue: 13 rackets added, the Hack 04 updated, and a `/pros` page with "Played by" lines.
  - Netlify deploys fixed: the database now works on Netlify.
- **How to deploy:** stage a clean copy without `.env.local`, then run the Netlify MCP `deploy-site`. The exact steps are in HANDOFF.md section 3. Never upload `.env.local` (the admin password).

- **Session 4 (7 Oct):** every racket page now has a researched "What reviewers say" section with linked sources, and spec gaps were filled from retailer listings. See HANDOFF 5d.

## Remaining work

1. **3D design quality check: done.**
   - All 47 traced models were rendered and compared with their photos.
   - Fixed rough frame edges on the Vertex 05 27, Elite 02 27, Xplo Comfort 27, Drop Shot Axion and Head Extreme Motion, using `--close` in `scripts/cutout-racket-photo.ts`.
   - Known limits:
     - Head models have printed holes (Head photos show the holes as dark dots).
     - The Wilson Defy's print is soft (400 px source photo).
     - The back face repeats the front print.
   - Possible upgrade: use real back-face photos where they exist (e.g. Lok "Front 2").
2. **Bergamini (Tactical El Jefe):** not added; the sources disagree. It needs confirmed specs and a photo.
3. **Photo licences:** brand and shop photos are marked "licence pending". Get permission, or use affiliate-feed images, before a public launch.
4. Everything else is in HANDOFF.md section 6: docs, tests, `DESIGN.md`, and the admin click-through test.
