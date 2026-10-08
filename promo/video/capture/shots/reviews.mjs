// Capture for scene 6 "reviews": the hero racket page's "What reviewers say" section.
//
//   node capture/shots/reviews.mjs          (everything)
//   node capture/shots/reviews.mjs stills   (page strip, header, viewer still, crops, hover states)
//   node capture/shots/reviews.mjs clip     (sticky viewer clip, racket auto-turning)
//
// Like the specs capture: the page strip has the sticky header and viewer hidden and
// they are layered back in the scene. Crops (dpr 3) are the pieces that lift out.
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { launch, sleep, writeManifest } from "../cdp.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const DIR = "capture/reviews";
const OUT = join(ROOT, "public", DIR);
const PAGE_URL = "http://localhost:3100/rackets/nox-at10-luxury-genius-18k-alum";
const PREP = `try{localStorage.setItem('paladex:hint-seen','1');localStorage.setItem('paladex:3d-quality','high')}catch(e){}`;

const S0 = 1480; // strip top (document y): just above the section title
const S2 = 1700; // furthest scroll (sources in view)
const STRIP_H = S2 + 1080 - S0;
const CROP_DPR = 4;
const PADX = 22;
const PADY = 10;
const CLIP_FRAMES = 240;

const what = process.argv[2] ?? "all";
mkdirSync(OUT, { recursive: true });

async function open(dpr) {
  const page = await launch({ width: 1920, height: 1080, dpr });
  await page.send("Page.addScriptToEvaluateOnNewDocument", { source: PREP });
  await page.goto(PAGE_URL, 3000);
  await page.waitFor("document.querySelector('canvas')", 60000);
  const c = await page.rect("canvas");
  await page.mouse("mouseMoved", c.x + c.w / 2, c.y + c.h / 2);
  await sleep(10000);
  await page.mouse("mouseMoved", 1880, 1040);
  await page.revealAll();
  await sleep(500);
  return page;
}

