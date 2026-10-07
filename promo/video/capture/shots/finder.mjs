// Scene 6 "finder": the real "Find my racket" flow, captured as
//  - dpr-2 stills of the home page's "Not sure where to start?" card (the deck cover)
//    and of each quiz question card (base / hover / selected states), with the
//    option boxes relative to each card for the cursor,
//  - 60 fps footage of the results view (3D viewer turning on the virtual clock).
//
// Answers (an intermediate, all-round player; the top match has an interactive model):
//   intermediate · balanced · control · teardrop · medium · no limit · no arm pain · current: none
//
// usage: node capture/shots/finder.mjs [stills|crops|footage|all]
// On a loaded Linux box, shoot with CPU raster (GPU raster can return stale tiles):
//   CHROME_EXTRA_ARGS="--disable-gpu-rasterization" node capture/shots/finder.mjs all
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { launch, record, sleep, writeManifest } from "../cdp.mjs";

// Headless Chrome reports `(hover: none)` and no fine pointer, so the site's hover
// styles (Tailwind `hover:` is gated on `@media (hover: hover)`) never show. Report a
// desktop mouse, like a real visitor's browser.
const DESKTOP_POINTER = "--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4";
process.env.CHROME_EXTRA_ARGS = [process.env.CHROME_EXTRA_ARGS, DESKTOP_POINTER].filter(Boolean).join(" ");

const SCENE = "finder";
const BASE = "http://localhost:3100";
const PUB = fileURLToPath(new URL("../../public/", import.meta.url));
const what = process.argv[2] ?? "all";

const ANSWERS = [
  ["level", "intermediate", "Intermediate"],
  ["game", "balanced", "Balanced"],
  ["priority", "control", "Control"],
  ["shape", "teardrop", "Teardrop"],
  ["weight", "medium", "Medium"],
  ["budget", "none", "No limit"],
  ["armCare", "no", "No"],
];
const qs = (n) => ANSWERS.slice(0, n).map(([k, v]) => `${k}=${v}`).join("&");
const RESULTS_URL = `${BASE}/finder?${qs(7)}&current=none`;

/** Box of `sel` (or of the element whose text is `text`) relative to `cardSel`, CSS px. */
const relBox = (page, cardSel, sel, text) =>
  page.eval(`(() => {
    const card = document.querySelector(${JSON.stringify(cardSel)});
    const c = card.getBoundingClientRect();
    let el = null;
    if (${JSON.stringify(text ?? null)}) {
      el = [...card.querySelectorAll(${JSON.stringify(sel)})].find((e) => (e.innerText || "").trim().split("\\n")[0].trim() === ${JSON.stringify(text ?? "")});
    } else el = card.querySelector(${JSON.stringify(sel)});
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x - c.x), y: Math.round(r.y - c.y), w: Math.round(r.width), h: Math.round(r.height) };
  })()`);

/** Document-coordinate box of a selector. */
const docBox = async (page, sel) => (await page.marks({ el: sel })).el;

async function shotCard(page, file, box) {
  await page.screenshot(join(PUB, file), { quality: 92, clip: { x: box.x, y: box.y, width: box.w, height: box.h } });
}

/** Same scroll as the results footage, so crop marks line up with the clip. */
const RESULTS_SCROLL = 70;

/** dpr-2 crops of the results page for lift-outs, with their box in the footage frame. */
async function resultCrops(page) {
  const out = {};
  await page.goto(`${BASE}/`, 1500);
  await page.eval(`localStorage.setItem("paladex:hint-seen", "1"), true`);
  await page.goto(RESULTS_URL, 4000);
  await page.waitFor("document.querySelector('canvas')", 60000);
  await sleep(9000);
  await page.mouse("mouseMoved", 1880, 140);
  await page.scrollTo(RESULTS_SCROLL);
  await sleep(1200);
  const rm = await page.marks({
    badge: ".bg-ball.px-4",
    matches: 'ol[aria-label="All matches"]',
    plate: ".plate",
    reasons: ".plate .mt-4",
  });
  console.log("results crops", rm);
  for (const [name, b] of Object.entries(rm)) {
    const file = `capture/${SCENE}/${name}.jpg`;
    await page.screenshot(join(PUB, file), { quality: 92, clip: { x: b.x, y: b.y, width: b.w, height: b.h } });
    // `frame`: the same box in the footage frame (page scrolled by RESULTS_SCROLL).
    out[`${SCENE}-${name}`] = { file, width: b.w, height: b.h, dpr: 2, marks: { frame: { ...b, y: b.y - RESULTS_SCROLL } } };
  }
  return out;
}

