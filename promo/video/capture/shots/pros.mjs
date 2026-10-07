// Scene 7 "pros": the real /pros page.
//
//   CHROME_EXTRA_ARGS="--disable-gpu-rasterization" node capture/shots/pros.mjs
//
// Produces (all dpr 2, CSS px sizes in the manifest):
//  - stills `pros-card-<slug>`: each pro entry (the "01 Player" label + the racket card, cut
//    just below the "played by" line so the price row stays out of frame). Unfinished
//    rackets are hidden by cdp.mjs and skipped here.
//  - still `pros-head`: breadcrumb, title and the page's own caveat paragraph ("Players are
//    matched to rackets from public lists as of early 2026; ...").
//  - stills `pros-men` / `pros-women`: the tour headings.
// The cards show the site's own racket posters ("Interactive 3D available"); the scene
// adds the real .glb model of the landing pro on top.
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { launch, sleep, writeManifest } from "../cdp.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const DIR = join(ROOT, "public", "capture", "pros");
mkdirSync(join(DIR, "cards"), { recursive: true });

const page = await launch({ width: 1920, height: 1080, dpr: 2 });
await page.goto("http://localhost:3100/pros", 5000);
await page.revealAll();
await page.mouse("mouseMoved", 5, 5);

// Load every lazy poster by scrolling through the page.
const H = await page.eval("document.documentElement.scrollHeight");
for (let y = 0; y < H; y += 500) {
  await page.scrollTo(y);
  await sleep(500);
}
await page.waitFor(`[...document.querySelectorAll("ol section img, section ol img")].every((i) => i.complete && i.naturalWidth > 0)`, 60000);
await sleep(1500);

const cards = await page.eval(`(() => [...document.querySelectorAll("section ol > li")].map((li) => {
  const a = li.querySelector("h3 a");
  const who = li.querySelector("p.mb-3 .title")?.textContent.trim();
  const played = li.querySelector("p.mt-2");
  const r = li.getBoundingClientRect();
  const pr = played?.getBoundingClientRect();
  const tour = li.closest("section").id;
  return { who, tour, slug: a?.getAttribute("href")?.split("/").pop(), name: a?.textContent.trim(), x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: pr ? pr.bottom + scrollY + 14 - (r.y + scrollY) : r.height, vis: r.width > 0 };
}))()`);

const stills = {};
const meta = [];
for (const c of cards) {
  if (!c.vis || !c.slug) continue;
  const key = `pros-card-${c.slug}`;
  await page.scrollTo(Math.max(0, c.y - 200));
  await sleep(500);
  const sy = await page.eval("scrollY");
  const file = join(DIR, "cards", `${c.slug}.jpg`);
  await page.screenshot(file, { quality: 93, clip: { x: c.x, y: c.y, width: c.w, height: c.h } });
  stills[key] = { file: `capture/pros/cards/${c.slug}.jpg`, width: Math.round(c.w), height: Math.round(c.h), dpr: 2 };
  meta.push({ key, who: c.who, tour: c.tour, name: c.name });
  console.log("card", c.tour, c.who, "→", c.name, sy);
}

// Headings.
await page.scrollTo(0);
await sleep(500);
await page.eval(`(() => { const p = document.querySelector("h1").parentElement.nextElementSibling; p.id = "pros-intro"; return true; })()`);
const marks = await page.marks({ h1: "h1", intro: "#pros-intro", men: "#men h2", women: "#women h2" });
console.log(marks);
const head = { x: 270, y: 60, w: 1380, h: 0 };
head.h = marks.intro.y + marks.intro.h + 24 - head.y;
await page.screenshot(join(DIR, "head.jpg"), { quality: 94, clip: { x: head.x, y: head.y, width: head.w, height: head.h } });
stills["pros-head"] = { file: "capture/pros/head.jpg", width: head.w, height: head.h, dpr: 2, marks };
for (const k of ["men", "women"]) {
  await page.scrollTo(Math.max(0, marks[k].y - 300));
  await sleep(400);
  const sy = await page.eval("scrollY");
  void sy;
  const b = (await page.marks({ t: `#${k} h2` })).t;
  await page.screenshot(join(DIR, `${k}.jpg`), { quality: 94, clip: { x: b.x - 4, y: b.y - 4, width: b.w + 8, height: b.h + 8 } });
  stills[`pros-${k}`] = { file: `capture/pros/${k}.jpg`, width: b.w + 8, height: b.h + 8, dpr: 2 };
}
stills["pros-index"] = { file: "", width: 0, height: 0, dpr: 1, marks: { order: meta } };
delete stills["pros-index"];
writeManifest("pros", { stills });
import { writeFileSync } from "node:fs";
writeFileSync(join(ROOT, "src", "scenes", "pros", "cards.json"), JSON.stringify(meta, null, 1));
console.log(page.logs.slice(0, 5).join("\n"));
await page.close();

// Macro still (dpr 4): the info block of Tapia's card (maker, name, shape, "played by" line).
{
  const p4 = await launch({ width: 1920, height: 1080, dpr: 4 });
  await p4.goto("http://localhost:3100/pros", 5000);
  await p4.revealAll();
  await p4.mouse("mouseMoved", 5, 5);
  await p4.scrollTo(300);
  await p4.waitFor(`document.querySelector("section ol > li img")?.complete`, 60000);
  await sleep(1200);
  const b = await p4.eval(`(() => { const li = document.querySelector("section ol > li"); const a = li.querySelector("p.label").getBoundingClientRect(); const pl = li.querySelector("p.mt-2").getBoundingClientRect(); const c = li.querySelector("article").getBoundingClientRect(); return { x: c.x + scrollX, y: a.y + scrollY - 14, w: c.width, h: pl.bottom - a.y + 28 }; })()`);
  await p4.screenshot(join(DIR, "tapia-info.jpg"), { quality: 94, clip: { x: b.x, y: b.y, width: b.w, height: b.h } });
  writeManifest("pros", { stills: { "pros-tapia-info": { file: "capture/pros/tapia-info.jpg", width: Math.round(b.w), height: Math.round(b.h), dpr: 4 } } });
  console.log("macro", b);
  await p4.close();
}
