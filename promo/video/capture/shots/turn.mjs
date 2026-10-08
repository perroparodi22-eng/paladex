// Scene 4 "turn": the hero racket's page. The cursor approaches the 3D racket,
// grabs and turns it on "turn it in your hand", then clicks the viewer's Front /
// Side / Back buttons exactly on those words (word-synced clip, English).
//
// Besides the frames, we record the site's own 3D camera every frame (by watching
// the WebGL viewMatrix/projectionMatrix uniforms), so the Remotion scene can place
// its WebGL racket exactly over the on-screen racket when it "breaks out" of the
// browser. Finally a still of the same page state with the 3D canvas hidden (the
// racket has left the screen).
//
// usage: node capture/shots/turn.mjs
import { mkdirSync, readFileSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { launch, packCursor, record, sleep, writeManifest } from "../cdp.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const URL_ = "http://localhost:3100/rackets/nox-at10-luxury-genius-18k-alum";
const langs = ["en"];

// Words that drive the shot (same lookups as wordAt() in the scene).
const KEYS = {
  en: { pick: "Grab", turn: "Spin", hand: "it", front: "Front", side: "Side", back: "Back", every: "Every" },
};

const norm = (x) => x.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
function words(lang) {
  const t = JSON.parse(readFileSync(`${ROOT}src/data/timeline.${lang}.json`, "utf8"));
  const s = t.scenes.find((x) => x.id === "turn");
  const at = (w, edge = "start") => {
    const hit = s.vo.words.find((x) => norm(x.text) === norm(w));
    if (!hit) throw new Error(`word ${w} not found (${lang})`);
    return hit[edge] - s.start;
  };
  const k = KEYS[lang];
  return {
    pick: at(k.pick),
    turn: at(k.turn),
    handEnd: at(k.hand, "end"),
    front: at(k.front),
    side: at(k.side),
    back: at(k.back),
    every: at(k.every),
    duration: s.duration,
  };
}

// cubic-bezier easing (CSS semantics)
function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = (t) => ((ax * t + bx) * t + cx) * t;
  const sy = (t) => ((ay * t + by) * t + cy) * t;
  const dx = (t) => (3 * ax * t + 2 * bx) * t + cx;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 8; i++) {
      const e = sx(t) - x;
      const d = dx(t);
      if (Math.abs(e) < 1e-6 || Math.abs(d) < 1e-6) break;
      t -= e / d;
    }
    return sy(Math.min(1, Math.max(0, t)));
  };
}
const handMove = bezier(0.42, 0, 0.18, 1); // a hand reaching: quick start, soft landing
const dragEase = bezier(0.45, 0, 0.6, 1);
const clamp01 = (x) => Math.min(1, Math.max(0, x));

/** Piecewise cursor path: segments {a, b, from, to, ease, arc}. Holds between. */
function pathAt(segs, f) {
  let p = segs[0].from;
  for (const s of segs) {
    if (f < s.a) return p;
    const t = (s.ease ?? handMove)(clamp01((f - s.a) / Math.max(1, s.b - s.a)));
    const dx = s.to[0] - s.from[0];
    const dy = s.to[1] - s.from[1];
    const len = Math.hypot(dx, dy) || 1;
    const arc = Math.sin(t * Math.PI) * (s.arc ?? Math.min(50, len * 0.08));
    p = [s.from[0] + dx * t + (-dy / len) * arc, s.from[1] + dy * t + (dx / len) * arc];
    if (f <= s.b) return p;
    p = s.to;
  }
  return p;
}

