// Render only the soundtrack (voice, ducked music, SFX) of the full ad to a WAV file.
// The CLI can't do this with remotion.config.ts (its video settings, like CRF, are
// rejected for audio codecs), so it goes through the renderer API.
//   [VO_OFFSET=12] node scripts/render-audio.mjs [out/audio.wav]
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import { rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = resolve(root, process.argv[2] ?? "out/audio.wav");
const win = process.platform === "win32";
const browserExecutable = process.env.REMOTION_BROWSER ?? (win ? null : "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell");
const chromiumOptions = { gl: win ? "angle" : "swangle" };

const serveUrl = await bundle({ entryPoint: join(root, "src/index.ts"), rootDir: root, publicDir: join(root, "public") });
try {
  // audioOnly: the 3D layers render nothing (sound never depends on them), so this is fast.
  // VO_OFFSET=<frames> shifts only the narrator (+ = later) to fine-tune lip-sync feel against the picture.
  const inputProps = { audioOnly: true, ...(process.env.VO_OFFSET ? { voOffset: Number(process.env.VO_OFFSET) } : {}) };
  const composition = await selectComposition({ serveUrl, id: "PaladexLaunch", inputProps, browserExecutable, chromiumOptions });
  await renderMedia({ composition, serveUrl, codec: "wav", outputLocation: output, inputProps, browserExecutable, chromiumOptions });
  console.log(`audio -> ${output}`);
} finally {
  rmSync(serveUrl, { recursive: true, force: true });
}
