// Scene 7 "brands": the real /rackets page (brand rail + racket grid).
//
//   node capture/shots/brands.mjs
//
// Produces
//  - clip `brands-rail` (1920x1080, dpr 1, 60 fps): the page at the top, the cursor comes
//    down onto the Nox tile and clicks it at clip frame CLICK; the grid filters to Nox.
//    One clip serves both languages: the scene maps CLICK onto a word-derived frame.
//    CSS transitions/animations (tile hover, active tile, "Nox rackets" rise) run on real
//    time in Chrome, so every frame we pause them and seek them to the virtual clock:
//    the footage is frame-exact.
//  - stills `brands-tile-<slug>` (dpr 2 crops of each rail tile's logo card) so the 3D
//    brand plates in the scene are pixel-identical to the site's tiles they land on.
//  - marks (page CSS px, scroll 0, "All" selected): each tile's logo card, the
//    "62 rackets" count and the first row of racket cards.
//  - still `brands-plate` (dpr 1, scroll 0): the same page with the brands' logo cards
//    hidden (empty slots in the rail tiles). The scene lays the rail strip of it over the
//    footage until the flying logo cards land in their slots.
//
// PARTS=tiles,clip,plate (default: all) runs only some parts, e.g. PARTS=plate.
// Run with CHROME_EXTRA_ARGS="--disable-gpu-rasterization" on GPU-less machines (CPU
// raster: SwiftShader raster can return stale tiles under load).
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { launch, packCursor, record, sleep, writeManifest } from "../cdp.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const URL_ = "http://localhost:3100/rackets";
const CLIP = "brands-rail";
const DIR = join(ROOT, "public", "capture", "brands", "rail");
const TILES_DIR = join(ROOT, "public", "capture", "brands", "tiles");
const FRAMES = Number(process.env.FRAMES ?? 210);
const CLICK = 84; // clip frame of the click on Nox

const RAIL = "[role=radiogroup][aria-label=Brands]";

// Pause every CSS animation/transition and seek it to the virtual clock.
const SYNC = `window.__syncAnims = () => {
  const now = window.__vt.now;
  for (const a of document.getAnimations()) {
    if (a.__t0 === undefined) { a.__t0 = now; try { a.pause(); } catch {} }
    try { a.currentTime = Math.max(0, now - a.__t0); } catch {}
  }
  return true;
}; true`;

const tileInfo = (page) =>
  page.eval(`(() => {
    const rail = document.querySelector(${JSON.stringify(RAIL)});
    return [...rail.children].map((el, i) => {
      const card = el.querySelector('.card-sky');
      const r = card.getBoundingClientRect();
      const t = el.getBoundingClientRect();
      const name = el.querySelector('.title')?.textContent.trim() ?? '';
      const count = el.querySelector('.num')?.textContent.trim() ?? '';
      return { i, name, count, card: { x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height }, tile: { x: t.x + scrollX, y: t.y + scrollY, w: t.width, h: t.height } };
    });
  })()`);

const slugOf = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

const PARTS = new Set((process.env.PARTS ?? "tiles,clip,plate").split(","));

// ---------------------------------------------------------------------------------
// 0) Clean plate: the page at scroll 0 with the rail's tiles hidden.
if (PARTS.has("plate")) {
  const page = await launch({ width: 1920, height: 1080, dpr: 1 });
  await page.goto(URL_, 5000);
  await page.waitFor(`document.querySelectorAll('${RAIL} > *').length > 5`, 60000);
  await page.mouse("mouseMoved", 1012, 168);
  await sleep(2500);
  // Hide only the brands' logo cards: the tiles' frames, names and counts and the
  // "All" tile stay, so the cards land into their own empty slots.
  await page.eval(`(() => { [...document.querySelector(${JSON.stringify(RAIL)}).children].slice(1).forEach((el) => { const c = el.querySelector('.card-sky'); if (c) c.style.visibility = 'hidden'; }); return true; })()`);
  await sleep(800);
  const file = join(ROOT, "public", "capture", "brands", "plate.jpg");
  await page.screenshot(file, { quality: 95 });
  writeManifest("brands", { stills: { "brands-plate": { file: "capture/brands/plate.jpg", width: 1920, height: 1080, dpr: 1 } } });
  console.log("plate", file);
  await page.close();
}

