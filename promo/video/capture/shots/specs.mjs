// Capture for scene 5 "specs": the hero racket page's Specification section.
//
//   node capture/shots/specs.mjs            (everything)
//   node capture/shots/specs.mjs stills     (page strip, header, row crops, hover)
//   node capture/shots/specs.mjs clip       (sticky 3D viewer clip with the "Show on model" click)
//
// On desktop the page's 3D viewer is sticky on the left while the right column
// scrolls. A full-page screenshot can't show that, so the scene rebuilds it from
// real layers, exactly as the browser composites them:
//   specs-page    the page between S0 and S2+1080 with the header and the sticky
//                 viewer hidden (dpr 2, stitched from viewport tiles, no layout change)
//   specs-header  the sticky site header (dpr 2)
//   specs-viewer  the sticky viewer card as a 60 fps clip (dpr 2): the racket in
//                 its hero pose, then "Show on model" on the Sweet spot row is clicked
//                 and the viewer flies to the front view with the sweet-spot overlay
//   specs-row-*   dpr 3 crops of the rows that lift out of the page
//   specs-sweet-hover  the Sweet spot row's "Show on model" button in hover state
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { launch, sleep, writeManifest } from "../cdp.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const DIR = "capture/specs";
const OUT = join(ROOT, "public", DIR);
const PAGE_URL = "http://localhost:3100/rackets/nox-at10-luxury-genius-18k-alum";
// No gesture hint (seen before), full-quality model and detail textures.
const PREP = `try{localStorage.setItem('paladex:hint-seen','1');localStorage.setItem('paladex:3d-quality','high')}catch(e){}`;

// Page.captureScreenshot `clip` is in DOCUMENT coordinates (not viewport).
// Document scroll positions the scene moves between (CSS px).
const S0 = 2560; // start: end of "Platform scores", "Specifications" heading below
const S2 = 3320; // furthest scroll: Shape … Sweet spot visible, "Where to buy" still below the fold
const STRIP_H = S2 + 1080 - S0;
const ROWS = { shape: "Shape", weight: "Weight", surface: "Surface", sweet: "Sweet spot" };
const LIFT = ["shape", "weight", "surface"];
const PADX = 22; // crop padding around a lifted row (CSS px)
const PADY = 8;

// The clip: the click lands on this capture frame (the scene maps its own click
// frame onto this one and holds frame 0 before). The viewer is idle in its hero
// pose until the click: with auto-rotate on, the site keeps turning after
// "Show on model" and the sweet-spot overlay spins edge-on, so it stays off.
const CLICK = 40;
const CLIP_FRAMES = CLICK + 130;

const what = process.argv[2] ?? "all";
mkdirSync(OUT, { recursive: true });

async function open(dpr) {
  const page = await launch({ width: 1920, height: 1080, dpr });
  await page.send("Page.addScriptToEvaluateOnNewDocument", { source: PREP });
  await page.goto(PAGE_URL, 3000);
  await page.waitFor("document.querySelector('canvas')", 60000);
  const c = await page.rect("canvas");
  // Hover the viewer to signal intent, let the full model + textures load.
  await page.mouse("mouseMoved", c.x + c.w / 2, c.y + c.h / 2);
  await sleep(10000);
  await page.mouse("mouseMoved", 1880, 1040);
  await page.revealAll();
  await sleep(500);
  return page;
}

/** Document-coordinate rects of the spec rows and their "Show on model" buttons, and the sticky viewer (viewport). */
const geometry = (page) =>
  page.eval(`(() => {
    const want = ${JSON.stringify(ROWS)};
    const rd = (r, dy) => ({ x: Math.round(r.x * 10) / 10, y: Math.round((r.y + dy) * 10) / 10, w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 });
    const out = {};
    const rows = [...document.getElementById('specs').closest('section').querySelectorAll('dl > div')];
    for (const k in want) {
      const d = rows.find((e) => (e.querySelector('dt')?.innerText || '').trim() === want[k]);
      if (!d) continue;
      out[k] = rd(d.getBoundingClientRect(), scrollY);
      const b = d.querySelector('button');
      if (b) out[k + 'Btn'] = rd(b.getBoundingClientRect(), scrollY);
    }
    out.heading = rd(document.getElementById('specs').getBoundingClientRect(), scrollY);
    const buy = document.getElementById('buy');
    if (buy) out.buy = rd(buy.getBoundingClientRect(), scrollY);
    let el = document.querySelector('canvas');
    while (el && getComputedStyle(el).position !== 'sticky') el = el.parentElement;
    window.__sticky = el;
    out.viewer = rd(el.getBoundingClientRect(), 0); // viewport coords (it is sticky)
    return out;
  })()`);

