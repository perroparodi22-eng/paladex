export const meta = {
  name: 'paladex-ad-scenes',
  description: 'Build the 8 scenes of the Paladex launch ad (capture real site footage, implement in Remotion, adversarial review, fix) plus the music/SFX audio pass',
  phases: [
    { title: 'Build', detail: 'one builder per scene: capture real site footage, implement, self-review' },
    { title: 'Review', detail: 'independent adversarial critic per scene' },
    { title: 'Fix', detail: 'apply the critique, re-render, verify' },
    { title: 'Audio', detail: 'synthesise music bed per language and the SFX set' },
  ],
}

const ROOT = 'C:\\Users\\diego\\Downloads\\paladex\\promo\\video'

const SCENES = [
  { id: 'cold-open', file: 'ColdOpen', n: 1, notes: `No site capture needed: this is pure WebGL (RacketStage + RacketModel HERO_SLUG). Camera language: slow push-in + slight orbit, light reveal (silhouette rim first). "€200" in EN; Italian uses "200 €" (on "duecento euro"). The very first frames are black and build up (this scene has nothing under it): skip the enter part of enterExit or start from black deliberately. Exit: a whip-turn of the racket that hands over to the Problem scene.` },
  { id: 'problem', file: 'Problem', n: 2, notes: `No site capture strictly needed. "Flat photo": the same hero racket in WebGL gets literally squashed flat (RacketModel scale accepts [x,y,z]; squash z toward ~0.02 and turn it front-on under flat, dull lighting) and lands inside a generic, dull grey "product listing" card (no brand photos, no real shop branding). "Spec sheet": a cloud of cryptic spec chips/rows floating in deep CSS 3D (Space3D) with parallax and depth-of-field blur, camera drifting laterally through them; localise the jargon for Italian (lang prop). Tension builds; on "explains" (Italian: "spiega") everything collapses toward a point so the next scene's impact lands on its frame 0. Camera language: lateral track through depth.` },
  { id: 'reveal', file: 'Reveal', n: 3, notes: `Capture needed: the HOME page (http://localhost:3100/) hero: the racket auto-turns on its stage. Record ~320 frames at 1920x1080 dpr 1 with the virtual clock (let the model fully load and the reveal finish before freeze). Optionally the cursor drifts toward "Browse rackets" near the end (scripted cursor via record() api). Frame 0 = impact: soft flash + LogoMark hit animation + Wordmark on "Paladex"; on "Every" the logo lifts and the Browser3D window swings in from depth (path "/") showing the footage; the window settles on "3D". Camera language: push-in + swing. Add Sfx impact at 0 and a whoosh on the window swing.` },
  { id: 'turn', file: 'Turn', n: 4, notes: `Capture needed, ONE CLIP PER LANGUAGE (word-synced): the racket page http://localhost:3100/rackets/nox-at10-luxury-genius-18k-alum . Script: cursor approaches, grabs and drags the 3D racket around on "turn it in your hand" (IT: "girala tra le mani"), then clicks the viewer's Front / Side / Back buttons exactly on those words (IT: Fronte / Lato / Retro) — compute capture frames from src/data/timeline.<lang>.json word frames relative to when your clip starts in the scene. Find the buttons by text in the viewer controls (rectByText). The site's camera glides between views (camera-controls, virtual clock = smooth). Then on "Every detail, up close" (IT: "Ogni dettaglio, da vicino") the racket breaks out of the screen: the browser tilts back/recedes while the WebGL hero racket emerges huge in front and the camera glides close across the face texture and frame edge; optional faint ball-lime sweet-spot ring. Make the WebGL racket's orientation at the break-out moment match the on-screen racket's last view as well as you can so it reads as the same object leaving the screen. Camera language: orbit around the browser, then crane/push into macro. Sfx: click on each button click, whoosh on break-out.` },
  { id: 'specs', file: 'Specs', n: 5, notes: `Capture needed: the same racket page (http://localhost:3100/rackets/nox-at10-luxury-genius-18k-alum) specification section (rows like Shape, Weight, Balance, Thickness, Core, Surface, Sweet spot with their plain-language explanations and "Show on model" buttons). Use revealAll(), capture a dpr 2 still of the region you need (not the whole 7000px page), and marks() for the spec rows you lift out. In Remotion: smooth scroll inside Browser3D, then 2–3 rows lift out of the page in 3D (crops of the real still), readable at 1080p, the explanation text being the hero. Optionally capture a short clip of clicking a "Show on model" button (the viewer scrolls into view and shows an overlay on the 3D model) if it reads well. Don't feature the price or the "Where to buy" area. Camera language: tilt/scroll with layers lifting toward camera.` },
  { id: 'finder', file: 'Finder', n: 6, notes: `Capture needed: explore http://localhost:3100/finder (8 questions; first is "What's your level?" with Beginner/Intermediate/Advanced cards; one question is the "Where do you win your points?" court). Read src/components/finder/FinderQuiz.tsx and CourtZones.tsx to understand the flow and selectors. Capture dpr 2 stills (or viewport-size screenshots) of several question states with marks for the answer you will "tap", the court question, and the RESULTS view (match scores + 3D; a short footage clip with the virtual clock if results show turning 3D models). In Remotion: a deck of question cards in 3D; on "Answer a few quick questions" the cursor taps answers (click ripple + Sfx click) and each answered card flies away as the next comes forward; on "see the rackets that fit" the results come forward in Browser3D. Keep the answers plausible and consistent (e.g. Intermediate player). Camera language: fly-through a deck.` },
  { id: 'brands', file: 'Brands', n: 7, notes: `Capture needed: http://localhost:3100/rackets (brand rail tiles with logos + counts, racket grid). Optionally footage of a cursor clicking a brand tile (e.g. Nox) and the grid filtering (CSS motion runs in real time: use setAnimationRate or stills). WebGL: on "Sixty-two rackets" (IT "Sessantadue racchette") a wall/arc of many DIFFERENT real racket models (public/models/*.glb, ≤ 24 instances, one RacketStage) sweeps past with a counter rising to 62 synced to the word; on "Thirteen brands" ("Tredici marchi") brand tiles/logos sweep on a curved 3D rail with a counter to 13 (public/brands has 10 logo PNGs; the real rail capture shows the rest); on "All in one place" ("Tutto in un unico posto") everything converges into Browser3D showing the real /rackets page. Camera language: fast lateral track / arc. Keep the counters honest (62 and 13).` },
  { id: 'endcard', file: 'EndCard', n: 8, notes: `No capture needed. LogoMark (hit animation) + Wordmark centred-ish, the hero racket turning slowly in WebGL behind or beside it (slow pull-back camera). Headline "See it from every side before you buy it." (IT: "Guardala da ogni lato, prima di comprarla."), an off-white pill CTA styled like the site's primary button ("Find your racket" / IT "Trova la tua racchetta") with a small line under it "Free · No sign-up" (IT "Gratis · Senza registrazione"). Make the CTA text props easy to change at the top of the file (the final domain is not decided; do NOT invent a URL). This is the last scene: no exit transition, keep drifting to the very last frame; a final soft hit (Sfx impact low volume or pop) lands with the logo; keep it calm. It's the ad's final impression: make it beautiful and balanced, with subtitles visible at the bottom.` },
]

