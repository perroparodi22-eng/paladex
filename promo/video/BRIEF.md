# Paladex launch ad: creative and technical brief

Read this whole file before touching code. It is the contract every scene follows.

## 0. Version 2: the owner's feedback (read first; it overrides anything below)

The owner watched v1 and asked for: **a fuller, faster opening** (the first ~10 s felt empty and slow), **everything faster but the ad longer** (more content, quicker pacing), **no unfinished rackets**, **higher detail**, **a livelier voice and sound**, and **no counts** of rackets or brands anywhere (the catalogue grows every year).

- **Length and structure.** About 54 s, 10 scenes: cold-open, problem, reveal, turn, specs, **reviews (new)**, **pros (new)**, finder, brands, endcard. New script in `src/data/script.json` (each line is several phrases voiced with different tone).
- **Timing is ESTIMATED for now.** `src/data/timeline.en.json` has `"estimated": true` and silent voice files until the real voice can be generated (network). Derive every frame from `wordAt()` / `timing.duration` (never hard-code frames), so the scene re-syncs when the real voice lands. Scene lengths can still change by a beat or two.
- **Pace.** No shot lingers: every ~1–1.5 s something decisive happens (a cut to a new framing, a whip, a punch-in, a new element landing on a word/beat). Camera moves are quicker with snappier ease-outs (fast start, soft settle), not slow drifts. Use the 120 BPM grid (beat = 30 frames, half-beat = 15) for hits. Keep it premium: fast and precise, never chaotic or cluttered. Transitions between scenes can be faster/punchier than the house dolly (whip, push-through, match cut) as long as the scene still enters/leaves within its overlap.
- **Full frames.** Avoid big empty black areas: layer depth (foreground elements, secondary rackets, UI fragments, type) so frames feel rich. Still the black-studio look and palette (section 2).
- **No counts.** Never show or say how many rackets/brands (no "62", no "12"). Don't feature the site's own count line ("62 rackets") either: keep it out of frame or unreadable.
- **No unfinished rackets.** 14 rackets have no finished design (`capture/unfinished.json`, e.g. the Nox ML10 Pro Cup). Never show them. `capture/cdp.mjs` hides them automatically in every capture (cards, list items, finder results, by link/poster/name); WebGL racket models come only from `public/models` (all finished). Check your captures anyway.
- **Detail.** The final render is **2560×1440** (`--scale 4/3`). Footage/stills that appear large must be captured at **dpr 2** (stills, crops) and clips at **dpr 1.5–2** so they stay crisp at 1440p; check frames at full size with `--scale 1.3333333333333333` (fewer digits gives a non-integer height that Remotion rejects).
- **Sound.** Livelier: put SFX on every cut, hit, landing and click (whoosh / swipe / impact / pop / tick / click / riser / shimmer), louder for key hits (0.5–0.9), so the picture feels punchy.

### Storyboard for new/changed scenes (v2)
- **cold-open** — "Two hundred euros. Maybe more. For one padel racket." Open hard, not on an empty black frame: a rapid, rhythmic montage of real 3D rackets (many different finished models, WebGL) whipping through frame on the beat, macro glimpses of faces/frames, then "€200" slams in big on "Two hundred euros" (hit), a flicker up to "€250"/"€300" on "Maybe more", and the hero racket (Nox AT10 18K) lands centre on "For one padel racket". Dense, confident, music-driven.
- **problem** — "And you're choosing it from one flat photo... and a spec sheet nobody explains." The hero flattens into a dull listing card on "flat photo", multiplied into a cold grid of identical flat cards; on "spec sheet nobody explains" a dense storm of cryptic spec chips; collapse to a point into the reveal impact. Faster than v1.
- **reveal** — "Not anymore. Meet Paladex. Every padel racket, in 3D." Hit on "Not anymore", logo punch on "Paladex", the real home page arrives fast on "Every", settle on "3D".
- **turn / specs / finder / endcard** — same ideas as section 8, tighter and faster (fewer slow holds, quicker moves, more shot changes).
- **reviews (new)** — "What the reviewers say, summed up, with the sources." The real racket page's **"What reviewers say"** section (hero racket page): the summary lifts out in 3D, then the **Sources** links (e.g. Padel Kiwi, Padelgids) land on "with the sources". Honest: real text only, no invented quotes or ratings; don't feature prices.
- **pros (new)** — "See what the pros actually play." The real **/pros** page ("Pro players' rackets — What the top of the tour plays, in 3D"): player cards/rows with their rackets, fast lateral sweep, land on a pro + racket on "play". Real data only; keep the page's caveat visible if it's in frame.
- **brands** — "All the top brands. All in one place." No counters. The real brand tiles sweep/turn on "All the top brands" (real `/rackets` brand rail crops), then everything converges into the real `/rackets` page on "All in one place" (cursor picks a brand, the grid filters). Only finished rackets in the grid.

### Timeline v2 (ESTIMATED; scene-local word frames)

| # | Scene id (file) | Start | Frames | Voice |
|---|---|---|---|---|
| 1 | `cold-open` (`ColdOpen.tsx`) | 0 | 300 | Two@26 hundred@43 euros@74 Maybe@132 more@155 For@205 one@221 padel@237 racket@259 |
| 2 | `problem` (`Problem.tsx`) | 300 | 360 | And@11 you're@26 choosing@49 it@78 from@90 one@108 flat@123 photo@141 and@185 a@200 spec@209 sheet@226 nobody@245 explains@267 |
| 3 | `reveal` (`Reveal.tsx`) | 660 | 300 | Not@23 anymore@40 Meet@100 Paladex@120 Every@180 padel@201 racket@222 in@251 3D@263 |
| 4 | `turn` (`Turn.tsx`) | 960 | 420 | Grab@20 one@37 Spin@59 it@77 Front@124 Side@177 Back@228 Every@282 detail@304 up@335 close@348 |
| 5 | `specs` (`Specs.tsx`) | 1380 | 300 | Every@17 spec@37 translated@59 into@105 what@124 it@142 means@154 for@175 your@190 game@208 |
| 6 | `reviews` (`Reviews.tsx`) | 1680 | 240 | What@17 the@34 reviewers@49 say@80 summed@112 up@136 with@153 the@171 sources@186 |
| 7 | `pros` (`Pros.tsx`) | 1920 | 240 | See@17 what@32 the@51 pros@66 actually@85 play@115 |
| 8 | `finder` (`Finder.tsx`) | 2160 | 480 | Not@17 sure@33 where@51 to@73 start@86 Answer@137 a@160 few@169 quick@183 questions@203 and@250 get@265 the@280 rackets@296 that@322 fit@339 how@354 you@369 really@384 play@408 |
| 9 | `brands` (`Brands.tsx`) | 2640 | 240 | All@17 the@32 top@47 brands@63 All@114 in@131 one@144 place@160 |
| 10 | `endcard` (`EndCard.tsx`) | 2880 | 360 | Paladex@29 See@96 it@113 from@126 every@146 side@168 before@192 you@218 buy@234 it@251 |

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