// Watches the WebGL camera uniforms (three.js uploads viewMatrix/projectionMatrix per program).
const CAM_HOOK = String.raw`(() => {
  if (window.__camHook) return;
  const names = new WeakMap();
  const progs = new Map();
  let seq = 0;
  const hook = (C) => {
    if (!C) return;
    const gul = C.prototype.getUniformLocation;
    C.prototype.getUniformLocation = function (prog, name) {
      const loc = gul.call(this, prog, name);
      if (loc) names.set(loc, { name, prog });
      return loc;
    };
    const um = C.prototype.uniformMatrix4fv;
    C.prototype.uniformMatrix4fv = function (loc, tr, data, ...rest) {
      const n = loc && names.get(loc);
      if (n && (n.name === "viewMatrix" || n.name === "projectionMatrix")) {
        let p = progs.get(n.prog);
        if (!p) progs.set(n.prog, (p = {}));
        p[n.name] = Array.from(data).slice(0, 16);
        if (n.name === "viewMatrix") p.seq = ++seq;
      }
      return um.call(this, loc, tr, data, ...rest);
    };
  };
  hook(window.WebGLRenderingContext);
  hook(window.WebGL2RenderingContext);
  window.__camHook = () => {
    let best = null;
    for (const p of progs.values()) {
      if (!p.viewMatrix || !p.projectionMatrix) continue;
      const P = p.projectionMatrix;
      if (Math.abs(P[11] + 1) > 1e-3 || P[5] < 2) continue; // perspective, narrow fov = the viewer camera
      if (!best || p.seq > best.seq) best = p;
    }
    return best ? { view: best.viewMatrix, proj: best.projectionMatrix } : null;
  };
})();`;

/** Site camera -> [azimuth, polar, racket centre x/y (page px), page px per metre at the racket]. */
function camInfo(cam, canvas) {
  if (!cam) return null;
  const V = cam.view;
  const P = cam.proj;
  const zx = V[2], zy = V[6], zz = V[10];
  const az = Math.atan2(zx, zz);
  const polar = Math.acos(Math.max(-1, Math.min(1, zy)));
  // model centre is the world origin: view-space position = translation column
  const vx = V[12], vy = V[13], vz = V[14];
  const cx = P[0] * vx + P[8] * vz + P[12] * 1;
  const cy = P[5] * vy + P[9] * vz + P[13];
  const w = -vz;
  const nx = cx / w, ny = cy / w;
  const px = canvas.x + ((nx + 1) / 2) * canvas.w;
  const py = canvas.y + ((1 - ny) / 2) * canvas.h;
  const pxPerM = ((canvas.h / 2) * P[5]) / w;
  const r = (x, n = 4) => Math.round(x * 10 ** n) / 10 ** n;
  return [r(az), r(polar), r(px, 2), r(py, 2), r(pxPerM, 2)];
}