const BUILD_SCHEMA = {
  type: 'object',
  properties: {
    scene: { type: 'string' },
    summary: { type: 'string', description: 'what the scene does now, beat by beat with frame numbers' },
    files: { type: 'array', items: { type: 'string' } },
    captures: { type: 'array', items: { type: 'string' }, description: 'clip/still names registered in the manifest fragment' },
    sheets: { type: 'array', items: { type: 'string' }, description: 'paths of the final contact sheets rendered' },
    known_issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['scene', 'summary', 'files', 'sheets', 'known_issues'],
}

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    scene: { type: 'string' },
    verdict: { type: 'string', enum: ['ship', 'fix'] },
    strengths: { type: 'array', items: { type: 'string' } },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          frames: { type: 'string', description: 'scene-local frame(s) where it shows' },
          problem: { type: 'string' },
          fix: { type: 'string', description: 'concrete change to make' },
        },
        required: ['severity', 'frames', 'problem', 'fix'],
      },
    },
  },
  required: ['scene', 'verdict', 'issues'],
}

const FIX_SCHEMA = {
  type: 'object',
  properties: {
    scene: { type: 'string' },
    fixed: { type: 'array', items: { type: 'string' } },
    not_fixed: { type: 'array', items: { type: 'string' }, description: 'issues deliberately not fixed, with the reason' },
    sheets: { type: 'array', items: { type: 'string' } },
    remaining_risks: { type: 'array', items: { type: 'string' } },
  },
  required: ['scene', 'fixed', 'not_fixed', 'sheets'],
}

