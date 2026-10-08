/**
 * Optimises a racket model you were given (an official or licensed GLB/GLTF)
 * for the web, writing the two files the viewer expects:
 *
 *   npm run models:optimize -- --in path/to/model.glb --slug nox-at10-2026
 *   npm run models:optimize -- --in model.glb --slug x --out-dir public/models/official
 *
 *   <out-dir>/<slug>.glb          full model: textures WebP, at most 2048 px
 *   <out-dir>/<slug>.preview.glb  light version for cards and first paint:
 *                                 about 35% of the triangles, textures 1024 px
 *
 * Both get weld → dedup → prune → resample → (simplify) → WebP textures →
 * Meshopt, the same compression the platform models use (scripts/generate-models.ts).
 * Draco- and Meshopt-compressed inputs are decoded first.
 *
 * Paste the two URLs into the admin (Model → URL / light version). The script
 * checks the model's size and orientation against the convention in
 * docs/3D-PIPELINE.md (metres, +Y butt → tip, +Z front face) and warns, but
 * does not move or scale anything: fix those in the source file.
 */
import { mkdirSync, statSync } from "node:fs";
import { basename, extname, join } from "node:path";
import { parseArgs } from "node:util";
import { NodeIO, type Document, type Transform } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { dedup, getBounds, meshopt, prune, resample, simplify, textureCompress, weld } from "@gltf-transform/functions";
import draco3d from "draco3d";
import { MeshoptDecoder, MeshoptEncoder, MeshoptSimplifier } from "meshoptimizer";
import sharp from "sharp";

const { values: args } = parseArgs({
  options: {
    in: { type: "string" },
    slug: { type: "string" },
    "out-dir": { type: "string", default: "public/models/official" },
    ratio: { type: "string", default: "0.35" },
  },
});

function fail(message: string): never {
  console.error(`models:optimize: ${message}`);
  process.exit(1);
}

const input = args.in ?? fail("pass --in <model.glb|.gltf>");
if (![".glb", ".gltf"].includes(extname(input).toLowerCase())) fail("the input must be a .glb or .gltf file");
const slug = args.slug ?? basename(input, extname(input)).toLowerCase();
if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) fail(`"${slug}" is not a valid slug (lowercase letters, numbers and dashes)`);
const ratio = Number(args.ratio);
if (!(ratio > 0 && ratio <= 1)) fail("--ratio must be between 0 and 1");
const outDir = args["out-dir"]!;

const LODS = {
  full: { file: `${slug}.glb`, texture: 2048, ratio: 1 },
  preview: { file: `${slug}.preview.glb`, texture: 1024, ratio },
} as const;

async function createIO() {
  await Promise.all([MeshoptDecoder.ready, MeshoptEncoder.ready, MeshoptSimplifier.ready]);
  return new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
    "draco3d.decoder": await draco3d.createDecoderModule(),
    "meshopt.decoder": MeshoptDecoder,
    "meshopt.encoder": MeshoptEncoder,
  });
}

function stats(doc: Document) {
  let triangles = 0;
  for (const mesh of doc.getRoot().listMeshes())
    for (const prim of mesh.listPrimitives()) {
      const count = prim.getIndices()?.getCount() ?? prim.getAttribute("POSITION")?.getCount() ?? 0;
      if (prim.getMode() === 4) triangles += count / 3;
    }
  return { triangles: Math.round(triangles), textures: doc.getRoot().listTextures().length };
}

/** Warn when the model breaks the site's size/orientation convention. */
function checkConvention(doc: Document) {
  const scene = doc.getRoot().getDefaultScene() ?? doc.getRoot().listScenes()[0];
  if (!scene) return fail("the file has no scene");
  const { min, max } = getBounds(scene);
  const size = max.map((v, i) => v - min[i]);
  const longest = size.indexOf(Math.max(...size));
  console.log(`  size ${size.map((v) => v.toFixed(3)).join(" × ")} (x × y × z)`);
  const length = size[longest];
  if (length > 2) console.warn(`  ! longest side is ${length.toFixed(1)}: looks like centimetres or millimetres, not metres (a racket is about 0.46 m)`);
  else if (length < 0.2) console.warn(`  ! longest side is ${length.toFixed(3)} m: too small for a racket (about 0.46 m)`);
  if (longest !== 1) console.warn(`  ! the racket's length runs along ${"xyz"[longest]}, not y (butt → tip should be +Y)`);
  if (size[2] > size[0]) console.warn("  ! the model is deeper (z) than wide (x): the face should point along +Z");
}

async function build(io: NodeIO, lod: keyof typeof LODS) {
  const cfg = LODS[lod];
  const doc = await io.read(input);
  const steps: Transform[] = [weld(), dedup(), prune(), resample()];
  if (cfg.ratio < 1) steps.push(simplify({ simplifier: MeshoptSimplifier, ratio: cfg.ratio, error: 0.005 }));
  steps.push(
    textureCompress({ encoder: sharp, targetFormat: "webp", resize: [cfg.texture, cfg.texture] }),
    meshopt({ encoder: MeshoptEncoder, level: "medium" }),
  );
  await doc.transform(...steps);
  const out = join(outDir, cfg.file);
  await io.write(out, doc);
  return { out, bytes: statSync(out).size, ...stats(doc) };
}

const kb = (n: number) => `${(n / 1024).toFixed(0)} KB`;

async function main() {
  const io = await createIO();
  const source = await io.read(input);
  const before = stats(source);
  console.log(`${input}: ${kb(statSync(input).size)}, ${before.triangles} triangles, ${before.textures} textures`);
  checkConvention(source);
  mkdirSync(outDir, { recursive: true });
  for (const lod of ["full", "preview"] as const) {
    const r = await build(io, lod);
    console.log(`  ${lod.padEnd(7)} ${r.out}: ${kb(r.bytes)}, ${r.triangles} triangles`);
  }
  const publicPath = /^(?:\.\/)?public(\/.*)$/.exec(outDir.replace(/\\/g, "/").replace(/\/$/, ""));
  if (publicPath) console.log(`\nIn the admin, use ${publicPath[1]}/${LODS.full.file} and ${publicPath[1]}/${LODS.preview.file}`);
}

main().catch((err) => fail(err instanceof Error ? err.message : String(err)));
