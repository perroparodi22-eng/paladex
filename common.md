You are one of seven parallel builders finishing **v2.1 of the Paladex launch ad** (Remotion 4, in `promo/video` of this repo). The owner watched v2 and asked for it "a bit slower so people can see well everything, and silence is filled". The voice and timeline are already done and committed. Your job is to make YOUR scenes fit the new timing and fix the review findings listed below. Work autonomously, no questions.

## Setup (do this first)
```
cd promo/video   # repo is checked out on claude/jolly-einstein-55kcst at 1e37877 or later
git fetch origin render-assets && git checkout origin/render-assets -- public/capture   # footage (git-ignored), then: git reset -q public/capture
npm ci
```
Read `promo/video/BRIEF.md` sections **0a** (v2.1 rules, they override everything) and 0, 3, 4, 6, 9. Read `src/data/timeline.en.json` for your scenes: absolute start/duration and every word's start/end frame. Scenes get scene-local timing via `wordAt(timing, "word", fallback)`; re-anchor every beat to the NEW words.

New lines (v2.1; bold = new words):
- cold-open 5 s: Two hundred euros. Maybe more. For one padel racket. **Would you buy it blind?**
- problem 5 s: And you're choosing it from one flat photo... and a spec sheet nobody explains. **Pure guesswork.**
- reveal 6 s (was 5): Not anymore. Meet Paladex. Every padel racket, in 3D, **right in your browser.**
- turn 7 s: Grab one. Spin it. Front. Side. Back. Every detail, up close: **the face, the frame, the finish.**
- specs 6 s (was 5): Every spec, translated into what it means for your game. **No jargon. Just how it feels on court.**
- reviews 5 s (was 4): What the reviewers say, summed up. **The good, the bad,** with the sources **to back it.**
- pros 4 s: See what the pros actually play **on tour, and the rackets behind their game.**
- finder 7 s: Not sure where to start? Answer a few quick questions, and get the rackets that fit how you really play. **Your match, in seconds.**
- brands 5 s (was 4): All the top brands**, side by side.** All in one place**, updated every season.**
- endcard 6 s: Paladex. See it from every side, before you buy it.
v2 -> v2.1 absolute scene starts: cold-open 0->0, problem 300->300, reveal 600->600, turn 900->960, specs 1320->1380, reviews 1620->1740, pros 1860->2040, finder 2100->2280, brands 2520->2700, endcard 2760->3000. Review frame numbers below are v2 ABSOLUTE frames (subtract the v2 scene start for scene-local).

## Rules that matter most
- Every new phrase gets a visible beat that matches what is said, landing on the word (±4 frames).
- Readable: each readable thing on screen is held ~1-1.5 s minimum; smooth continuous motion instead of rapid swaps.
- Never static: no hold over ~0.4 s without visible motion; no dim/near-empty frames; fill the frame.
- Owner rules: no counts of rackets or brands anywhere; never show the 14 unfinished rackets (`capture/unfinished.json`; the capture code hides them); don't feature sample data (match %, platform scores, prices) or rows reading "Not published"/"—".
- Sharp at 2560x1440: re-capture footage at dpr 2-3 if you show it large (see BRIEF section 5; the site runs with `npm run setup` then `npx next dev -p 3100` at the repo root; use `CHROME_EXTRA_ARGS="--disable-gpu-rasterization"`).
- Only edit files you own (listed below). Do not edit shared components, `Launch.tsx`, `timeline.*.json`, `script.json`, audio, or other builders' scenes. If you truly need a shared change, describe it in your report instead.

## Check your work (required)
- Scene alone: `node scripts/stills.mjs Dev out/<you> 0-<dur>/12 --entry src/dev/<scene>.tsx --scale 0.5 --sheet sheet.jpg` and look at the sheet; then full-res stills (`--scale 1.3333333333333333`) of every distinct shot and look at them (Read the PNGs).
- In the real composition: `node scripts/stills.mjs PaladexLaunch out/<you>-full <absFrom>-<absTo>/15 --scale 0.5 --sheet full.jpg` for your scenes' absolute range, including 20 frames before/after for the transitions.
- `npx tsc --noEmit` must pass.
- Optional but good: render your scenes' range as a short mp4 (`npx remotion render PaladexLaunch out/<you>.mp4 --frames=A-B --scale 0.5`) and step through it.

## Deliver
Commit to your branch (the session's outcome branch) with a clear message, and push. If you re-captured footage, also push only the changed capture dirs with `scripts/push-frames.sh <your-branch>-frames <scene...>`. Final message (your last turn, short): what changed per finding, anything you could not fix and why, commit hash, frames branch if any.