const COMMON = `You are working in the Remotion project at ${ROOT} (a launch ad for the Paladex website). Seven other agents are building the other scenes in parallel right now, and one more is making the audio: only edit the files you own (your scene file src/scenes/<File>.tsx, an optional folder src/scenes/<scene-id>/, your capture script capture/shots/<scene-id>.mjs, your manifest fragment src/data/capture/<scene-id>.json, your captured frames under public/capture/<scene-id>/, and renders under out/<scene-id>/). Never edit shared files (listed in BRIEF.md section 4), never stop/restart the Next dev server on port 3100, never kill node/chrome processes you didn't start. Use absolute paths or cd into ${ROOT} in each Bash call. The Bash tool runs Git Bash on Windows; python, node 24 and pillow are available.

FIRST read ${ROOT}\\BRIEF.md completely (it is the contract), then the shared components it lists (src/components/*.tsx, src/lib/motion.ts, src/timeline.ts, src/scenes/types.ts, capture/cdp.mjs, capture/test-drag.mjs). Also read the Remotion agent skills the user asked us to follow: C:\\Users\\diego\\Downloads\\paladex\\.claude\\skills\\remotion-markup\\SKILL.md plus its 3d.md, timing.md, images.md, sequencing.md (Remotion 4.0.533: frame-driven animation only, no useFrame, premountFor={fps}, scale/translate/rotate props).`

// Builders that were interrupted in the first run (session limit / full disk). Their
// partial work is on disk; finished builds (reveal, specs) keep their exact prompts so
// their cached results are reused on resume.
const RESUMED = new Set(['cold-open', 'problem', 'turn', 'finder', 'brands', 'endcard'])
const RESUME_NOTE = (s) => RESUMED.has(s.id) ? `

RESUMING: an earlier builder for this scene was interrupted (account session limit, and the C: drive briefly filled up; that is fixed now: scripts/stills.mjs hard-links public/ instead of copying it and deletes its temp bundle). Its partial work may already be on disk: src/scenes/${s.file}.tsx (may still be the placeholder, or a full/partial implementation), capture/shots/${s.id}.mjs, src/data/capture/${s.id}.json and frames under public/capture/${s.id}/. Inspect all of it first. Keep and continue good work (verify captured frames by looking at them; re-capture only if they're missing, broken, incomplete or not what the storyboard needs). Then finish the scene and run the full check process below.` : ''

