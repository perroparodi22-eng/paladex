/**
 * Copies the Draco and Basis (KTX2) decoders that ship with three.js into
 * /public/decoders so models compressed with Draco or textures compressed as
 * KTX2 decode from our own origin (no third-party CDN, CSP-friendly).
 *
 * Runs automatically after `npm install` (postinstall). Safe to re-run.
 * Never fails the install: a missing source is reported and skipped.
 */
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const threeLibs = join(root, "node_modules", "three", "examples", "jsm", "libs");

const jobs: Array<{ from: string; to: string; files: string[] }> = [
  {
    from: join(threeLibs, "draco", "gltf"),
    to: join(root, "public", "decoders", "draco"),
    files: ["draco_decoder.js", "draco_decoder.wasm", "draco_wasm_wrapper.js"],
  },
  {
    from: join(threeLibs, "basis"),
    to: join(root, "public", "decoders", "basis"),
    files: ["basis_transcoder.js", "basis_transcoder.wasm"],
  },
];

let copied = 0;
for (const job of jobs) {
  if (!existsSync(job.from)) {
    console.warn(`[decoders] skipped: ${job.from} not found`);
    continue;
  }
  mkdirSync(job.to, { recursive: true });
  for (const file of job.files) {
    const src = join(job.from, file);
    if (!existsSync(src)) {
      console.warn(`[decoders] skipped missing file ${src}`);
      continue;
    }
    copyFileSync(src, join(job.to, file));
    copied++;
  }
}
console.log(`[decoders] ${copied} decoder files ready in public/decoders`);