const geometry = (page) =>
  page.eval(`(() => {
    const rd = (r, dy = 0) => ({ x: Math.round(r.x * 10) / 10, y: Math.round((r.y + dy) * 10) / 10, w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 });
    const sec = document.getElementById('reviews');
    const a = sec.querySelector('article');
    const k = [...a.children];
    const out = {};
    out.title = rd(document.getElementById('reviews-title').getBoundingClientRect(), scrollY);
    out.badges = rd(k[0].getBoundingClientRect(), scrollY);
    out.summary = rd(k[1].getBoundingClientRect(), scrollY);
    out.lists = rd(k[2].getBoundingClientRect(), scrollY);
    out.suits = rd(k[3].getBoundingClientRect(), scrollY);
    out.read = rd(k[4].getBoundingClientRect(), scrollY);
    out.sources = rd(k[5].getBoundingClientRect(), scrollY);
    const links = [...a.querySelectorAll('a')];
    out.links = links.map((l) => ({ name: l.innerText.replace(/\\(opens.*\\)/, '').trim(), href: l.href, ...rd(l.getBoundingClientRect(), scrollY) }));
    out.section = rd(sec.getBoundingClientRect(), scrollY);
    let el = document.querySelector('canvas');
    while (el && getComputedStyle(el).position !== 'sticky') el = el.parentElement;
    window.__sticky = el;
    out.viewer = rd(el.getBoundingClientRect(), 0);
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
  await sleep(800);
  const g = await geometry(page);
  console.log(JSON.stringify(g));
  await save("header.jpg", { x: 0, y: S2, width: 1920, height: 64 });
  // viewer still (hero pose) at the S2 scroll
  await save("viewer.jpg", { x: g.viewer.x, y: g.viewer.y + S2, width: g.viewer.w, height: g.viewer.h });

  // hover states of the source pills
  const hovers = {};
  for (let i = 0; i < g.links.length; i++) {
    const l = g.links[i];
    await page.mouse("mouseMoved", l.x + l.w / 2, l.y - S2 + l.h / 2);
    await sleep(700);
    const clip = { x: l.x - 6, y: l.y - 6, width: l.w + 12, height: l.h + 12 };
    await save(`link-hover-${i}.jpg`, clip, 94);
    hovers[`reviews-link-hover-${i}`] = { file: `${DIR}/link-hover-${i}.jpg`, width: clip.width, height: clip.height, dpr: 2, marks: { crop: { x: clip.x, y: clip.y, w: clip.width, h: clip.height }, link: l } };
  }
  await page.mouse("mouseMoved", 1880, 1040);
  await sleep(700);

  // page strip (header and viewer hidden), stitched from viewport tiles
  await page.eval(`(() => { document.querySelector('header').style.visibility = 'hidden'; window.__sticky.style.visibility = 'hidden'; return true; })()`);
  const tiles = [];
  for (let y = S0, i = 0; y < S0 + STRIP_H; y += 1080, i++) {
    await page.scrollTo(y);
    await sleep(1500);
    const real = await page.eval("scrollY");
    if (Math.abs(real - y) > 0.5) throw new Error(`scroll ${y} landed at ${real}`);
    const f = join(OUT, `_tile${i}.png`);
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
  execFileSync("python3", ["-c", py, join(OUT, "page.jpg"), String(STRIP_H * 2), JSON.stringify(tiles)], { stdio: "inherit" });
  for (const [f] of tiles) rmSync(f);

  // crops at dpr 3 (no jigsaw texture behind the text)
  await setDpr(page, CROP_DPR);
  await page.eval(`(() => { document.querySelector('header').style.visibility = ''; const s = document.createElement('style'); s.textContent = 'body{background-image:none!important}'; document.head.appendChild(s); return true; })()`);
  await sleep(300);
  const crops = {};
  const pieces = { title: [g.title, g.badges], summary: [g.summary], lists: [g.lists], read: [g.read], sources: [g.sources] };
  for (const [k, rs] of Object.entries(pieces)) {
    const x0 = Math.min(...rs.map((r) => r.x));
    const y0 = Math.min(...rs.map((r) => r.y));
    const x1 = Math.max(...rs.map((r) => r.x + r.w));
    const y1 = Math.max(...rs.map((r) => r.y + r.h));
    const r = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    await page.scrollTo(Math.round(r.y) - 420);
    await sleep(500);
    const clip = { x: Math.round(r.x) - PADX, y: Math.round(r.y) - PADY, width: Math.round(r.w) + PADX * 2, height: Math.round(r.h) + PADY * 2 };
    await save(`crop-${k}.jpg`, clip, 94);
    crops[`reviews-crop-${k}`] = { file: `${DIR}/crop-${k}.jpg`, width: clip.width, height: clip.height, dpr: CROP_DPR, marks: { crop: { x: clip.x, y: clip.y, w: clip.width, h: clip.height }, row: r } };
  }
  await page.close();

  writeManifest("reviews", {
    stills: {
      "reviews-page": {
        file: `${DIR}/page.jpg`, width: 1920, height: STRIP_H, dpr: 2,
        marks: { scroll: { x: 0, y: S0, w: 0, h: S2 }, viewer: g.viewer, title: g.title, summary: g.summary, lists: g.lists, read: g.read, sources: g.sources, link0: g.links[0], link1: g.links[1] },
      },
      "reviews-header": { file: `${DIR}/header.jpg`, width: 1920, height: 64, dpr: 2 },
      "reviews-viewer": { file: `${DIR}/viewer.jpg`, width: Math.round(g.viewer.w), height: Math.round(g.viewer.h), dpr: 2 },
      ...hovers,
      ...crops,
    },
  });
  writeFileSync(join(OUT, "links.json"), JSON.stringify(g.links, null, 1));
  console.log("stills done");
}

async function viewerClip() {
  const dpr = 1.5;
  const page = await open(dpr);
  await page.scrollTo(S2);
  await sleep(800);
  const g = await geometry(page);
  const v = g.viewer;
  await sleep(1500);
  await page.freeze();
  const dir = join(OUT, "viewer");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const fs = await import("node:fs");
  const clip = { x: v.x, y: v.y + S2, width: v.w, height: v.h, scale: 1 };
  for (let f = 0; f < CLIP_FRAMES; f++) {
    await page.step(1000 / 60);
    const res = await page.send("Page.captureScreenshot", { format: "jpeg", quality: 90, clip });
    fs.writeFileSync(join(dir, `f${String(f).padStart(5, "0")}.jpg`), Buffer.from(res.data, "base64"));
    if (f % 60 === 0) console.log(`  viewer ${f}/${CLIP_FRAMES}`);
  }
  await page.close();
  writeManifest("reviews", {
    clips: { "reviews-viewer": { dir: `${DIR}/viewer`, frames: CLIP_FRAMES, fps: 60, width: Math.round(v.w), height: Math.round(v.h), dpr } },
  });
  console.log("clip done");
}

if (what === "all" || what === "stills") await stills();
if (what === "all" || what === "clip") await viewerClip();