const buildPrompt = (s) => `${COMMON}${RESUME_NOTE(s)}

YOUR SCENE: #${s.n} "${s.id}" — component \`${s.file}\` in src/scenes/${s.file}.tsx (currently a placeholder; replace it). Isolated preview entry: src/dev/${s.id}.tsx (composition id "Dev", scene-local frames).

Storyboard for your scene is BRIEF.md section 8, item ${s.n}. Timing/words: BRIEF.md section 7 and src/data/timeline.en.json / timeline.it.json (the Italian cut has different lengths and word frames; your scene must work for both — derive frames from timing.duration and wordAt()).

Scene-specific direction:
${s.notes}

Quality bar: this is a paid launch ad. It must look like a high-end product film (Apple/Linear/Arc-launch quality): real depth, weighted camera moves, crisp type, nothing cheap, nothing cluttered, always moving at 60 fps, synced to the voice. Use the REAL site (captured footage/stills) wherever the site is shown — never fake UI.

Process:
1. If your scene needs captures, write capture/shots/${s.id}.mjs using capture/cdp.mjs (launch/goto/waitFor/rect/rectByText/freeze/record/revealAll/marks/fullPage/screenshot/writeManifest/packCursor). Run it, then LOOK at a few captured frames (Read tool) to confirm they are right (model loaded, nothing broken, correct state, no dev overlays). Re-capture until good.
2. Implement the scene. Use enterExit() for the house transition (see BRIEF section 3), Sfx for clicks/whooshes, Kinetic for headlines, lang-aware strings defined inside your scene file.
3. Render and inspect: \`cd ${ROOT} && node scripts/stills.mjs Dev out/${s.id} 0-<last frame>/12 --entry src/dev/${s.id}.tsx --sheet sheet-en.jpg\` and the same with \`--props '{"lang":"it"}' --sheet sheet-it.jpg\` (into a different out dir, e.g. out/${s.id}-it). Read the sheets AND several full-size frames (\`--scale 1\` for specific frames) around every key moment and fast move (every 2–4 frames there) to check smoothness. Fix and repeat at least twice; be your own harshest critic.
4. \`cd ${ROOT} && npx tsc --noEmit\` must report no errors in your files (ignore errors that are only in other scenes' files).
Return the structured summary (beats with frame numbers, files, captures, final sheet paths, honest known issues).`

const reviewPrompt = (s, built) => `${COMMON}

You are an independent, demanding creative director reviewing scene #${s.n} "${s.id}" (src/scenes/${s.file}.tsx) of the Paladex launch ad. You did not build it; assume nothing works until you see it. Do NOT edit any source files — only render and look.

The builder's own summary (may be optimistic): ${JSON.stringify(built ?? {}).slice(0, 4000)}

Scene direction given to the builder:
${s.notes}

Render fresh: \`cd ${ROOT} && node scripts/stills.mjs Dev out/${s.id}-review 0-<last>/10 --entry src/dev/${s.id}.tsx --sheet review-en.jpg\`, the Italian version (\`--props '{"lang":"it"}'\`, out/${s.id}-review-it), and full-size (\`--scale 1\`) frames at every key beat and densely (every 2 frames) around fast moves and the entry/exit. Read them.

Judge against BRIEF.md (sections 2, 3, 6, 8) and a top-tier launch-film bar:
- Is it genuinely 3D and showing the real website being used (where the storyboard calls for it)? Is footage crisp, correctly loaded, real?
- Always moving at 60 fps? Any frozen stretches, pops, jumps, flicker between consecutive frames, blank frames, z-fighting, clipping at frame edges?
- Composition, hierarchy, typography, readability at 1080p; anything cheap-looking, cluttered, off-palette, or under the bottom subtitle zone?
- Sync: do clicks/reveals land on the words (check word frames in src/data/timeline.<lang>.json)? Works in Italian (longer/shorter timing)?
- House transition on entry/exit; continuity with the story (same hero racket).
- Honesty rules (no fake UI/claims, no prices zoomed, labels not hidden misleadingly).
- Remotion rules (no CSS transitions, no useFrame, frame-driven only): read the source.
Return verdict "ship" only if there is nothing high or medium severity. Every issue needs exact frames and a concrete fix.`