const setDpr = async (page, dpr) => {
  await page.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: dpr, mobile: false });
  await sleep(1200);
};

async function stills() {
  const page = await open(2);
  const fs = await import("node:fs");
  const save = async (file, clip, quality = 92) => {
    const res = await page.send("Page.captureScreenshot", { format: "jpeg", quality, ...(clip ? { clip: { ...clip, scale: 1 } } : {}) });
    fs.writeFileSync(join(OUT, file), Buffer.from(res.data, "base64"));
  };
  await page.scrollTo(S2);
  await sleep(600);
  const g = await geometry(page);
  console.log(JSON.stringify(g));
  if (g.buy && g.buy.y < S2 + 1080) console.warn("WARNING: 'Where to buy' heading inside the strip at", g.buy.y);

  // Header (sticky, solid once scrolled).
  await save("header.jpg", { x: 0, y: S2, width: 1920, height: 64 });
  // The translucent header has the row behind it (Collection AT10) baked in: paint it out.
  execFileSync("python", [join(ROOT, "capture/shots/specs-header-clean.py"), join(OUT, "header.jpg")], { stdio: "inherit" });

  // Hover state of the Sweet spot "Show on model" button (viewport coords at S2).
  const b = g.sweetBtn;
  await page.mouse("mouseMoved", b.x + b.w / 2, b.y - S2 + b.h / 2);
  await sleep(700);
  await save("sweet-hover.jpg", { x: b.x - 6, y: b.y - 6, width: b.w + 12, height: b.h + 12 });
  await page.mouse("mouseMoved", 1880, 1040);
  await sleep(700);

  // Page strip: hide the sticky header and the sticky viewer (they are layered
  // back in the scene), then stitch viewport tiles. Layout doesn't change.
  await page.eval(`(() => { document.querySelector('header').style.visibility = 'hidden'; window.__sticky.style.visibility = 'hidden'; return true; })()`);
  const tiles = [];
  for (let y = S0, i = 0; y < S0 + STRIP_H; y += 1080, i++) {
    await page.scrollTo(y);
    await sleep(1500);
    const real = await page.eval("scrollY");
    if (Math.abs(real - y) > 0.5) throw new Error(`scroll ${y} landed at ${real}`);
    const f = join(OUT, `_tile${i}.png`);
    // On a busy machine (software raster) the compositor can still show stale tiles
    // from the previous scroll position: shoot until two shots in a row match.
    let res = await page.send("Page.captureScreenshot", { format: "png" });
    for (let k = 0; k < 10; k++) {
      await sleep(700);
      const again = await page.send("Page.captureScreenshot", { format: "png" });
      if (again.data === res.data) break;
      res = again;
    }
    fs.writeFileSync(f, Buffer.from(res.data, "base64"));
    tiles.push([f, (y - S0) * 2]);
  }
  const py = `
import sys, json
from PIL import Image
out, h, tiles = sys.argv[1], int(sys.argv[2]), json.loads(sys.argv[3])
im = Image.new("RGB", (3840, h))
for f, y in tiles:
    im.paste(Image.open(f).convert("RGB"), (0, y))
im.save(out, quality=92)
`;
  execFileSync("python", ["-c", py, join(OUT, "page.jpg"), String(STRIP_H * 2), JSON.stringify(tiles)], { stdio: "inherit" });
  for (const [f] of tiles) rmSync(f);

  // Lifted rows at dpr 3 (crisp when they come toward the camera). The body's
  // faint jigsaw texture is switched off for these crops only: at 2.5x it turns
  // into busy lines behind the text. The row itself is untouched.
  await setDpr(page, 3);
  await page.eval(`(() => { const s = document.createElement('style'); s.textContent = 'body{background-image:none!important}'; document.head.appendChild(s); return true; })()`);
  await sleep(300);
  const rows = {};
  for (const k of LIFT) {
    const r = g[k];
    const top = Math.round(r.y) - 420;
    await page.scrollTo(top);
    await sleep(500);
    const clip = { x: Math.round(r.x) - PADX, y: Math.round(r.y) - PADY, width: Math.round(r.w) + PADX * 2, height: Math.round(r.h) + PADY * 2 };
    await save(`row-${k}.jpg`, clip, 94);
    rows[`specs-row-${k}`] = {
      file: `${DIR}/row-${k}.jpg`,
      width: clip.width,
      height: clip.height,
      dpr: 3,
      // crop: the crop's document rect; btn: the row's "Show on model" button (document)
      marks: { crop: { x: clip.x, y: clip.y, w: clip.width, h: clip.height }, row: r, ...(g[k + "Btn"] ? { btn: g[k + "Btn"] } : {}) },
    };
  }
  await page.close();

  writeManifest("specs", {
    stills: {
      // The page strip covers document y S0 … S0+height. marks are DOCUMENT coords,
      // except `viewer` (the sticky card, viewport coords). `scroll` = { y: S0, h: S2 }.
      "specs-page": {
        file: `${DIR}/page.jpg`,
        width: 1920,
        height: STRIP_H,
        dpr: 2,
        marks: {
          scroll: { x: 0, y: S0, w: 0, h: S2 },
          heading: g.heading,
          viewer: g.viewer,
          shape: g.shape,
          weight: g.weight,
          surface: g.surface,
          sweet: g.sweet,
          shapeBtn: g.shapeBtn,
          surfaceBtn: g.surfaceBtn,
          sweetBtn: g.sweetBtn,
        },
      },
      "specs-header": { file: `${DIR}/header.jpg`, width: 1920, height: 64, dpr: 2 },
      "specs-sweet-hover": {
        file: `${DIR}/sweet-hover.jpg`,
        width: Math.round(b.w) + 12,
        height: Math.round(b.h) + 12,
        dpr: 2,
        marks: { crop: { x: b.x - 6, y: b.y - 6, w: b.w + 12, h: b.h + 12 } },
      },
      ...rows,
    },
  });
  console.log("stills done");
}

