// Render many stills of one composition with a single bundle, plus an optional
// contact sheet. Much faster than calling `npx remotion still` per frame.
//
// usage: node scripts/stills.mjs <compositionId> <outDir> <frame|from-to/step> ... [--sheet name.jpg] [--scale 0.5] [--props '{"subtitles":false}'] [--entry src/dev/<scene>.tsx]
//   e.g. node scripts/stills.mjs PaladexLaunch out/stills 600-1080/60 1200 --sheet turn.jpg
//   one scene only (isolated bundle, scene-local frames): node scripts/stills.mjs Dev out/turn 0-480/24 --entry src/dev/turn.tsx --sheet sheet.jpg
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import fs, { mkdirSync, rmSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const opt = (name, def) => {
  const i = args.indexOf(name);
  if (i < 0) return def;
  const v = args[i + 1];
  args.splice(i, 2);
  return v;
};
const sheet = opt("--sheet", null);
const entry = opt("--entry", "src/index.ts");
const scale = Number(opt("--scale", "0.5"));
const props = JSON.parse(opt("--props", "{}"));
const [id, outDir, ...specs] = args;
if (!id || !outDir || !specs.length) {
  console.error("usage: node scripts/stills.mjs <compositionId> <outDir> <frame|from-to/step> ... [--sheet name.jpg] [--scale 0.5] [--props json]");
  process.exit(1);
}
const frames = specs.flatMap((s) => {
  const m = s.match(/^(\d+)-(\d+)(?:\/(\d+))?$/);
  if (!m) return [Number(s)];
  const out = [];
  for (let f = +m[1]; f <= +m[2]; f += +(m[3] ?? 1)) out.push(f);
  return out;
});

// The bundler copies all of public/ (hundreds of MB of captured frames) into a temp
// folder on every run. Hard-link the files instead (same volume, no extra disk,
// instant), and delete the bundle when done.
const copyFile = fs.promises.copyFile.bind(fs.promises);
fs.promises.copyFile = async (src, dest, mode) => {
  try {
    await fs.promises.link(src, dest);
  } catch {
    await copyFile(src, dest, mode);
  }
};

const t0 = Date.now();
const serveUrl = await bundle({ entryPoint: join(root, entry), rootDir: root, publicDir: join(root, "public") });
const files = [];
try {
  // GPU WebGL on Windows; software (SwiftShader) in GPU-less Linux containers.
  const win = process.platform === "win32";
  const chromiumOptions = { gl: win ? "angle" : "swangle" };
  const browserExecutable = process.env.REMOTION_BROWSER ?? (win ? null : "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell");
  const composition = await selectComposition({ serveUrl, id, inputProps: props, chromiumOptions, browserExecutable });
  mkdirSync(join(root, outDir), { recursive: true });
  for (const frame of frames) {
    const output = join(root, outDir, `${id}-${String(frame).padStart(5, "0")}.jpg`);
    await renderStill({ composition, serveUrl, output, frame, inputProps: props, imageFormat: "jpeg", jpegQuality: 88, scale, chromiumOptions, browserExecutable, overwrite: true });
    files.push(output);
    console.log(`frame ${frame} -> ${output}`);
  }
  console.log(`rendered ${files.length} stills in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
} finally {
  try {
    rmSync(serveUrl, { recursive: true, force: true });
  } catch {}
}

if (sheet) {
  // Contact sheet: 3 columns, each tile labelled with its frame number.
  const py = `
import sys, math
from PIL import Image, ImageDraw
files = sys.argv[2:]
ims = [Image.open(f) for f in files]
w, h = ims[0].size
tw = 640; th = int(h * tw / w); cols = 3 if len(ims) > 2 else len(ims); rows = math.ceil(len(ims) / cols)
out = Image.new("RGB", (cols * tw, rows * (th + 26)), (30, 30, 30))
d = ImageDraw.Draw(out)
for i, (f, im) in enumerate(zip(files, ims)):
    x, y = (i % cols) * tw, (i // cols) * (th + 26)
    out.paste(im.resize((tw, th)), (x, y + 26))
    d.text((x + 8, y + 6), f.split("-")[-1].split(".")[0].lstrip("0") or "0", fill=(255, 255, 0))
out.save(sys.argv[1], quality=85)
`;
  const sheetPath = join(root, outDir, sheet);
  execFileSync("python", ["-c", py, sheetPath, ...files], { stdio: "inherit" });
  console.log(`sheet -> ${sheetPath}`);
}