const fixPrompt = (s, built, review) => `${COMMON}

You are finishing scene #${s.n} "${s.id}" (src/scenes/${s.file}.tsx). A builder made it; an independent critic reviewed it. Your job: fix every high and medium issue (and low ones when cheap), without regressing what works.

Builder summary: ${JSON.stringify(built ?? {}).slice(0, 3500)}

Critic review: ${JSON.stringify(review ?? {}).slice(0, 6000)}

Scene direction:
${s.notes}

Read BRIEF.md and the current scene source first. You may re-capture footage if the critique requires it (capture/shots/${s.id}.mjs). After fixing, render both languages (\`node scripts/stills.mjs Dev out/${s.id}-final 0-<last>/12 --entry src/dev/${s.id}.tsx --sheet final-en.jpg\` and the Italian one into out/${s.id}-final-it) and check each fixed issue at full size. \`npx tsc --noEmit\` clean for your files. Return what you fixed, what you didn't (and why), and the final sheet paths.`

// --- English only (owner's decision after the first run) -------------------------
// The Italian cut, its timeline, voice and music were deleted. Builds that already
// finished (reveal, specs) keep buildPrompt() above unchanged so their cached results
// are reused; every other new agent gets the English-only prompts below.
const DONE_BUILDS = new Set(['reveal', 'specs'])

const NOTES_EN = {
  'cold-open': `No site capture needed: this is pure WebGL (RacketStage + RacketModel HERO_SLUG). Camera language: slow push-in + slight orbit, light reveal (silhouette rim first). A big, quiet "€200" rises on "two hundred euros". The very first frames are black and build up (this scene has nothing under it): skip the enter part of enterExit or start from black deliberately. Exit: a whip-turn of the racket that hands over to the Problem scene.`,
  'problem': `No site capture strictly needed. "Flat photo": the same hero racket in WebGL gets literally squashed flat (RacketModel scale accepts [x,y,z]; squash z toward ~0.02 and turn it front-on under flat, dull lighting) and lands inside a generic, dull grey "product listing" card (no brand photos, no real shop branding). "Spec sheet": a cloud of cryptic spec chips/rows floating in deep CSS 3D (Space3D) with parallax and depth-of-field blur, camera drifting laterally through them. Tension builds; on "explains" everything collapses toward a point so the next scene's impact lands on its frame 0. Camera language: lateral track through depth.`,
  'reveal': SCENES.find((s) => s.id === 'reveal').notes,
  'turn': `Capture needed (word-synced): the racket page http://localhost:3100/rackets/nox-at10-luxury-genius-18k-alum . Script: cursor approaches, grabs and drags the 3D racket around on "turn it in your hand", then clicks the viewer's Front / Side / Back buttons exactly on those words — compute capture frames from src/data/timeline.en.json word frames relative to when your clip starts in the scene. Find the buttons by text in the viewer controls (rectByText). The site's camera glides between views (camera-controls, virtual clock = smooth). Then on "Every detail, up close" the racket breaks out of the screen: the browser tilts back/recedes while the WebGL hero racket emerges huge in front and the camera glides close across the face texture and frame edge; optional faint ball-lime sweet-spot ring. Make the WebGL racket's orientation at the break-out moment match the on-screen racket's last view as well as you can so it reads as the same object leaving the screen. Camera language: orbit around the browser, then crane/push into macro. Sfx: click on each button click, whoosh on break-out.`,
  'specs': SCENES.find((s) => s.id === 'specs').notes,
  'finder': SCENES.find((s) => s.id === 'finder').notes,
  'brands': `Capture needed: http://localhost:3100/rackets (brand rail tiles with logos + counts, racket grid). Optionally footage of a cursor clicking a brand tile (e.g. Nox) and the grid filtering (CSS motion runs in real time: use setAnimationRate or stills). WebGL: on "Sixty-two rackets" a wall/arc of many DIFFERENT real racket models (public/models/*.glb, ≤ 24 instances, one RacketStage) sweeps past with a counter rising to 62 synced to the word; on "Thirteen brands" brand tiles/logos sweep on a curved 3D rail with a counter to 13 (public/brands has 10 logo PNGs; the real rail capture shows the rest); on "All in one place" everything converges into Browser3D showing the real /rackets page. Camera language: fast lateral track / arc. Keep the counters honest (62 and 13).`,
  'endcard': `No capture needed. LogoMark (hit animation) + Wordmark centred-ish, the hero racket turning slowly in WebGL behind or beside it (slow pull-back camera). Headline "See it from every side before you buy it.", an off-white pill CTA styled like the site's primary button ("Find your racket") with a small line under it "Free · No sign-up". Make the CTA text props easy to change at the top of the file (the final domain is not decided; do NOT invent a URL). This is the last scene: no exit transition, keep drifting to the very last frame; a final soft hit (Sfx impact low volume or pop) lands with the logo; keep it calm. It's the ad's final impression: make it beautiful and balanced, with subtitles visible at the bottom.`,
}

