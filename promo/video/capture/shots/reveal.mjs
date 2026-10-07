// Scene 3 "reveal": the real home page hero, the hero racket auto-turning on its stage.
//
// One clip for both languages, `reveal-home`. The scene maps clip frame P (POSE_FRAME
// below, also exported in the manifest as an event) onto the word "3D", so the racket's
// pose at the window's settle is the same in EN and IT.
//
//   node capture/shots/reveal.mjs
//
// Deterministic pose: on the frozen clock we step (without screenshots) until the
// viewer's own "Front" chip lights up (the azimuth enters the front quarter, -45°),
// then start recording. The auto-turn is 0.22 rad/s, so clip frame k is at about
// -45° + 0.21°·k (plus the site's gentle lean toward the pointer).
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { launch, packCursor, record, sleep, writeManifest } from "../cdp.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const CLIP = "reveal-home";
const DIR = join(ROOT, "public", "capture", "reveal", "home");
const FRAMES = Number(process.env.FRAMES ?? 280);
// Clip frame that lands on the word "3D" (see Reveal.tsx). The cursor move is timed from it.
const POSE_FRAME = Number(process.env.POSE ?? 150);
// Where the (real) mouse rests before it drifts to "Browse rackets".
const REST = { x: 1580, y: 868 };

const page = await launch({ width: 1920, height: 1080, dpr: Number(process.env.DPR ?? 1.5) });
// A returning visitor: the one-time "Drag to rotate" hint has been seen, so it does not
// cover the racket face (it is shown once per browser on the real site).
await page.send("Page.addScriptToEvaluateOnNewDocument", { source: `try { localStorage.setItem("paladex:hint-seen", "1"); } catch {}` });
await page.goto("http://localhost:3100/", 3000);
await page.waitFor("document.querySelector('canvas')", 60000);
const canvas = await page.rect("canvas");
// Hover the viewer to signal intent, then let the full model load and the intro settle.
await page.mouse("mouseMoved", canvas.x + canvas.w * 0.62, canvas.y + canvas.h * 0.5);
await sleep(9000);
await page.mouse("mouseMoved", REST.x, REST.y);
await sleep(2500);
const browse = await page.rectByText("Browse rackets", "a");
if (!browse) throw new Error("no Browse rackets button");
console.log("browse", browse);

const frontPressed = () =>
  page.eval(`(() => { const b = [...document.querySelectorAll('button[aria-pressed]')].find((x) => x.textContent.trim() === 'Front'); return b ? b.getAttribute('aria-pressed') === 'true' : null; })()`);

await page.freeze();
// Step until the front quarter begins (Front chip turns on after being off).
let wasFront = await frontPressed();
if (wasFront === null) throw new Error("no Front chip");
let pre = 0;
// (The home racket now sways around the front view and the chip stays on: cap the pre-roll.)
for (; pre < Number(process.env.PRE ?? 40); pre++) {
  await page.step(1000 / 60);
  const now = await frontPressed();
  if (now && !wasFront) break;
  wasFront = now;
}
console.log("pre-roll frames", pre);

// Cursor drift: rest → "Browse rackets", eased, with a slight arc (hand-made feel).
const target = { x: browse.x + browse.w * 0.42, y: browse.y + browse.h * 0.56 };
const MOVE_A = POSE_FRAME + 10;
const MOVE_B = POSE_FRAME + 58;
const ease = (t) => (t < 0.5 ? 8 * t ** 4 : 1 - (-2 * t + 2) ** 4 / 2); // in-out quart
const along = (f) => {
  const t = ease(Math.max(0, Math.min(1, (f - MOVE_A) / (MOVE_B - MOVE_A))));
  const dx = target.x - REST.x;
  const dy = target.y - REST.y;
  const len = Math.hypot(dx, dy);
  const arc = Math.sin(t * Math.PI) * Math.min(90, len * 0.07);
  return { x: REST.x + dx * t + (dy / len) * arc, y: REST.y + dy * t - (dx / len) * arc };
};

const track = await record(page, {
  dir: DIR,
  frames: FRAMES,
  quality: 90,
  script: async (f, t, api) => {
    const p = along(f);
    if (f >= MOVE_A - 1 && f <= MOVE_B + 1) await page.mouse("mouseMoved", p.x, p.y);
    api.cursor(p.x, p.y, false);
  },
});

writeManifest("reveal", {
  clips: {
    [CLIP]: {
      dir: "capture/reveal/home",
      frames: FRAMES,
      fps: 60,
      width: 1920,
      height: 1080,
      dpr: Number(process.env.DPR ?? 1.5),
      cursor: packCursor(track),
      events: [
        { type: "pose", frame: POSE_FRAME, x: 0, y: 0, label: "3D" },
        { type: "move-start", frame: MOVE_A, x: REST.x, y: REST.y },
        { type: "hover", frame: MOVE_B, x: target.x, y: target.y, label: "Browse rackets" },
      ],
    },
  },
});
console.log(page.logs.slice(0, 10).join("\n"));
await page.close();
console.log("done", FRAMES, "frames");