for (const lang of langs) {
  const W = words(lang);
  const frames = W.every + 70;
  const name = `turn-page-${lang}`;
  const dir = `${ROOT}public/capture/turn/${name}`;
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  console.log(lang, W, "frames", frames);

  // dpr 1.5: the page fills most of the frame in a 2560x1440 render.
  const page = await launch({ width: 1920, height: 1080, dpr: 1.5 });
  await page.send("Page.addScriptToEvaluateOnNewDocument", { source: CAM_HOOK });
  await page.goto(URL_, 3000);
  await page.waitFor("document.querySelector('canvas')", 60000);
  await page.scrollTo(0);
  // The canvas starts at the default 300x150 and gets its real size once the viewer
  // has mounted: measure it only then (the grab point and the camera track use it).
  await page.waitFor("document.querySelector('canvas').getBoundingClientRect().width > 400", 120000);
  const canvas = await page.rect("canvas");
  // Hover the viewer to signal intent, then let the full model load.
  await page.mouse("mouseMoved", canvas.x + canvas.w / 2, canvas.y + canvas.h / 2);
  await sleep(9000);
  // Park the pointer off the viewer (right column, plain text) and let the parallax settle.
  const start = [canvas.x + canvas.w + 150, canvas.y + canvas.h * 0.63];
  await page.mouse("mouseMoved", start[0], start[1]);
  await sleep(2500);

  // The view buttons appear once the model has loaded (slow on a software GPU).
  await page.waitFor(`[...document.querySelectorAll("button")].some((b) => b.textContent.trim() === "Back")`, 120000);
  await sleep(1500);
  const btn = {};
  for (const label of ["Front", "Side", "Back"]) {
    const r = await page.rectByText(label, "button");
    if (!r) throw new Error("button not found: " + label);
    btn[label] = [r.x + r.w / 2, r.y + r.h / 2 + 1];
  }
  const hint = await page.rectByText("Drag to rotate");
  console.log("canvas", canvas, "buttons", btn, "hint", hint);

  // CSS transitions run on real time: slow them to match the capture pace.
  {
    const t0 = Date.now();
    for (let i = 0; i < 6; i++) await page.screenshot(`${dir}/_probe.jpg`, { quality: 90 });
    const ms = (Date.now() - t0) / 6 + 12;
    const rate = Math.min(1, 1000 / 60 / ms);
    console.log("ms/frame ~", ms.toFixed(0), "animation rate", rate.toFixed(3));
    await page.setAnimationRate(rate);
    rmSync(`${dir}/_probe.jpg`, { force: true });
  }

  // ---- the choreography (scene-local frames = clip frames)
  const G = [canvas.x + canvas.w * 0.6, canvas.y + canvas.h * 0.37]; // grab: right half of the face
  const D = [G[0] - 430, G[1] + 46]; // drag end
  const press = W.turn - 3;
  const dragEnd = Math.min(W.handEnd - 6, W.front - 34);
  const release = dragEnd;
  const click = (w) => ({ down: w - 2, up: w + 2 });
  const cF = click(W.front), cS = click(W.side), cB = click(W.back);
  const segs = [
    { a: W.pick + 2, b: press - 4, from: start, to: G, arc: 60 },
    // the drag: an easy hand turn with a gentle lift at the end
    { a: press + 1, b: dragEnd, from: G, to: D, ease: dragEase, arc: -26 },
    { a: release + 2, b: cF.down - 2, from: D, to: btn.Front, arc: 34 },
    { a: cF.up + 6, b: cS.down - 3, from: btn.Front, to: btn.Side, arc: 8 },
    { a: cS.up + 6, b: cB.down - 3, from: btn.Side, to: btn.Back, arc: 8 },
  ];
  const events = [
    { type: "grab", frame: press, x: G[0], y: G[1] },
    { type: "release", frame: release, x: D[0], y: D[1] },
    { type: "click", frame: W.front, x: btn.Front[0], y: btn.Front[1], label: "Front" },
    { type: "click", frame: W.side, x: btn.Side[0], y: btn.Side[1], label: "Side" },
    { type: "click", frame: W.back, x: btn.Back[0], y: btn.Back[1], label: "Back" },
  ];

  const cams = [];
  let down = false;
  await page.freeze();
  const track = await record(page, {
    dir,
    frames,
    quality: 90,
    script: async (f, t, api) => {
      if (f > 0) cams.push(camInfo(await page.eval("window.__camHook()"), canvas));
      const [x, y] = pathAt(segs, f);
      const wantDown = (f >= press && f < release) || [cF, cS, cB].some((c) => f >= c.down && f < c.up);
      if (wantDown && !down) {
        await page.mouse("mouseMoved", x, y, { buttons: 0 });
        await page.mouse("mousePressed", x, y, { button: "left", buttons: 1, clickCount: 1 });
      } else if (!wantDown && down) {
        await page.mouse("mouseMoved", x, y, { buttons: 1 });
        await page.mouse("mouseReleased", x, y, { button: "left", buttons: 0, clickCount: 1 });
      } else {
        await page.mouse("mouseMoved", x, y, { buttons: wantDown ? 1 : 0 });
      }
      down = wantDown;
      api.cursor(x, y, wantDown);
    },
  });
  cams.push(camInfo(await page.eval("window.__camHook()"), canvas));

  // The same page with the racket gone: hide the 3D canvas, keep everything else.
  await page.eval(`(() => { const c = document.querySelector('canvas'); c.style.visibility = 'hidden'; return true; })()`);
  await page.step(1000 / 60);
  await page.step(1000 / 60);
  const emptyFile = `capture/turn/turn-empty-${lang}.jpg`;
  await page.screenshot(`${ROOT}public/${emptyFile}`, { quality: 92 });

  console.log(page.logs.slice(0, 8).join("\n"));
  await page.close();

  writeManifest("turn", {
    clips: {
      [name]: {
        dir: `capture/turn/${name}`,
        frames,
        fps: 60,
        width: 1920,
        height: 1080,
        dpr: 1.5,
        cursor: packCursor(track),
        events,
        // scene-specific extras
        canvas,
        cam: cams,
      },
    },
    stills: {
      [`turn-empty-${lang}`]: { file: emptyFile, width: 1920, height: 1080, dpr: 1.5 },
    },
  });
  console.log("done", lang);
}