const ENGLISH_ONLY = (s) => `

ENGLISH ONLY: the owner decided the ad is English only. The Italian cut, src/data/timeline.it.json, the Italian voice and music were deleted, and src/timeline.ts now has \`type Lang = "en"\` and \`TIMELINES = { en }\`. Remove any Italian left in this scene: no \`lang === "it"\` branches, no Italian strings, no \`{ en: ..., it: ... }\` string tables (inline the English text; such tables now fail typecheck), no per-language clip selection. Delete any Italian captures of this scene (\`*-it\` folders/files under public/capture/${s.id}/ and their entries in src/data/capture/${s.id}.json; English captures may keep their \`-en\` names). Never render with --props lang "it".`

const buildPromptEn = (s) => `${COMMON}${RESUME_NOTE(s)}${ENGLISH_ONLY(s)}

YOUR SCENE: #${s.n} "${s.id}" — component \`${s.file}\` in src/scenes/${s.file}.tsx. Isolated preview entry: src/dev/${s.id}.tsx (composition id "Dev", scene-local frames).

Storyboard for your scene is BRIEF.md section 8, item ${s.n}. Timing/words: BRIEF.md section 7 and src/data/timeline.en.json (derive frames from timing.duration and wordAt() rather than hard-coding).

Scene-specific direction:
${NOTES_EN[s.id]}

Quality bar: this is a paid launch ad. It must look like a high-end product film (Apple/Linear/Arc-launch quality): real depth, weighted camera moves, crisp type, nothing cheap, nothing cluttered, always moving at 60 fps, synced to the voice. Use the REAL site (captured footage/stills) wherever the site is shown — never fake UI.

Process:
1. If your scene needs captures, write capture/shots/${s.id}.mjs using capture/cdp.mjs (launch/goto/waitFor/rect/rectByText/freeze/record/revealAll/marks/fullPage/screenshot/writeManifest/packCursor). Run it, then LOOK at a few captured frames (Read tool) to confirm they are right (model loaded, nothing broken, correct state, no dev overlays). Re-capture until good.
2. Implement the scene. Use enterExit() for the house transition (see BRIEF section 3), Sfx for clicks/whooshes, Kinetic for headlines, English strings inline.
3. Render and inspect: \`cd ${ROOT} && node scripts/stills.mjs Dev out/${s.id} 0-<last frame>/12 --entry src/dev/${s.id}.tsx --sheet sheet.jpg\`. Read the sheet AND several full-size frames (\`--scale 1\` for specific frames) around every key moment and fast move (every 2–4 frames there) to check smoothness. Fix and repeat at least twice; be your own harshest critic.
4. \`cd ${ROOT} && npx tsc --noEmit\` must report no errors in your files (ignore errors that are only in other scenes' files).
Return the structured summary (beats with frame numbers, files, captures, final sheet paths, honest known issues).`

const buildPromptFor = (s) => (DONE_BUILDS.has(s.id) ? buildPrompt(s) : buildPromptEn(s))

