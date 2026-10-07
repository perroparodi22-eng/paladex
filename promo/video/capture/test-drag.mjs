import { launch, record, sleep } from "./cdp.mjs";

const out = process.argv[2] ?? "C:/Users/diego/AppData/Local/Temp/claude/C--Users-diego-Downloads-paladex/d19f14d0-2b78-470d-8f23-9faf4597ee12/scratchpad/drag";
const page = await launch({ width: 1920, height: 1080, dpr: 1 });
await page.goto("http://localhost:3100/rackets/nox-at10-luxury-genius-18k-alum", 3000);
await page.waitFor("document.querySelector('canvas')", 60000);
// Hover the viewer to signal intent, then wait for the full model to load.
const c = await page.rect("canvas");
console.log("canvas", c);
await page.mouse("mouseMoved", c.x + c.w / 2, c.y + c.h / 2);
await sleep(9000);
await page.freeze();
const cx = c.x + c.w / 2;
const cy = c.y + c.h * 0.45;
await record(page, {
  dir: out,
  frames: 90,
  script: async (f, t, api) => {
    if (f === 10) {
      api.cursor(cx - 150, cy, true);
      await page.mouse("mousePressed", cx - 150, cy, { button: "left", buttons: 1, clickCount: 1 });
    } else if (f > 10 && f <= 60) {
      const x = cx - 150 + ((f - 10) / 50) * 300;
      api.cursor(x, cy, true);
      await page.mouse("mouseMoved", x, cy, { buttons: 1 });
    } else if (f === 61) {
      api.cursor(cx + 150, cy, false);
      await page.mouse("mouseReleased", cx + 150, cy, { button: "left", buttons: 0, clickCount: 1 });
    }
  },
});
console.log(page.logs.slice(0, 10).join("\n"));
await page.close();
