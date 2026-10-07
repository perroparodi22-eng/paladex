// Frame-exact capture of the real Paladex site over the Chrome DevTools protocol.
//
// The page gets a virtual clock (performance.now, Date.now, requestAnimationFrame,
// timers, requestIdleCallback). While "live", time passes normally so the page can
// load. After `freeze()`, time only moves when we call `step()`, so a 60 fps capture
// is perfectly smooth no matter how long each screenshot takes. The site's 3D viewer
// (React Three Fiber, camera-controls) reads all its time from these functions.
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const WIN = process.platform === "win32";
const CHROME =
  process.env.CHROME ??
  (WIN ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/opt/pw-browsers/chromium-1194/chrome-linux/chrome");
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const TIME_SHIM = String.raw`(() => {
  if (window.__vt) return;
  const W = window;
  const real = {
    raf: W.requestAnimationFrame.bind(W),
    caf: W.cancelAnimationFrame.bind(W),
    st: W.setTimeout.bind(W),
    ct: W.clearTimeout.bind(W),
    si: W.setInterval.bind(W),
    ci: W.clearInterval.bind(W),
    ric: (W.requestIdleCallback || ((cb) => W.setTimeout(() => cb({ didTimeout: false, timeRemaining: () => 8 }), 1))).bind(W),
    pnow: performance.now.bind(performance),
    dnow: Date.now.bind(Date),
  };
  const vt = { frozen: false, now: 0, dateBase: 0, frames: 0 };
  // rAF: our own queue, flushed by a real rAF pump while live, by step() while frozen.
  let rafQ = new Map();
  let rafSeq = 1;
  const pump = (ts) => {
    if (vt.frozen) return;
    const q = rafQ; rafQ = new Map();
    for (const cb of q.values()) { try { cb(real.pnow()); } catch (e) { console.error(e); } }
    real.raf(pump);
  };
  real.raf(pump);
  W.requestAnimationFrame = (cb) => { const id = rafSeq++; rafQ.set(id, cb); return id; };
  W.cancelAnimationFrame = (id) => { rafQ.delete(id); };
  performance.now = () => (vt.frozen ? vt.now : real.pnow());
  Date.now = () => (vt.frozen ? vt.dateBase + vt.now : real.dnow());
  // Timers: real while live; virtual once frozen. A real timer that fires after the
  // freeze is re-queued on the virtual clock so nothing runs "between" frames.
  const vtimers = new Map();
  let tSeq = 1;
  const realIds = new Map();
  const addVirtual = (id, cb, args, delay, interval) => vtimers.set(id, { at: vt.now + Math.max(0, delay || 0), cb, args, interval, seq: tSeq++ });
  W.setTimeout = (cb, delay = 0, ...args) => {
    const id = tSeq++;
    if (typeof cb !== "function") return id;
    if (vt.frozen) { addVirtual(id, cb, args, delay, 0); return id; }
    const rid = real.st(() => { realIds.delete(id); if (vt.frozen) addVirtual(id, cb, args, 0, 0); else cb(...args); }, delay);
    realIds.set(id, { rid, kind: "t" });
    return id;
  };
  W.setInterval = (cb, delay = 0, ...args) => {
    const id = tSeq++;
    if (typeof cb !== "function") return id;
    if (vt.frozen) { addVirtual(id, cb, args, delay, Math.max(1, delay || 1)); return id; }
    const rid = real.si(() => { if (vt.frozen) { real.ci(rid); realIds.delete(id); addVirtual(id, cb, args, delay, Math.max(1, delay || 1)); } else cb(...args); }, delay);
    realIds.set(id, { rid, kind: "i" });
    return id;
  };
  const clear = (id) => { vtimers.delete(id); const r = realIds.get(id); if (r) { (r.kind === "i" ? real.ci : real.ct)(r.rid); realIds.delete(id); } };
  W.clearTimeout = clear;
  W.clearInterval = clear;
  W.requestIdleCallback = (cb, opts) => W.setTimeout(() => cb({ didTimeout: false, timeRemaining: () => 12 }), 1);
  W.cancelIdleCallback = (id) => clear(id);
  vt.freeze = () => {
    if (vt.frozen) return;
    vt.now = real.pnow();
    vt.dateBase = real.dnow() - vt.now;
    vt.frozen = true;
  };
  vt.thaw = () => { if (!vt.frozen) return; vt.frozen = false; real.raf(pump); };
  // Advance the virtual clock by dt ms: run due timers in order, then one rAF batch.
  vt.step = (dt) => {
    const target = vt.now + dt;
    for (let guard = 0; guard < 10000; guard++) {
      let next = null;
      for (const [id, t] of vtimers) if (t.at <= target && (!next || t.at < next[1].at || (t.at === next[1].at && t.seq < next[1].seq))) next = [id, t];
      if (!next) break;
      const [id, t] = next;
      vt.now = Math.max(vt.now, t.at);
      if (t.interval) { t.at += t.interval; t.seq = tSeq++; } else vtimers.delete(id);
      try { t.cb(...(t.args || [])); } catch (e) { console.error(e); }
    }
    vt.now = target;
    const q = rafQ; rafQ = new Map();
    for (const cb of q.values()) { try { cb(vt.now); } catch (e) { console.error(e); } }
    vt.frames++;
    return rafQ.size;
  };
  W.__vt = vt;
})();`;

// Hide dev-only chrome (Next.js dev indicator) and the scrollbar.
const HIDE_CSS = `nextjs-portal{display:none!important} html{scrollbar-width:none} ::-webkit-scrollbar{display:none}`;

// The site's viewer gives up ("3D view paused") if a loaded model hasn't drawn its first
// frame after 9 s of *visible* time. With a GPU that never happens; on SwiftShader the
// shader warm-up can take longer. So outside Windows the page reports itself as hidden
// while it loads (the watchdog only counts visible time) and becomes visible again on
// freeze(), before anything is recorded.
const HIDE_SHIM = `(() => {
  window.__forceHidden = true;
  Object.defineProperty(Document.prototype, "visibilityState", { configurable: true, get() { return window.__forceHidden ? "hidden" : "visible"; } });
  Object.defineProperty(Document.prototype, "hidden", { configurable: true, get() { return !!window.__forceHidden; } });
})();`;

// Rackets without a finished 3D design never appear in the ad (owner's rule): every
// capture hides any card, list item or result that links to one, shows its poster, or
// is labelled with its exact name. See capture/unfinished.json.
const UNFINISHED = JSON.parse(readFileSync(new URL("./unfinished.json", import.meta.url), "utf8"));
const HIDE_UNFINISHED = `(() => {
  const slugs = ${JSON.stringify(UNFINISHED.slugs)};
  const names = new Set(${JSON.stringify(UNFINISHED.names)});
  const bySlug = (v) => v && slugs.some((s) => new RegExp("/" + s + "(?![a-z0-9-])").test(v));
  const hide = (el) => {
    const box = el.closest("li") || el.closest("article") || el.closest("[class*='card']") || el;
    if (box.style.display !== "none") box.style.setProperty("display", "none", "important");
  };
  const sweep = () => {
    for (const a of document.querySelectorAll("a[href]")) if (bySlug(a.getAttribute("href"))) hide(a);
    for (const img of document.querySelectorAll("img")) if (bySlug(img.getAttribute("src")) || bySlug(img.currentSrc)) hide(img);
    for (const el of document.querySelectorAll("li span, li p, li h3, li h2")) if (names.has((el.textContent || "").trim())) hide(el);
  };
  const start = () => { sweep(); new MutationObserver(sweep).observe(document.documentElement, { childList: true, subtree: true }); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();`;

export async function launch({ width = 1920, height = 1080, dpr = 1, gpu = true, mobile = false, hideWhileLoading = !WIN, hideUnfinished = true } = {}) {
  const port = 9600 + Math.floor(Math.random() * 300);
  const profile = mkdtempSync(join(tmpdir(), "promo-cap-"));
  const proc = spawn(
    CHROME,
    [
      "--headless=new",
      `--remote-debugging-port=${port}`,
      // No GPU outside Windows (cloud containers): WebGL runs on SwiftShader.
      ...(gpu && WIN ? ["--use-angle=d3d11", "--enable-gpu-rasterization", "--ignore-gpu-blocklist"] : ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]),
      ...(WIN ? [] : ["--no-sandbox", "--disable-dev-shm-usage"]),
      // e.g. CHROME_EXTRA_ARGS="--disable-gpu-rasterization" for page stills (CPU raster).
      ...(process.env.CHROME_EXTRA_ARGS ? process.env.CHROME_EXTRA_ARGS.split(" ") : []),
      "--hide-scrollbars",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-background-timer-throttling",
      "--disable-renderer-backgrounding",
      "--force-color-profile=srgb",
      "--font-render-hinting=none",
      `--window-size=${width},${height}`,
      `--user-data-dir=${profile}`,
      "about:blank",
    ],
    { stdio: "ignore" },
  );
  // Never leave a headless Chrome behind, even when the script throws.
  process.on("exit", () => {
    try {
      proc.kill("SIGKILL");
    } catch {}
  });
  let targets = [];
  for (let i = 0; i < 80; i++) {
    try {
      targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      if (targets.some((t) => t.type === "page")) break;
    } catch {}
    await sleep(250);
  }
  const target = targets.find((t) => t.type === "page");
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0;
  const pending = new Map();
  const logs = [];
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    } else if (msg.method === "Runtime.exceptionThrown") {
      logs.push("EXC " + (msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text).slice(0, 300));
    } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
      logs.push("ERR " + msg.params.args.map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 300));
    }
  };
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const i = ++id;
      pending.set(i, (msg) => (msg.error ? reject(new Error(`${method}: ${msg.error.message}`)) : resolve(msg.result)));
      ws.send(JSON.stringify({ id: i, method, params }));
    });

  await send("Runtime.enable");
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: dpr, mobile });
  await send("Emulation.setFocusEmulationEnabled", { enabled: true });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }, { name: "prefers-color-scheme", value: "dark" }] });
  if (mobile) await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await send("Page.addScriptToEvaluateOnNewDocument", { source: TIME_SHIM });
  if (hideWhileLoading) await send("Page.addScriptToEvaluateOnNewDocument", { source: HIDE_SHIM });
  if (hideUnfinished) await send("Page.addScriptToEvaluateOnNewDocument", { source: HIDE_UNFINISHED });
  await send("Page.addScriptToEvaluateOnNewDocument", {
    source: `document.addEventListener("DOMContentLoaded",()=>{const s=document.createElement("style");s.textContent=${JSON.stringify(HIDE_CSS)};document.head.appendChild(s);});`,
  });

  const page = {
    send,
    logs,
    width,
    height,
    dpr,
    async eval(expression) {
      const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) throw new Error("eval failed: " + (r.exceptionDetails.exception?.description ?? r.exceptionDetails.text));
      return r.result?.value;
    },
    async goto(url, settleMs = 4000) {
      await send("Page.navigate", { url });
      await page.waitFor("document.readyState === 'complete'", 60000);
      await sleep(settleMs);
    },
    async waitFor(expr, timeout = 30000, interval = 200) {
      const t0 = Date.now();
      while (Date.now() - t0 < timeout) {
        try {
          if (await page.eval(`!!(${expr})`)) return true;
        } catch {}
        await sleep(interval);
      }
      throw new Error("timeout waiting for: " + expr);
    },
    /** Bounding box of the first element matching a selector (CSS px). */
    async rect(selector) {
      return page.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; })()`);
    },
    /** Bounding box of the first element whose visible text matches exactly (trimmed). */
    async rectByText(text, selector = "button, a, [role=button], label, li, div, span") {
      return page.eval(`(() => {
        const want = ${JSON.stringify(text)}.trim().toLowerCase();
        const els = [...document.querySelectorAll(${JSON.stringify(selector)})].filter((el) => (el.innerText || el.textContent || "").trim().toLowerCase() === want);
        const vis = els.map((el) => [el, el.getBoundingClientRect()]).filter(([, r]) => r.width > 0 && r.height > 0);
        if (!vis.length) return null;
        vis.sort((a, b) => a[1].width * a[1].height - b[1].width * b[1].height);
        const r = vis[0][1];
        return { x: r.x, y: r.y, w: r.width, h: r.height };
      })()`);
    },
    /** Make the page visible again (see HIDE_SHIM). */
    show: () => page.eval(`(() => { if (window.__forceHidden) { window.__forceHidden = false; document.dispatchEvent(new Event("visibilitychange")); } return true; })()`),
    async freeze() {
      await page.show();
      return page.eval("window.__vt.freeze(), true");
    },
    thaw: () => page.eval("window.__vt.thaw(), true"),
    step: (dt = 1000 / 60) => page.eval(`window.__vt.step(${dt})`),
    async mouse(type, x, y, { buttons = 0, button = "none", clickCount = 0 } = {}) {
      await send("Input.dispatchMouseEvent", { type, x, y, buttons, button, clickCount, pointerType: "mouse" });
    },
    async wheel(x, y, deltaY) {
      await send("Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX: 0, deltaY });
    },
    async screenshot(file, { format = "jpeg", quality = 92, clip } = {}) {
      const res = await send("Page.captureScreenshot", { format, quality: format === "jpeg" ? quality : undefined, ...(clip ? { clip: { ...clip, scale: 1 } } : {}) });
      writeFileSync(file, Buffer.from(res.data, "base64"));
    },
    /** Click (press + release) at page coordinates. */
    async click(x, y) {
      await page.mouse("mouseMoved", x, y);
      await page.mouse("mousePressed", x, y, { button: "left", buttons: 1, clickCount: 1 });
      await page.mouse("mouseReleased", x, y, { button: "left", buttons: 0, clickCount: 1 });
    },
    /**
     * Slow down (rate < 1) or speed up CSS transitions/animations and Web Animations.
     * CSS motion runs on real time, not the virtual clock: while recording at a fixed
     * fps where each captured frame takes ~N ms of real time, a rate of
     * (1000/fps)/N keeps CSS motion roughly in step with the 3D.
     */
    async setAnimationRate(rate) {
      await send("Animation.enable");
      await send("Animation.setPlaybackRate", { playbackRate: rate });
    },
    /** Force every scroll-reveal block to its final, visible state (for stills). */
    async revealAll() {
      await page.eval(`(() => { const s = document.createElement("style"); s.textContent = '[data-reveal]{opacity:1!important;transform:none!important;filter:none!important;transition:none!important;animation:none!important}'; document.head.appendChild(s); document.querySelectorAll('[data-reveal]').forEach((e) => (e.dataset.reveal = 'in')); return true; })()`);
    },
    async scrollTo(y) {
      await page.eval(`window.scrollTo({ top: ${y}, behavior: "instant" }), true`);
    },
    /** Document-coordinate boxes (CSS px) for named selectors, for crops/callouts. */
    async marks(selectors) {
      return page.eval(`(() => { const out = {}; const m = ${JSON.stringify(selectors)}; for (const k in m) { const el = document.querySelector(m[k]); if (!el) continue; const r = el.getBoundingClientRect(); out[k] = { x: Math.round(r.x + scrollX), y: Math.round(r.y + scrollY), w: Math.round(r.width), h: Math.round(r.height) }; } return out; })()`);
    },
    /**
     * Full-page screenshot (everything below the fold too). Returns the CSS size.
     * Run revealAll() first so scroll-reveal sections are visible.
     */
    async fullPage(file, { format = "jpeg", quality = 92, maxHeight = 16000 } = {}) {
      const size = await page.eval(`({ w: document.documentElement.clientWidth, h: Math.min(${maxHeight}, document.documentElement.scrollHeight) })`);
      const res = await send("Page.captureScreenshot", { format, quality: format === "jpeg" ? quality : undefined, captureBeyondViewport: true, clip: { x: 0, y: 0, width: size.w, height: size.h, scale: 1 } });
      writeFileSync(file, Buffer.from(res.data, "base64"));
      return size;
    },
    async close() {
      try {
        ws.close();
      } catch {}
      proc.kill();
      await sleep(300);
      try {
        rmSync(profile, { recursive: true, force: true });
      } catch {}
    },
  };
  return page;
}

/**
 * Merge clips/stills into this scene's manifest fragment, src/data/capture/<scene>.json
 * (each scene owns its own fragment so parallel captures never collide).
 * Clip entry: { dir, frames, fps, width, height, dpr, cursor?: [[x,y,down01],...], events? }
 * Still entry: { file, width, height, dpr, marks? }   (paths relative to public/)
 */
export function writeManifest(sceneId, { clips = {}, stills = {} }) {
  const file = new URL(`../src/data/capture/${sceneId}.json`, import.meta.url);
  let cur = { clips: {}, stills: {} };
  try {
    cur = JSON.parse(readFileSync(file, "utf8"));
  } catch {}
  const next = { clips: { ...cur.clips, ...clips }, stills: { ...cur.stills, ...stills } };
  writeFileSync(file, JSON.stringify(next));
  return next;
}

/** Turn a record() track into the compact manifest cursor format. */
export const packCursor = (track) => track.map((t) => [Math.round(t.x * 10) / 10, Math.round(t.y * 10) / 10, t.down ? 1 : 0]);

/**
 * Records a scripted shot at a fixed frame rate on the frozen clock.
 * `script(frame, t)` runs before each frame is captured (t in seconds since the
 * shot started) and may dispatch input. Frames go to `${dir}/f00000.jpg`…
 * Returns the cursor track the script reported via `cursor(x, y, down)`.
 */
export async function record(page, { dir, frames, fps = 60, quality = 90, script }) {
  mkdirSync(dir, { recursive: true });
  const track = [];
  let cur = { x: page.width / 2, y: page.height / 2, down: false };
  const api = {
    cursor(x, y, down = cur.down) {
      cur = { x, y, down };
    },
    get cur() {
      return cur;
    },
  };
  for (let f = 0; f < frames; f++) {
    if (script) await script(f, f / fps, api);
    await page.step(1000 / fps);
    await page.screenshot(join(dir, `f${String(f).padStart(5, "0")}.jpg`), { quality });
    track.push({ x: +cur.x.toFixed(2), y: +cur.y.toFixed(2), down: cur.down });
    if (f % 60 === 0) process.stdout.write(`  ${dir.split(/[\\/]/).pop()} ${f}/${frames}\n`);
  }
  writeFileSync(join(dir, "cursor.json"), JSON.stringify({ fps, width: page.width, height: page.height, dpr: page.dpr, track }));
  return track;
}