// ---------------------------------------------------------------------------------
// 1) Tile crops at dpr 2.
if (PARTS.has("tiles")) {
  mkdirSync(TILES_DIR, { recursive: true });
  const page = await launch({ width: 1920, height: 1080, dpr: 2 });
  await page.goto(URL_, 5000);
  await page.waitFor(`document.querySelectorAll('${RAIL} > *').length > 5`, 60000);
  await page.mouse("mouseMoved", 1700, 200);
  await sleep(1500);
  const stills = {};
  // Scroll the rail so every tile is inside its visible box once.
  for (const left of [0, 2000]) {
    await page.eval(`document.querySelector(${JSON.stringify(RAIL)}).scrollLeft = ${left}, true`);
    await sleep(900);
    const railBox = await page.rect(RAIL);
    const tiles = await tileInfo(page);
    for (const t of tiles) {
      if (t.i === 0) continue; // "All"
      const slug = slugOf(t.name);
      if (stills[`brands-tile-${slug}`]) continue;
      const c = t.card;
      if (c.x < railBox.x - 0.5 || c.x + c.w > railBox.x + railBox.w + 0.5) continue;
      const file = join(TILES_DIR, `${slug}.jpg`);
      await page.screenshot(file, { quality: 94, clip: { x: c.x, y: c.y, width: c.w, height: c.h } });
      stills[`brands-tile-${slug}`] = { file: `capture/brands/tiles/${slug}.jpg`, width: Math.round(c.w), height: Math.round(c.h), dpr: 2 };
      console.log("tile", slug, t.count);
    }
  }
  writeManifest("brands", { stills });
  console.log(page.logs.slice(0, 5).join("\n"));
  await page.close();
}