const reviewPromptEn = (s, built) => `${COMMON}

You are an independent, demanding creative director reviewing scene #${s.n} "${s.id}" (src/scenes/${s.file}.tsx) of the Paladex launch ad. You did not build it; assume nothing works until you see it. Do NOT edit any source files — only render and look. The ad is ENGLISH ONLY (the Italian version was dropped; src/timeline.ts has Lang = "en" only).

The builder's own summary (may be optimistic): ${JSON.stringify(built ?? {}).slice(0, 4000)}

Scene direction given to the builder:
${NOTES_EN[s.id]}

Render fresh: \`cd ${ROOT} && node scripts/stills.mjs Dev out/${s.id}-review 0-<last>/10 --entry src/dev/${s.id}.tsx --sheet review.jpg\`, and full-size (\`--scale 1\`) frames at every key beat and densely (every 2 frames) around fast moves and the entry/exit. Read them.

Judge against BRIEF.md (sections 2, 3, 6, 8) and a top-tier launch-film bar:
- Is it genuinely 3D and showing the real website being used (where the storyboard calls for it)? Is footage crisp, correctly loaded, real?
- Always moving at 60 fps? Any frozen stretches, pops, jumps, flicker between consecutive frames, blank frames, z-fighting, clipping at frame edges?
- Composition, hierarchy, typography, readability at 1080p; anything cheap-looking, cluttered, off-palette, or under the bottom subtitle zone?
- Sync: do clicks/reveals land on the words (check word frames in src/data/timeline.en.json)?
- House transition on entry/exit; continuity with the story (same hero racket).
- Honesty rules (no fake UI/claims, no prices zoomed, labels not hidden misleadingly).
- Remotion rules (no CSS transitions, no useFrame, frame-driven only) and leftover Italian (lang branches, Italian strings, { en, it } tables, -it captures): read the source; leftover Italian is a medium issue.
Return verdict "ship" only if there is nothing high or medium severity. Every issue needs exact frames and a concrete fix.`

const fixPromptEn = (s, built, review) => `${COMMON}${ENGLISH_ONLY(s)}

You are finishing scene #${s.n} "${s.id}" (src/scenes/${s.file}.tsx). A builder made it; an independent critic reviewed it. Your job: fix every high and medium issue (and low ones when cheap), without regressing what works, and make sure no Italian is left (see above).

Builder summary: ${JSON.stringify(built ?? {}).slice(0, 3500)}

Critic review: ${JSON.stringify(review ?? {}).slice(0, 6000)}

Scene direction:
${NOTES_EN[s.id]}

Read BRIEF.md and the current scene source first. You may re-capture footage if the critique requires it (capture/shots/${s.id}.mjs). After fixing, render (\`node scripts/stills.mjs Dev out/${s.id}-final 0-<last>/12 --entry src/dev/${s.id}.tsx --sheet final.jpg\`) and check each fixed issue at full size. \`npx tsc --noEmit\` clean for your files. Return what you fixed, what you didn't (and why), and the final sheet paths.`