async function viewerClip() {
  const dpr = 2;
  const page = await open(dpr);
  await page.scrollTo(S2);
  await sleep(800);
  const g = await geometry(page);
  const v = g.viewer;
  const b = g.sweetBtn;
  const bx = b.x + b.w / 2;
  const by = b.y - S2 + b.h / 2;
  console.log("viewer", v, "sweet btn", b);
  await sleep(1500);
  await page.freeze();
  const dir = join(OUT, "viewer");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const fs = await import("node:fs");
  const clip = { x: v.x, y: v.y + S2, width: v.w, height: v.h, scale: 1 };
  // CSS transitions run on real time: slow them to match the virtual clock.
  let t0 = Date.now();
  for (let f = 0; f < CLIP_FRAMES; f++) {
    if (f === 6) {
      const ms = (Date.now() - t0) / 6;
      const rate = Math.min(1, 1000 / 60 / ms);
      console.log(`~${ms.toFixed(0)} ms per frame, CSS animation rate ${rate.toFixed(3)}`);
      await page.setAnimationRate(rate);
    }
    if (f === CLICK - 24) await page.mouse("mouseMoved", bx, by);
    // The viewer renders on demand and has been idle since before freeze(), so R3F's
    // clock would hand camera-controls the whole idle time as one delta on the first
    // frame after the click: the camera snaps to the front view instead of gliding.
    // A scroll event wakes the viewer once (its scroll-settle listener invalidates
    // 160 ms later, i.e. on step CLICK - 2) without moving anything, so the click
    // starts from a fresh 1/60 s delta and the site's own glide plays out.
    if (f === CLICK - 11) await page.eval(`window.dispatchEvent(new Event('scroll')), true`);
    if (f === CLICK) {
      await page.mouse("mousePressed", bx, by, { button: "left", buttons: 1, clickCount: 1 });
      await page.mouse("mouseReleased", bx, by, { button: "left", buttons: 0, clickCount: 1 });
    }
    await page.step(1000 / 60);
    const res = await page.send("Page.captureScreenshot", { format: "jpeg", quality: 90, clip });
    fs.writeFileSync(join(dir, `f${String(f).padStart(5, "0")}.jpg`), Buffer.from(res.data, "base64"));
    if (f % 60 === 0) console.log(`  viewer ${f}/${CLIP_FRAMES}`);
  }
  console.log(page.logs.slice(0, 8).join("\n"));
  await page.close();
  writeManifest("specs", {
    clips: {
      "specs-viewer": {
        dir: `${DIR}/viewer`,
        frames: CLIP_FRAMES,
        fps: 60,
        width: Math.round(v.w),
        height: Math.round(v.h),
        dpr,
        // the click on the Sweet spot row's "Show on model" (page viewport coords at scroll S2)
        events: [{ type: "click", frame: CLICK, x: Math.round(bx * 10) / 10, y: Math.round(by * 10) / 10, label: "Show on model (Sweet spot)" }],
      },
    },
  });
  console.log("clip done");
}

if (what === "all" || what === "stills") await stills();
if (what === "all" || what === "clip") await viewerClip();
