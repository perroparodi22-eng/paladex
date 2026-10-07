# Paladex launch ad (Remotion)

A ~47-second, 60 fps launch video for Paladex. It shows the real site, captured from the running app, inside floating 3D browser windows. The site's real `.glb` rackets are rendered in WebGL. A neural voiceover, a synthesised music bed and sound effects play underneath.

| Output | Command |
|---|---|
| English, 1920×1080, 60 fps | `npm run render` → `out/paladex-launch-en.mp4` |
| English without subtitles | `npm run render:nosubs` |
| Preview and edit in the browser | `npm run studio` |

The creative and technical contract is in [`BRIEF.md`](BRIEF.md).

## How it is built

1. **Voice and timing.** `npm run voice` runs `audio/make_vo.py`.
   - It reads the lines in `src/data/script.json`.
   - It generates the voice with Microsoft neural voices through `edge-tts`.
   - It writes `public/audio/vo/en/*.mp3` and `src/data/timeline.en.json`, which holds every scene's start and length and the frame of every spoken word.
   - Scene lengths snap to the 120 BPM beat grid, so cuts land on the music.
2. **Music and SFX.** `npm run music` runs `audio/make_music.py`. It synthesises `public/audio/music.en.wav`, arranged to the timeline, and the sound effects in `public/audio/sfx/`.
3. **Site footage.**
   - `capture/shots/<scene>.mjs` drives the real site at `http://localhost:3100` in headless Chrome through `capture/cdp.mjs`.
   - The page runs on a virtual clock that advances exactly 1/60 s per captured frame. The site's own 3D viewer therefore renders perfectly smooth 60 fps footage, whatever the machine speed.
   - Frames go to `public/capture/<scene>/`. They are git-ignored, so re-run the shot scripts to regenerate them.
   - The manifests are in `src/data/capture/<scene>.json`.
4. **Scenes.** There is one file per scene in `src/scenes/`, assembled in `src/Launch.tsx`.
   - Shared building blocks are in `src/components/`: `Browser3D`, `Cursor`, `Footage`, `Racket3D`, `Kinetic`, `Captions` and `Sfx`.

## Changing things

- **Words.** Edit `src/data/script.json`, run `npm run voice`, then `npm run music` (the timing may move), then render.
- **CTA text on the end card.** Edit the constants at the top of `src/scenes/EndCard.tsx`. No final domain is shown yet; add it there once you have one.
- **One scene only.**
  - Preview it: `node scripts/stills.mjs Dev out/<scene> 0-300/12 --entry src/dev/<scene>.tsx --sheet sheet.jpg`
- **Different voice.** Change `voice` in `src/data/script.json`. List the voices with `python -m edge_tts --list-voices`.
- **GPU.** Rendering uses `--gl=angle` (see `remotion.config.ts`). On a machine without a GPU, switch to `swangle`.

## Before publishing (from PRODUCT.md and `promo/script.md`)

- Check the "Paladex" trademark before paying for ads.
- Decide the final domain and add it to the end card.
- Get the photo licences: the brand photos used for the traced 3D models are marked "licence pending" on the site.
- Prices on the site are demo data. The ad never features them.