const AUDIO_PROMPT = `You are the audio designer for a ~47 s launch ad for Paladex (a premium, dark "black studio" 3D padel racket website). Project: ${ROOT} (Remotion). Read ${ROOT}\\BRIEF.md, src/Launch.tsx (how music is mixed and ducked under the voice), src/components/Sfx.tsx (the SFX names scenes use) and src/data/timeline.en.json + timeline.it.json (scene starts in frames at 60 fps; 120 BPM; beat = 30 frames, bar = 120 frames; every scene starts on the beat grid). The voiceover already exists in public/audio/vo/. Python 3.14 with numpy and pillow is available (pip install --user scipy if you need it). Remotion bundles ffmpeg: \`cd ${ROOT} && npx remotion ffmpeg -i in.mp3 out.wav\` works for decoding. Only write: audio/make_music.py (and helpers under audio/), public/audio/music.en.wav, public/audio/music.it.wav, public/audio/sfx/*.wav, out/audio/*. Other agents are editing scenes in parallel; don't touch other files.

1. SFX first (other agents are placing them now): synthesise 48 kHz stereo 16-bit WAVs, each tasteful, modern, premium UI-film style, short tails, no clipping, peaks ≤ -3 dBFS: click (crisp soft UI tick-click, ~60 ms), tick (tiny high tick), pop (soft bubbly pop for UI appearing), swipe (short airy swish ~250 ms), whoosh (big filtered-noise whoosh with doppler-ish pitch sweep ~700 ms), whoosh-soft (gentler ~500 ms), impact (deep cinematic hit: sub drop + noise burst + long dark reverb tail ~2.5 s), riser (2 s rising filtered noise + pitch, ends abruptly so it can lead into an impact), shimmer (airy bright sparkle ~1.2 s). Write them into public/audio/sfx/ with exactly those names.
2. Music bed (one per language, because scene lengths differ): an original minimal electronic track, 120 BPM, in a minor key (e.g. A minor), premium and confident, like a modern tech product film. Arrange it to the scene starts in the timeline JSON so section changes land exactly on scene starts:
   - cold-open: dark low drone + slow sub heartbeat pulse, very sparse, mysterious;
   - problem: tension: ticking hats/clock-like pulse, dissonant pad, a riser building into the next scene start;
   - reveal (frame 0 of this scene): impact/downbeat, then the main groove starts: punchy kick (4 on the floor), soft clap on 2 and 4, shuffled hats, warm sub/mid bass following chords, wide pad chords (e.g. Am–F–C–G), a simple memorable pluck/arp motif;
   - turn → specs → finder → brands: keep the groove, but evolve (filter opening, arp variations, add/remove layers at scene starts, small fills/reverse swells into each scene start);
   - endcard: groove continues for about one bar, then the drums and bass drop out under the final line, leaving the pad and motif with reverb; a final soft chord/hit near the logo (scene start + ~42 frames ≈ "Paladex"), and a clean reverb tail to the last frame (no abrupt cut, but it must be faded out by the final frame).
   Exact length = durationInFrames / 60 seconds. Proper synthesis (band-limited oscillators or oversampling, ADSR envelopes, filters, chorus/detune for width, a convolution or feedback-delay reverb, sidechain-style pumping on pads/bass from the kick), gentle bus compression/soft-clip limiter, true peak ≤ -1 dBFS, integrated loudness around -16 LUFS (approximate with K-weighted RMS is fine). Mono-compatible low end (sub mono). It will be ducked under the voice by Remotion, so leave room in the 1–4 kHz voice range in the pads.
3. Verify like an engineer since you cannot listen: print peak/RMS per section, check no clipping or DC offset, render spectrogram and waveform PNGs (out/audio/) and Read them to confirm structure (sections change at scene starts, drop-out at the end, impact at reveal). Mix a rough check (music at the ducked levels from Launch.tsx + the voice files decoded from public/audio/vo/en at their timeline 'at' frames) to out/audio/mix-check.en.wav and confirm the voice sits clearly above the music (report the voice-to-music RMS ratio during speech, aim ≥ 10 dB).
Return a short report: files written, durations, loudness/peaks, structure per scene, and any concerns.`

phase('Build')
const scenesP = pipeline(
  SCENES,
  (s) => agent(buildPromptFor(s), { label: `build:${s.id}`, phase: 'Build', schema: BUILD_SCHEMA }),
  (built, s) => agent(reviewPromptEn(s, built), { label: `review:${s.id}`, phase: 'Review', schema: REVIEW_SCHEMA }).then((review) => ({ built, review })),
  (r, s) => agent(fixPromptEn(s, r?.built, r?.review), { label: `fix:${s.id}`, phase: 'Fix', schema: FIX_SCHEMA }).then((fix) => ({ id: s.id, built: r?.built, review: r?.review, fix })),
)
const audioP = agent(AUDIO_PROMPT, { label: 'audio', phase: 'Audio' })
const [scenes, audio] = await Promise.all([scenesP, audioP])
return { scenes, audio }
