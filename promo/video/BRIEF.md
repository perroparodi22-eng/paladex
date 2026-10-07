# Paladex launch ad: creative and technical brief

Read this whole file before touching code. It is the contract every scene follows.

## 1. What we are making

A ~47 s launch advertisement for **Paladex** (the 3D padel racket website in `C:\Users\diego\Downloads\paladex`), built in **Remotion** (`promo/video`). Goal: people watch, like it, and go to the site.

- **1920×1080, 60 fps.** Smooth. **Always moving**: no frame may be identical to the one before it. Even "holds" keep a slow camera drift (use `drift()` from `src/lib/motion.ts`).
- **3D, and showing the real website being used.** The site is shown inside floating 3D browser windows (`Browser3D`, CSS 3D) with a cursor interacting with it, using **real footage captured from the running site** (`capture/cdp.mjs`). The racket models are the site's real `.glb` files rendered in WebGL (`Racket3D`).
- **Voiceover** (Microsoft neural voice, already generated, word-timed) + **music bed** + **sound effects**. **English only** (the owner decided: no Italian version; don't add language branches or Italian strings).
- Tone: premium, calm, confident, sporty. One person talking to a player. Not an announcer, not "gaming", not childish.

## 2. Look ("Black studio", same as the site)

- Ground `#070809`/`#0a0b0d`, surfaces `#131519` `#1a1d22`, text `#eceef1` (ink) `#a9aeb8` (ink-2) `#878d98` (ink-3). All in `src/theme.ts` as `C`.
- **Off-white `#eceef1` is the action colour** (pill buttons, highlights). **Ball-lime `#d9f04a` is only for the sweet spot and match scores.** No other accent colours, no gradients in colour, no neon.
- Type: Google Sans Flex only. Headlines use `display` from `src/theme.ts` (wide, semibold, tight). `Kinetic` animates headlines word by word.
- Rackets stand in a black studio under one soft light (`Backdrop` + `RacketStage` lights copy the site's rig).
- Film grain and vignette are global (in `Backdrop`). Don't add your own backgrounds: scenes are transparent layers over the global `Backdrop`.
- **Keep the bottom 170 px clear of important content**: subtitles (`Captions`) live there (pill, ~70 px tall, 70 px from the bottom).

## 3. Motion rules (Remotion)

- Everything is a pure function of `useCurrentFrame()`. **No CSS transitions/animations, no `useFrame` in three.js, nothing that animates by itself.** Use `interpolate()` with `Easing.bezier` (helpers in `src/lib/motion.ts`: `rise`, `easeOut` (the site's expo), `easeInOut`, `easeIn`, `drift`, `clamp`).
- Get `fps` from `useVideoConfig()`; give timed `<Sequence>`/`<Audio>` `premountFor={fps}`.
- Prefer `scale`, `translate`, `rotate` style props; use `transform` strings for 3D (`poseTransform`).
- Moves ease in and out (no linear starts/stops) except continuous drifts. Motion should feel like a real camera operator: smooth, weighted, with small overshoot-free settles.
- **Sync to the voice.** Scene-local word frames come from `wordAt(timing, "Side", fallback)` (`src/timeline.ts`). Clicks, reveals and counters land on the word that names them. Derive frames from `wordAt` / `timing` rather than hard-coding them, so the scene survives a re-recorded voice.
- **Transitions:** a scene is mounted for `timing.duration + timeline.overlapFrames` (18) frames. It enters on top of the previous scene during its first 18 frames and leaves under the next one during its last 18. Use `enterExit()` from `src/lib/motion.ts` on the scene root so every cut reads as one forward dolly. You may add a scene-specific flourish (e.g. the Reveal impact) on top.

## 4. Building blocks (use them; don't edit shared files)

Shared files are read-only for scene builders: `src/components/*`, `src/lib/*`, `src/theme.ts`, `src/timeline.ts`, `src/Launch.tsx`, `src/Root.tsx`, `src/dev/SceneDev.tsx`, `capture/cdp.mjs`. If you need something different, write a scene-local helper in your scene file or in `src/scenes/<scene-id>/`.

- `Space3D` + `Browser3D` (`src/components/Browser3D.tsx`): a browser window in 3D. Props: `x y z rotateX rotateY rotateZ scale opacity path glare bare pageWidth pageHeight`. Its `children` are laid out in page CSS px (default 1920×1080), so footage, cursor and callouts placed inside stay glued to the page as it turns. Chrome bar is 56 px.
- `Footage` / `footageCursor` / `PageStill` / `clip` / `still` (`src/components/Footage.tsx`): play a captured clip at a local frame (`rate` to speed up/slow down), get the cursor that was scripted during capture, or show a captured still scrolled by `scrollY`.
- `Cursor` + `cursorAt` (`src/components/Cursor.tsx`): pointer or grabbing hand, click ripples; `cursorAt(keys, frame)` moves along eased, slightly arced keyframes. Coordinates are page px inside `Browser3D`.
- `RacketStage` + `RacketModel` (`src/components/Racket3D.tsx`): a transparent full-frame WebGL layer with the site's studio lights; models by slug (`public/models/<slug>.glb`, 48 real traced rackets; the hero is `HERO_SLUG` = `nox-at10-luxury-genius-18k-alum`). One `RacketStage` per scene at most; ≤ 24 model instances. Racket height ≈ 0.46 units; default camera at z 1.4, fov 30.
- `Kinetic` (`src/components/Kinetic.tsx`): headline words rising out of blur; optional `outAt`, `accent`.
- `LogoMark` (with `hit` 0–1 ball animation) and `Wordmark` (`src/components/Logo.tsx`).
- `Sfx` (`src/components/Sfx.tsx`): `<Sfx name="click|whoosh|whoosh-soft|impact|riser|tick|pop|swipe|shimmer" at={localFrame} volume={0.6} />`. Files are synthesised by the audio pass; until then they are silent placeholders. Put clicks on cursor clicks, whooshes on big moves. Keep it tasteful (volume 0.3–0.7).
- Brand logos: `public/brands/<brand>.png` (white on transparent). Models: `public/models/*.glb`. Do **not** use `public/photos/*` (brand photos with licences pending).

## 5. Capturing the real site

The site runs at **http://localhost:3100** (Next dev server; don't stop or restart it). `capture/cdp.mjs` drives headless Chrome with a **virtual clock**: `launch()` → `goto()` → interact/wait → `freeze()` → `record({ dir, frames, script })` steps time by exactly 1/60 s per captured frame, so the site's own 3D viewer (React Three Fiber) renders perfectly smooth 60 fps footage. See `capture/test-drag.mjs` for a working drag-to-rotate example.

- Write your capture script as `capture/shots/<scene-id>.mjs`. Save frames under `public/capture/<scene-id>/<clip>/f00000.jpg` (JPEG quality ~88, `dpr: 1` for motion clips). Register them with `writeManifest("<scene-id>", { clips: { name: { dir: "capture/<scene-id>/<clip>", frames, fps: 60, width, height, dpr, cursor: packCursor(track) } } })`. Clip names must be globally unique: prefix them with your scene id.
- Stills: `revealAll()` (forces scroll-reveal blocks visible), `scrollTo(y)`, `screenshot(file, { clip })` or `fullPage(file)`; `marks({ name: "css selector" })` returns document-coordinate boxes for callouts/crops. Keep stills ≤ ~4000 px on each side (decode cost): prefer `dpr: 2` crops of just the region you need over whole-page shots. Register stills with `writeManifest(..., { stills: { name: { file, width, height, dpr, marks } } })` where `width/height` are CSS px.
- **CSS animations run on real time, not the virtual clock.** For footage where CSS motion matters, `setAnimationRate()` (see its comment) or prefer stills + Remotion-side animation.
- If a clip must sync to words (e.g. clicks on "Front/Side/Back"), compute the click frames from `src/data/timeline.en.json` in the capture script.
- The Next dev indicator is hidden automatically. Wait for models to finish loading (hover the viewer to signal intent, then wait ~8 s) before `freeze()`.
- `prefers-reduced-motion` is off in captures, so the site's auto-turn and smooth camera are on.

## 6. Honesty (non-negotiable, from the site's PRODUCT.md)

- Everything shown must be the real site. No invented UI, features, reviews, ratings, testimonials or prices. Don't zoom in on prices (they're demo data) or affiliate links. Don't hide or crop away "sample"/"placeholder"/"platform-created model" labels in a misleading way.
- On-screen claims must be true today: **62 rackets, 12 brands** (brands with rackets on the site; the database also lists Tactical, which has none yet), every racket turns in 3D (some models are labelled placeholders on the site), the finder has 8 questions, browsing is **free with no sign-up**. Compare is removed from the site: never show it.

## 7. Timeline (`src/data/timeline.en.json`)

Scene-local frames (0 = scene start), 60 fps, 120 BPM (beat = 30 frames, bar = 120). Words: `word@frame`.

| # | Scene id (file) | Frames | Voice |
|---|---|---|---|
| 1 | `cold-open` (`ColdOpen.tsx`) | 240 | You're@36 about@41 to@53 spend@58 two@85 hundred@97 euros@116 on@140 a@147 padel@150 racket@176 |
| 2 | `problem` (`Problem.tsx`) | 300 | based@6 on@19 one@31 flat@50 photo@68 and@128 a@156 spec@158 sheet@174 nobody@195 explains@217 |
| 3 | `reveal` (`Reveal.tsx`) | 300 | Meet@42 Paladex@54 Every@119 padel@134 racket@163 in@208 3D@217 |
| 4 | `turn` (`Turn.tsx`) | 480 | Pick@24 any@34 racket@42 and@78 turn@85 it@99 in@101 your@105 hand@110 Front@162 Side@203 Back@250 Every@290 detail@302 up@331 close@336 |
| 5 | `specs` (`Specs.tsx`) | 360 | Every@23 spec@37 is@75 translated@81 into@123 what@136 it@143 actually@149 means@172 for@189 your@195 game@200 |
| 6 | `finder` (`Finder.tsx`) | 480 | Not@22 sure@29 where@42 to@49 start@52 Answer@100 a@114 few@117 quick@135 questions@148 and@203 see@213 the@224 rackets@228 that@257 fit@267 how@295 you@304 really@315 play@328 |
| 7 | `brands` (`Brands.tsx`) | 300 | Sixty-two@24 rackets@61 Thirteen@121 brands@142 All@197 in@203 one@208 place@216 |
| 8 | `endcard` (`EndCard.tsx`) | 360 | Paladex@42 See@102 it@111 from@115 every@132 side@148 before@173 you@191 buy@197 it@212 |

## 8. Storyboard

One racket carries the story: the **Nox AT10 Luxury Genius 18K Alum** (`HERO_SLUG`, black and gold). It is the home-page hero and its page is the one we use.

1. **Cold open — "You're about to spend two hundred euros on a padel racket…"** Black. The hero racket emerges from darkness in the WebGL studio: rim light first traces its silhouette, then the face catches the key light; slow turn and a slow push-in. On "two hundred euros" a big, quiet "€200" (display type, ink) rises beside it. Mysterious, premium. Exit: the racket whips/turns away into the next scene.
2. **Problem — "…based on one flat photo, and a spec sheet nobody explains."** On "flat", the 3D racket is literally flattened: it squashes into a dull, flat, slightly low-res "product listing" card (render the racket front-on with flat light inside a generic grey card; no brand photos). On "spec sheet", a cloud of cryptic spec chips/rows floats in deep 3D around it with parallax and depth blur: "Balance 265 mm", "EVA Soft 30", "12K Carbon", "Hardness 7/10", "Profile 38 mm", "Swingweight 162", "Teardrop?", "Diamond?", "Fiberglass 3K"… ink-3 grey, confusing, too many. Camera drifts through them. Tension builds; on "explains" everything collapses/sucks toward a point (music riser lands on the next scene's frame 0).
3. **Reveal — "Meet Paladex. Every padel racket, in 3D."** Frame 0 = impact (`Sfx impact`): a soft light flash, the logo mark punches in (the ball pops off the racket: `LogoMark hit`), "Paladex" wordmark on "Paladex". On "Every", the logo lifts away and a `Browser3D` window swings in from depth showing **captured footage of the home page** (racket auto-turning on its stage, "Every padel racket, in 3D." headline). Camera keeps pushing in; land the window's settle on "3D".
4. **Turn — "Pick any racket and turn it in your hand. Front. Side. Back. Every detail, up close."** The browser shows **the hero racket's page** (`/rackets/nox-at10-luxury-genius-18k-alum`). Real captured interaction: the cursor grabs the 3D racket and drags it round on "turn it in your hand"; then clicks the viewer's **Front / Side / Back** buttons exactly on those words (captured clicks, the site's camera glides between views). On "Every detail, up close", the racket **breaks out of the screen**: the browser tilts back and recedes while the WebGL hero racket emerges in front, huge, and the camera glides close across the face texture and frame edge (macro detail), maybe a faint ball-lime sweet-spot ring on the face.
5. **Specs — "Every spec is translated into what it actually means for your game."** The browser scrolls the racket page's specification section (real still, smooth Remotion scroll). Two or three spec rows **lift out of the page** in 3D (crops of the real rows using `marks`), each with its plain-language explanation readable: the site translates jargon into consequences. Cursor touches a "Show on model" control. Land the clearest lift on "means for your game".
6. **Finder — "Not sure where to start? Answer a few quick questions, and see the rackets that fit how you really play."** The real "Find my racket" quiz (`/finder`, 8 questions) as a deck of question cards in 3D: on "Answer a few quick questions" the cursor taps answers and each answered card flies off as the next one comes forward (captured stills of real question states; include "Where do you win your points?" court if possible). On "see the rackets that fit", the real results (match scores, 3D) come forward in the browser.
7. **Brands — "Sixty-two rackets. Twelve brands. All in one place."** On "Sixty-two rackets", a wall/arc of real 3D racket models (WebGL, many different models) sweeps past with a counter to 62. On "Twelve brands", the brand tiles/logos (real `/rackets` brand rail, or `public/brands/*.png`) sweep on a curved rail with a counter to 12. On "All in one place", everything converges into a browser window showing the real `/rackets` page (brand rail + racket grid; a cursor picks a brand and the grid filters if you can capture it).
8. **End card — "Paladex. See it from every side, before you buy it."** Logo mark + wordmark centred, the hero racket turning slowly in WebGL behind/beside it. Headline "See it from every side before you buy it." (the site's own footer line). An off-white pill CTA like the site's primary button: "Find your racket", with a small line under it: "Free · No sign-up". Keep drifting until the last frame; the music drops out under the last line and a final soft hit lands on the logo.

Every scene keeps moving the whole time and uses depth (parallax layers, 3D rotation, WebGL). Vary the camera language between scenes (orbit, push, crane, lateral track) so it never feels like the same move repeated.

## 9. How to check your work

- Scene-local preview of just your scene (isolated bundle, so other scenes' work-in-progress can't break it):
  `node scripts/stills.mjs Dev out/<scene-id> 0-<last>/12 --entry src/dev/<scene-id>.tsx --sheet sheet.jpg`
  (`--scale 1` for full-size frames). Then look at the sheet and at individual frames with the Read tool.
- Check: no blank/black gaps, no frozen stretches, no jumps between neighbouring frames (sample every 2–4 frames around fast moves), text readable and not clipped, nothing important under the subtitle pill, footage crisp, cursor where the clicks happen, words in sync, entry/exit follow the house transition.
- `npx tsc --noEmit` must be clean for your files.