// ---------------------------------------------------------------------------------
// 2) The page clip.
if (PARTS.has("clip")) {
  const page = await launch({ width: 1920, height: 1080, dpr: 1 });
  await page.goto(URL_, 5000);
  await page.waitFor(`document.querySelectorAll('${RAIL} > *').length > 5`, 60000);
  const REST = { x: 1012, y: 168 };
  await page.mouse("mouseMoved", REST.x, REST.y);
  await sleep(1200);

  const tiles = await tileInfo(page);
  const nox = tiles.find((t) => t.name === "Nox");
  const all = tiles[0];
  if (!nox) throw new Error("no Nox tile");

  // Warm the Nox posters (first row after filtering), then go back to "All".
  await page.click(nox.tile.x + nox.tile.w / 2, nox.tile.y + 80);
  await sleep(3500);
  await page.click(all.tile.x + all.tile.w / 2, all.tile.y + 80);
  await sleep(1500);
  await page.mouse("mouseMoved", REST.x, REST.y);
  await sleep(2500);

  // Marks at scroll 0 with "All" selected (doc coords == viewport coords at scroll 0).
  const marksTiles = Object.fromEntries((await tileInfo(page)).map((t) => [t.i === 0 ? "card-all" : `card-${slugOf(t.name)}`, { x: Math.round(t.card.x * 10) / 10, y: Math.round(t.card.y * 10) / 10, w: Math.round(t.card.w), h: Math.round(t.card.h) }]));
  const extra = await page.eval(`(() => {
    const out = {};
    const p = [...document.querySelectorAll('p')].find((el) => /\\brackets\\b/.test(el.textContent) && el.querySelector('.num'));
    if (p) { const r = p.querySelector('.num').getBoundingClientRect(); out['count-num'] = { x: r.x, y: r.y, w: r.width, h: r.height }; const q = p.getBoundingClientRect(); out['count-line'] = { x: q.x, y: q.y, w: q.width, h: q.height }; }
    const rail = document.querySelector(${JSON.stringify(RAIL)}).getBoundingClientRect();
    out['rail'] = { x: rail.x, y: rail.y, w: rail.width, h: rail.height };
    [...document.querySelectorAll('ul.grid > li')].slice(0, 3).forEach((li, i) => { const r = li.querySelector('.card-sky').getBoundingClientRect(); out['racket-' + i] = { x: r.x, y: r.y, w: r.width, h: r.height }; });
    const h1 = document.querySelector('h1').getBoundingClientRect();
    out['title'] = { x: h1.x, y: h1.y, w: h1.width, h: h1.height };
    return out;
  })()`);
  const marks = { ...marksTiles };
  for (const [k, r] of Object.entries(extra)) marks[k] = { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h) };
  console.log("marks", JSON.stringify(marks));

  await page.eval(SYNC);
  await page.freeze();

  // Cursor: rests in the paragraph area, glides down onto the Nox tile, clicks, then
  // drifts a little toward the new heading. Positions in page CSS px.
  const target = { x: nox.tile.x + nox.tile.w * 0.5 + 6, y: nox.tile.y + 92 };
  const after = { x: target.x + 70, y: target.y + 150 };
  const ease = (t) => (t < 0.5 ? 8 * t ** 4 : 1 - (-2 * t + 2) ** 4 / 2); // in-out quart
  const smooth = (t) => t * t * (3 - 2 * t);
  const MOVE_A = 18;
  const MOVE_B = CLICK - 8;
  const pos = (f) => {
    if (f <= MOVE_B) {
      const t = ease(Math.min(1, Math.max(0, (f - MOVE_A) / (MOVE_B - MOVE_A))));
      const dx = target.x - REST.x;
      const dy = target.y - REST.y;
      const arc = Math.sin(t * Math.PI) * 26;
      return { x: REST.x + dx * t + arc, y: REST.y + dy * t };
    }
    if (f <= CLICK + 34) {
      // tiny settle into the press
      const t = smooth(Math.min(1, (f - MOVE_B) / 8));
      return { x: target.x - 2 * t, y: target.y + 3 * t };
    }
    const t = ease(Math.min(1, (f - CLICK - 34) / 90));
    const s = { x: target.x - 2, y: target.y + 3 };
    return { x: s.x + (after.x - s.x) * t, y: s.y + (after.y - s.y) * t };
  };

  const events = [];
  const track = await record(page, {
    dir: DIR,
    frames: FRAMES,
    quality: 90,
    script: async (f, t, api) => {
      const p = pos(f);
      const down = f >= CLICK && f < CLICK + 4;
      api.cursor(p.x, p.y, down);
      if (f === CLICK) {
        await page.mouse("mouseMoved", p.x, p.y);
        await page.mouse("mousePressed", p.x, p.y, { button: "left", buttons: 1, clickCount: 1 });
        events.push({ type: "click", frame: f, x: p.x, y: p.y, label: "Nox" });
      } else if (f === CLICK + 4) {
        await page.mouse("mouseReleased", p.x, p.y, { button: "left", buttons: 0, clickCount: 1 });
      } else {
        await page.mouse("mouseMoved", p.x, p.y, { buttons: down ? 1 : 0 });
      }
      await page.eval("window.__syncAnims()");
    },
  });

  writeManifest("brands", {
    clips: { [CLIP]: { dir: "capture/brands/rail", frames: FRAMES, fps: 60, width: 1920, height: 1080, dpr: 1, cursor: packCursor(track), events } },
    stills: { "brands-page": { file: "capture/brands/rail/f00000.jpg", width: 1920, height: 1080, dpr: 1, marks } },
  });
  console.log(page.logs.slice(0, 10).join("\n"));
  await page.close();
}