async function stills() {
  const dir = join(PUB, "capture", SCENE);
  mkdirSync(dir, { recursive: true });
  const page = await launch({ width: 1920, height: 1080, dpr: 2 });
  const stillsOut = {};
  const park = () => page.mouse("mouseMoved", 4, 1076);

  // ---- Cover: the home page's "Not sure where to start?" card.
  await page.goto(`${BASE}/`, 5000);
  await page.revealAll();
  const coverSel = 'section[aria-labelledby="finder-title"] .stage-sky';
  let cov = await docBox(page, coverSel);
  await page.scrollTo(cov.y - 300);
  await sleep(1200);
  await page.revealAll();
  await park();
  await sleep(800);
  cov = await docBox(page, coverSel);
  const covMarks = {
    intermediate: await relBox(page, coverSel, 'a[href="/finder?level=intermediate"]'),
    beginner: await relBox(page, coverSel, 'a[href="/finder?level=beginner"]'),
    advanced: await relBox(page, coverSel, 'a[href="/finder?level=advanced"]'),
    title: await relBox(page, coverSel, "#finder-title"),
  };
  await shotCard(page, `capture/${SCENE}/cover.jpg`, cov);
  // Hover "Intermediate" (the site's own hover state).
  const scrollY = await page.eval("scrollY");
  await page.mouse("mouseMoved", cov.x + covMarks.intermediate.x + covMarks.intermediate.w / 2, cov.y - scrollY + covMarks.intermediate.y + covMarks.intermediate.h / 2);
  await sleep(900);
  await shotCard(page, `capture/${SCENE}/cover-hover.jpg`, cov);
  await park();
  stillsOut[`${SCENE}-cover`] = { file: `capture/${SCENE}/cover.jpg`, width: cov.w, height: cov.h, dpr: 2, marks: covMarks };
  stillsOut[`${SCENE}-cover-hover`] = { file: `capture/${SCENE}/cover-hover.jpg`, width: cov.w, height: cov.h, dpr: 2, marks: covMarks };
  console.log("cover", cov, covMarks);

  // ---- Question cards 2..8 (the home card answered question 1).
  for (let q = 1; q < 8; q++) {
    await page.goto(`${BASE}/finder?${qs(q)}`, 2500);
    await page.waitFor("document.querySelector('.card-sky')");
    await park();
    await sleep(700);
    const box = await docBox(page, ".card-sky");
    const marks = {};
    const n = q + 1;
    if (q < 7) {
      const opts = await page.eval(`[...document.querySelectorAll('.card-sky [role=radio]')].map((e) => (e.innerText || '').trim().split('\\n')[0].trim())`);
      for (const o of opts) marks[o] = await relBox(page, ".card-sky", "[role=radio]", o);
    } else {
      marks.see = await relBox(page, ".card-sky", "button.btn-primary");
      marks.select = await relBox(page, ".card-sky", "select");
    }
    marks.title = await relBox(page, ".card-sky", "h2");
    const base = `capture/${SCENE}/q${n}.jpg`;
    await shotCard(page, base, box);
    stillsOut[`${SCENE}-q${n}`] = { file: base, width: box.w, height: box.h, dpr: 2, marks };
    // Hover the answer we are about to give (or the "See my matches" button).
    const target = q < 7 ? marks[ANSWERS[q][2]] : marks.see;
    const sy = await page.eval("scrollY");
    await page.mouse("mouseMoved", box.x + target.x + target.w / 2, box.y - sy + target.y + target.h / 2);
    await sleep(900);
    const hov = `capture/${SCENE}/q${n}-hover.jpg`;
    await shotCard(page, hov, box);
    stillsOut[`${SCENE}-q${n}-hover`] = { file: hov, width: box.w, height: box.h, dpr: 2, marks };
    await park();
    // Selected state: answer it, then come back (the site shows the chosen card highlighted).
    if (q < 7) {
      await page.goto(`${BASE}/finder?${qs(q + 1)}`, 2500);
      await page.waitFor("document.querySelector('.card-sky')");
      const back = await page.rectByText("Back", "button");
      await page.click(back.x + back.w / 2, back.y + back.h / 2);
      await park();
      await sleep(900);
      const box2 = await docBox(page, ".card-sky");
      if (box2.w !== box.w || box2.h !== box.h) console.warn(`q${n}: selected card size differs`, box, box2);
      const sel = `capture/${SCENE}/q${n}-selected.jpg`;
      await shotCard(page, sel, box);
      stillsOut[`${SCENE}-q${n}-selected`] = { file: sel, width: box.w, height: box.h, dpr: 2, marks };
    }
    console.log(`q${n}`, box, Object.keys(marks).join(", "));
  }

  Object.assign(stillsOut, await resultCrops(page));
  writeManifest(SCENE, { stills: stillsOut });
  console.log(page.logs.slice(0, 8).join("\n"));
  await page.close();
}

async function footage() {
  const CLIP_DPR = Number(process.env.CLIP_DPR ?? 1.5);
  const page = await launch({ width: 1920, height: 1080, dpr: CLIP_DPR });
  await page.goto(`${BASE}/`, 1500);
  // The gesture hint is shown once per browser: mark it seen, like a returning visitor.
  await page.eval(`localStorage.setItem("paladex:hint-seen", "1"), true`);
  await page.goto(RESULTS_URL, 4000);
  await page.waitFor("document.querySelector('canvas')", 60000);
  const c = await page.rect("canvas");
  await page.mouse("mouseMoved", c.x + c.w / 2, c.y + c.h / 2);
  await sleep(10000);
  await page.mouse("mouseMoved", 1880, 140);
  await sleep(1500);
  const SCROLL = Number(process.env.SCROLL ?? RESULTS_SCROLL);
  if (SCROLL) {
    await page.scrollTo(SCROLL);
    await sleep(1200);
  }
  const marks = await page.marks({
    badge: ".bg-ball.px-4",
    matches: 'ol[aria-label="All matches"]',
    plate: ".plate",
    viewer: ".h-\\[60svh\\]",
    summary: "main p.text-ink-2",
  });
  await page.freeze();
  // Let the pointer lean and the scroll settle on the virtual clock (auto-turn is still off).
  for (let i = 0; i < 150; i++) await page.step(1000 / 60);
  // The viewer reads document visibility only when it renders (`autoRotate && !isHidden()`),
  // and it last rendered while the page was hidden for loading (cdp HIDE_SHIM), so its
  // auto-turn stays off. Re-render it now that the page is visible by toggling the site's
  // own "Stop turning" / "Turn slowly" button (synthetic clicks: no pointer, no lean).
  const toggle = (label) =>
    page.eval(`(() => { const b = document.querySelector('button[aria-label=${JSON.stringify(label)}]'); if (!b) return false; b.click(); return true; })()`);
  if (!(await toggle("Stop turning"))) throw new Error('no "Stop turning" button');
  await sleep(500);
  if (!(await toggle("Turn slowly"))) throw new Error('no "Turn slowly" button');
  await sleep(500);
  if (!(await page.eval(`!!document.querySelector('button[aria-label="Stop turning"]')`))) throw new Error("auto-turn did not come back on");
  for (let i = 0; i < 4; i++) await page.step(1000 / 60);
  const name = `${SCENE}-results`;
  const dir = join(PUB, "capture", SCENE, "results");
  const FR = Number(process.env.FRAMES ?? 320);
  await record(page, { dir, frames: FR, quality: 90 });
  // marks are document px; the clip shows the page scrolled by SCROLL.
  writeManifest(SCENE, {
    clips: { [name]: { dir: `capture/${SCENE}/results`, frames: FR, fps: 60, width: 1920, height: 1080, dpr: CLIP_DPR } },
    stills: { [`${SCENE}-results-marks`]: { file: `capture/${SCENE}/results/f00000.jpg`, width: 1920, height: 1080, dpr: CLIP_DPR, marks: Object.fromEntries(Object.entries(marks).map(([k, b]) => [k, { ...b, y: b.y - SCROLL }])) } },
  });
  console.log("marks", marks, "scroll", SCROLL);
  console.log(page.logs.slice(0, 8).join("\n"));
  await page.close();
}

if (what === "stills" || what === "all") await stills();
if (what === "crops") {
  const page = await launch({ width: 1920, height: 1080, dpr: 2 });
  writeManifest(SCENE, { stills: await resultCrops(page) });
  await page.close();
}
if (what === "footage" || what === "all") await footage();
