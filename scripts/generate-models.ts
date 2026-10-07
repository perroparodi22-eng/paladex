/**
 * Builds every racket's 3D model as compressed glTF binaries (.glb).
 *
 *   npm run models:build             # all rackets
 *   npm run models:build -- --only adidas-metalbone-3-4
 *
 * Two kinds of models:
 *  - platform: built from a traced reference photo (src/data/designs). The
 *    photo is projected onto the face and frame, geometry comes from the trace.
 *    Written to public/models/platform/<slug>.glb
 *  - placeholder: generic racket of the right shape class, in our own colours,
 *    from the parametric geometry (src/lib/racket-geometry).
 *    Written to public/models/placeholders/<slug>.glb
 *
 * Each model is written twice: a full model and a lightweight <slug>.preview.glb
 * for cards, carousels and first paint. Geometry is welded, quantized and
 * Meshopt-compressed; textures are WebP. Part names follow the convention in
 * docs/3D-PIPELINE.md so the viewer can explode and annotate any model.
 * A manifest with sizes and bounds is written to src/data/models.generated.json.
 */
import { mkdirSync, readFileSync, statSync, writeFileSync, existsSync } from "node:fs";
import * as THREE from "three";
import { toCreasedNormals } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { Document, NodeIO, type Material, type Texture } from "@gltf-transform/core";
import { EXTMeshoptCompression, EXTTextureWebP, KHRMaterialsClearcoat, KHRMeshQuantization } from "@gltf-transform/extensions";
import { dedup, meshopt, prune, weld } from "@gltf-transform/functions";
import { MeshoptEncoder } from "meshoptimizer";
import sharp from "sharp";
import { seedRackets, type SeedRacket } from "../src/data/seed/rackets";
import { photoDesigns } from "../src/data/designs";
import type { PhotoDesign, V2 } from "../src/data/designs/types";
import { buildBlueprint, clipPolygon, DIMS } from "../src/lib/racket-geometry";

export const GENERATOR_VERSION = "1.0.0";

type Lod = "full" | "preview";
const LOD = {
  full: { curve: 12, texture: 1024, gripTexture: 256, lathe: 40, radial: 40 },
  preview: { curve: 5, texture: 512, gripTexture: 128, lathe: 16, radial: 18 },
} as const;

/* ---------------------------------------------------------------- utils */

function srgbToLinear(c: number) {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}
function hexLinear(hex: string): [number, number, number] {
  const n = parseInt(hex.replace("#", ""), 16);
  return [srgbToLinear(((n >> 16) & 255) / 255), srgbToLinear(((n >> 8) & 255) / 255), srgbToLinear((n & 255) / 255)];
}
const vec = (p: V2) => new THREE.Vector2(p[0], p[1]);

function shapeFrom(outer: V2[], holes: V2[][] = [], circles: Array<{ x: number; y: number; r: number }> = []) {
  const s = new THREE.Shape(outer.map(vec));
  for (const h of holes) if (h.length >= 3) s.holes.push(new THREE.Path(h.map(vec))); // e.g. no throat opening traced
  for (const c of circles) {
    const p = new THREE.Path();
    p.absarc(c.x, c.y, c.r, 0, Math.PI * 2, true);
    s.holes.push(p);
  }
  return s;
}

/** Split a non-indexed ExtrudeGeometry into [caps, sides]. */
function splitGroups(g: THREE.BufferGeometry): THREE.BufferGeometry[] {
  const out: THREE.BufferGeometry[] = [];
  const attrs = ["position", "normal", "uv"] as const;
  for (const grp of g.groups) {
    const ng = new THREE.BufferGeometry();
    for (const name of attrs) {
      const a = g.getAttribute(name) as THREE.BufferAttribute | undefined;
      if (!a) continue;
      const size = a.itemSize;
      ng.setAttribute(name, new THREE.Float32BufferAttribute((a.array as Float32Array).slice(grp.start * size, (grp.start + grp.count) * size), size));
    }
    out[grp.materialIndex ?? 0] = ng;
  }
  return out;
}

interface Slab {
  caps: THREE.BufferGeometry;
  sides: THREE.BufferGeometry;
}

/** Extrude a shape so the solid spans z in [z0, z1], optionally with a chamfer/round on the edges. */
function slab(shape: THREE.Shape, z0: number, z1: number, curve: number, bevel?: { t: number; s: number; seg: number }): Slab {
  const bt = bevel?.t ?? 0;
  const depth = z1 - z0 - 2 * bt;
  const g = new THREE.ExtrudeGeometry(shape, {
    depth,
    steps: 1,
    curveSegments: curve,
    bevelEnabled: !!bevel,
    bevelThickness: bt,
    bevelSize: bevel?.s ?? 0,
    bevelOffset: bevel ? -bevel.s : 0,
    bevelSegments: bevel?.seg ?? 1,
  });
  g.translate(0, 0, z0 + bt);
  const [caps, sides] = splitGroups(g);
  g.dispose();
  // toCreasedNormals hashes positions at 1/100 unit; work in millimetres so
  // neighbouring holes (a few mm apart) are never merged.
  sides.scale(1000, 1000, 1000);
  const smooth = toCreasedNormals(sides, (35 * Math.PI) / 180);
  smooth.scale(0.001, 0.001, 0.001);
  return { caps, sides: smooth };
}

/** Taper thickness towards the handle so the frame flows into the grip. */
function taperNeck(g: THREE.BufferGeometry, neckY: number, length: number, minScale: number) {
  const p = g.getAttribute("position") as THREE.BufferAttribute;
  for (let i = 0; i < p.count; i++) {
    const y = p.getY(i);
    if (y >= neckY + length) continue;
    const t = Math.min(1, Math.max(0, (y - neckY) / length));
    const k = minScale + (1 - minScale) * (t * t * (3 - 2 * t));
    p.setZ(i, p.getZ(i) * k);
  }
  p.needsUpdate = true;
}

/** Planar projection of the front photo; back faces read the mirrored point. */
function projectUV(g: THREE.BufferGeometry, map: (x: number, y: number, back: boolean) => [number, number]) {
  const p = g.getAttribute("position") as THREE.BufferAttribute;
  const n = g.getAttribute("normal") as THREE.BufferAttribute;
  const uv = new Float32Array(p.count * 2);
  for (let i = 0; i < p.count; i++) {
    const [u, v] = map(p.getX(i), p.getY(i), n.getZ(i) < 0);
    uv[i * 2] = u;
    uv[i * 2 + 1] = v;
  }
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
}

function stripUV(g: THREE.BufferGeometry) {
  g.deleteAttribute("uv");
  return g;
}

/** Keep only triangles facing +Z (sign 1) or -Z (sign -1). */
function onlyFacing(g: THREE.BufferGeometry, sign: 1 | -1): THREE.BufferGeometry {
  const nrm = g.getAttribute("normal") as THREE.BufferAttribute;
  const keep: number[] = [];
  for (let tri = 0; tri < nrm.count / 3; tri++) {
    const nz = nrm.getZ(tri * 3) + nrm.getZ(tri * 3 + 1) + nrm.getZ(tri * 3 + 2);
    if (nz * sign > 0) keep.push(tri);
  }
  const out = new THREE.BufferGeometry();
  for (const name of ["position", "normal", "uv"]) {
    const a = g.getAttribute(name) as THREE.BufferAttribute | undefined;
    if (!a) continue;
    const size = a.itemSize;
    const arr = new Float32Array(keep.length * 3 * size);
    keep.forEach((tri, k) => arr.set((a.array as Float32Array).subarray(tri * 3 * size, (tri + 1) * 3 * size), k * 3 * size));
    out.setAttribute(name, new THREE.Float32BufferAttribute(arr, size));
  }
  return out;
}

/**
 * The hitting surface. Full models keep separate skins and core so the
 * exploded view can pull them apart; previews use one solid slab.
 */
function faceLayers(
  shape: () => THREE.Shape,
  F: number,
  skin: number,
  curve: number,
  lod: Lod,
  mats: { front: MatSpec; back: MatSpec; edge: MatSpec; core: MatSpec },
  uvMap?: (x: number, y: number, back: boolean) => [number, number],
): Part[] {
  const finish = (g: THREE.BufferGeometry) => {
    if (uvMap) projectUV(g, uvMap);
    else stripUV(g);
    return g;
  };
  if (lod === "preview") {
    const s = slab(shape(), -F / 2, F / 2, curve);
    return [
      {
        name: "part_face",
        prims: [
          { geometry: finish(onlyFacing(s.caps, 1)), material: mats.front },
          { geometry: finish(onlyFacing(s.caps, -1)), material: mats.back },
          { geometry: stripUV(s.sides), material: mats.core },
        ],
      },
    ];
  }
  const front = slab(shape(), F / 2 - skin, F / 2, curve);
  const back = slab(shape(), -F / 2, -F / 2 + skin, curve);
  const core = slab(shape(), -F / 2 + skin, F / 2 - skin, curve);
  return [
    { name: "part_face_front", prims: [{ geometry: finish(front.caps), material: mats.front }, { geometry: stripUV(front.sides), material: mats.edge }] },
    { name: "part_face_back", prims: [{ geometry: finish(back.caps), material: mats.back }, { geometry: stripUV(back.sides), material: mats.edge }] },
    { name: "part_core", prims: [{ geometry: stripUV(core.caps), material: mats.core }, { geometry: stripUV(core.sides), material: mats.core }] },
  ];
}

function insetPolygon(poly: V2[], d: number): V2[] {
  const n = poly.length;
  return poly.map((p, i) => {
    const a = poly[(i - 1 + n) % n];
    const b = poly[(i + 1) % n];
    const n1 = norm([-(p[1] - a[1]), p[0] - a[0]]);
    const n2 = norm([-(b[1] - p[1]), b[0] - p[0]]);
    const avg = norm([n1[0] + n2[0], n1[1] + n2[1]]);
    const cos = Math.max(0.5, n1[0] * avg[0] + n1[1] * avg[1]);
    return [p[0] + (avg[0] * d) / cos, p[1] + (avg[1] * d) / cos] as V2;
  });
}
function norm(v: V2): V2 {
  const l = Math.hypot(v[0], v[1]) || 1;
  return [v[0] / l, v[1] / l];
}

/** Points where a horizontal line crosses a polygon, with outward normals. */
function crossings(poly: V2[], y: number): Array<{ x: number; normal: V2 }> {
  const out: Array<{ x: number; normal: V2 }> = [];
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i];
    const b = poly[(i + 1) % poly.length];
    if ((a[1] - y) * (b[1] - y) > 0 || a[1] === b[1]) continue;
    const t = (y - a[1]) / (b[1] - a[1]);
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    out.push({ x: a[0] + dx * t, normal: norm([dy, -dx]) });
  }
  return out.sort((p, q) => p.x - q.x);
}

/** Elliptic lathe: profile [radius, y] pairs revolved, then squashed in z. */
function ellipticLathe(profile: V2[], rz: number, segments: number, x0 = 0) {
  const g = new THREE.LatheGeometry(profile.map(([r, y]) => new THREE.Vector2(r, y)), segments);
  g.scale(1, 1, rz);
  g.translate(x0, 0, 0);
  return g;
}

/* ------------------------------------------------------------ textures */

/** Fill transparent pixels from their neighbours (holes and edges) so the print never shows cut-outs. */
function inpaint(rgba: Uint8Array, W: number, H: number, maxLayers = 48) {
  const known = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) known[i] = rgba[i * 4 + 3] > 200 ? 1 : 0;
  let frontier: number[] = [];
  const inFrontier = new Uint8Array(W * H);
  const neighbours = (i: number) => {
    const x = i % W;
    const y = (i - x) / W;
    const out: number[] = [];
    for (let dy = -1; dy <= 1; dy++)
      for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dy) continue;
        const nx = x + dx;
        const ny = y + dy;
        if (nx >= 0 && ny >= 0 && nx < W && ny < H) out.push(ny * W + nx);
      }
    return out;
  };
  for (let i = 0; i < W * H; i++) {
    if (known[i]) continue;
    if (neighbours(i).some((q) => known[q])) {
      frontier.push(i);
      inFrontier[i] = 1;
    }
  }
  for (let layer = 0; layer < maxLayers && frontier.length; layer++) {
    const colours = frontier.map((i) => {
      let r = 0;
      let g = 0;
      let b = 0;
      let n = 0;
      for (const q of neighbours(i)) {
        if (!known[q]) continue;
        r += rgba[q * 4];
        g += rgba[q * 4 + 1];
        b += rgba[q * 4 + 2];
        n++;
      }
      return [r / n, g / n, b / n];
    });
    const next: number[] = [];
    frontier.forEach((i, k) => {
      rgba[i * 4] = colours[k][0];
      rgba[i * 4 + 1] = colours[k][1];
      rgba[i * 4 + 2] = colours[k][2];
      rgba[i * 4 + 3] = 255;
      known[i] = 1;
    });
    for (const i of frontier) {
      for (const q of neighbours(i)) {
        if (!known[q] && !inFrontier[q]) {
          inFrontier[q] = 1;
          next.push(q);
        }
      }
    }
    frontier = next;
  }
  for (let i = 0; i < W * H; i++) {
    if (!known[i]) {
      rgba[i * 4] = rgba[i * 4 + 1] = rgba[i * 4 + 2] = 6;
      rgba[i * 4 + 3] = 255;
    }
  }
}

interface PhotoTexture {
  data: Buffer;
  crop: { x: number; y: number; w: number; h: number };
}

async function photoTexture(design: PhotoDesign, height: number): Promise<PhotoTexture> {
  const t = design.trace;
  let img = sharp(design.frontImage).ensureAlpha();
  if (Math.abs(t.rotateDeg) > 1e-3) {
    img = sharp(await img.rotate(t.rotateDeg, { background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toBuffer());
  }
  const s = t.metresPerPixel;
  const xs = t.frameOuter.map((p) => p[0] / s + t.axisX);
  const ys = t.frameOuter.map((p) => t.buttY - p[1] / s);
  const margin = 14;
  const x = Math.max(0, Math.floor(Math.min(...xs)) - margin);
  const y = Math.max(0, Math.floor(Math.min(...ys)) - margin);
  const w = Math.min(t.imageSize[0] - x, Math.ceil(Math.max(...xs)) + margin - x);
  const h = Math.min(t.imageSize[1] - y, Math.ceil(Math.max(...ys)) + margin - y);
  const { data, info } = await img.extract({ left: x, top: y, width: w, height: h }).raw().toBuffer({ resolveWithObject: true });
  const rgba = new Uint8Array(data);
  inpaint(rgba, info.width, info.height);
  const out = await sharp(Buffer.from(rgba), { raw: { width: info.width, height: info.height, channels: 4 } })
    .removeAlpha()
    .resize({ height, kernel: "lanczos3" })
    .webp({ quality: 86, effort: 6 })
    .toBuffer();
  return { data: out, crop: { x, y, w, h } };
}

async function gripTexture(base: string, dots: string, size: number): Promise<Buffer> {
  // Overgrip: a perforation pattern plus one diagonal wrap seam per tile (tiles seamlessly).
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 64 64">
    <rect width="64" height="64" fill="${base}"/>
    <path d="M-4 68 L68 -4" stroke="#000" stroke-opacity="0.55" stroke-width="2.4"/>
    <path d="M-4 66 L66 -4" stroke="#fff" stroke-opacity="0.05" stroke-width="0.8"/>
    <g fill="${dots}" fill-opacity="0.85">
      <circle cx="12" cy="14" r="2.1"/><circle cx="36" cy="9" r="2.1"/><circle cx="54" cy="30" r="2.1"/>
      <circle cx="22" cy="40" r="2.1"/><circle cx="45" cy="52" r="2.1"/><circle cx="8" cy="58" r="2.1"/>
    </g>
  </svg>`;
  return sharp(Buffer.from(svg)).webp({ quality: 90 }).toBuffer();
}

/* -------------------------------------------------------------- scene IR */

interface MatSpec {
  name: string;
  color: string;
  roughness: number;
  metalness?: number;
  clearcoat?: number;
  clearcoatRoughness?: number;
  texture?: Buffer;
}
interface Part {
  name: string;
  prims: Array<{ geometry: THREE.BufferGeometry; material: MatSpec }>;
}

function addHandle(
  parts: Part[],
  lod: Lod,
  opts: { neckY: number; rx: number; rz: number; x0: number; grip: MatSpec; collar: MatSpec; cap: MatSpec; core: MatSpec },
) {
  const L = LOD[lod];
  const { neckY, rx, rz, x0 } = opts;
  const k = rz / rx;
  const capTop = 0.012;
  const collarH = 0.016;
  const gripTop = neckY - collarH;
  // Handle core (visible when the grip is exploded off).
  const core = new THREE.CylinderGeometry(rx * 0.92, rx * 0.92, gripTop - capTop + 0.01, L.radial, 1, true);
  core.scale(1, 1, k);
  core.translate(x0, capTop + (gripTop - capTop + 0.01) / 2, 0);
  parts.push({ name: "part_handle", prims: [{ geometry: stripUV(core), material: opts.core }] });
  // Grip wrap with tiled overgrip texture (u around, v along the handle).
  const grip = new THREE.CylinderGeometry(rx, rx, gripTop - capTop, L.radial, 1, true);
  const uv = grip.getAttribute("uv") as THREE.BufferAttribute;
  const circumference = Math.PI * (rx + rx * k);
  const along = (gripTop - capTop) / circumference;
  for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * 3, uv.getY(i) * along * 3);
  grip.scale(1, 1, k);
  grip.translate(x0, capTop + (gripTop - capTop) / 2, 0);
  parts.push({ name: "part_grip", prims: [{ geometry: grip, material: opts.grip }] });
  // Ribbed collar between grip and frame.
  const ribs: V2[] = [[rx * 0.9, gripTop - 0.001]];
  const n = 5;
  for (let i = 0; i <= n * 4; i++) {
    const t = i / (n * 4);
    ribs.push([rx * (1.05 + 0.035 * Math.cos(t * n * Math.PI * 2)), gripTop + t * collarH]);
  }
  ribs.push([rx * 1.0, neckY + 0.004]);
  ribs.push([rx * 0.8, neckY + 0.006]);
  parts.push({ name: "part_collar", prims: [{ geometry: stripUV(ellipticLathe(ribs, k, L.lathe, x0)), material: opts.collar }] });
  // Butt cap.
  const cap: V2[] = [
    [0.0001, 0],
    [rx * 0.9, 0],
    [rx * 1.13, 0.0025],
    [rx * 1.14, 0.007],
    [rx * 1.06, capTop],
    [rx * 0.95, capTop + 0.002],
  ];
  parts.push({ name: "part_cap", prims: [{ geometry: stripUV(ellipticLathe(cap, k, L.lathe, x0)), material: opts.cap }] });
}

/* ----------------------------------------------------- platform models */

async function buildPhotoRacket(design: PhotoDesign, lod: Lod): Promise<Part[]> {
  const L = LOD[lod];
  const t = design.trace;
  const T = design.thicknessMm / 1000;
  const F = design.faceThicknessMm / 1000;
  const skin = DIMS.skinThickness;
  const tex = await photoTexture(design, L.texture);
  const s = t.metresPerPixel;
  const uvMap = (x: number, y: number, back: boolean): [number, number] => {
    const px = (back && design.mirrorBack ? -x : x) / s + t.axisX;
    const py = t.buttY - y / s;
    return [(px - tex.crop.x) / tex.crop.w, (py - tex.crop.y) / tex.crop.h];
  };

  // Face outline: frame contour inset by the rim, cut by the V above the throat.
  const fb = design.faceBottom;
  const vRegion: V2[] = [
    [-0.5, fb.centerY + fb.slope * 0.5],
    [0, fb.centerY],
    [0.5, fb.centerY + fb.slope * 0.5],
    [0.5, 1],
    [-0.5, 1],
  ];
  const face = clipPolygon(insetPolygon(t.frameOuter, t.faceInsetM), vRegion);

  const printFrame: MatSpec = {
    name: "frame_print",
    color: "#ffffff",
    roughness: design.frameRoughness + 0.08,
    clearcoat: 0.6,
    clearcoatRoughness: 0.18,
    texture: tex.data,
  };
  const frameFinish: MatSpec = { name: "frame_finish", color: design.colors.frame, roughness: design.frameRoughness, clearcoat: 1, clearcoatRoughness: 0.1 };
  const facePrint: MatSpec = { name: "face_print", color: "#e2e2e2", roughness: 0.62, texture: tex.data };
  const faceEdge: MatSpec = { name: "face_edge", color: design.colors.faceEdge, roughness: 0.7 };
  const core: MatSpec = { name: "core_eva", color: design.colors.core, roughness: 0.95 };

  const parts: Part[] = [];
  const bevel = { t: 0.0035, s: 0.0028, seg: lod === "full" ? design.frameBevelSegments : 1 };
  const frame = slab(shapeFrom(t.frameOuter, [face, t.throat]), -T / 2, T / 2, L.curve, bevel);
  taperNeck(frame.caps, t.neckY, 0.055, 0.7);
  taperNeck(frame.sides, t.neckY, 0.055, 0.7);
  frame.caps.computeVertexNormals();
  projectUV(frame.caps, uvMap);
  parts.push({ name: "part_frame", prims: [{ geometry: frame.caps, material: printFrame }, { geometry: stripUV(frame.sides), material: frameFinish }] });

  parts.push(...faceLayers(() => shapeFrom(face, [], t.holes), F, skin, L.curve, lod, { front: facePrint, back: facePrint, edge: faceEdge, core }, uvMap));

  if (design.screws) {
    const steel: MatSpec = { name: "screw_steel", color: "#8e979f", roughness: 0.32, metalness: 1 };
    const ring: MatSpec = { name: "screw_ring", color: design.screws.ring, roughness: 0.3, metalness: 0.6 };
    const heads: THREE.BufferGeometry[] = [];
    const rings: THREE.BufferGeometry[] = [];
    for (const y of design.screws.y) {
      const hits = crossings(t.frameOuter, y);
      for (const hit of [hits[0], hits[hits.length - 1]]) {
        if (!hit) continue;
        const dir = new THREE.Vector3(hit.normal[0], hit.normal[1], 0).normalize();
        const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
        const head = new THREE.CylinderGeometry(0.0031, 0.0031, 0.0024, lod === "full" ? 20 : 10);
        head.applyQuaternion(q);
        head.translate(hit.x + dir.x * 0.0004, y + dir.y * 0.0004, 0);
        heads.push(stripUV(head));
        const torus = new THREE.TorusGeometry(0.0037, 0.0008, 8, lod === "full" ? 24 : 12);
        torus.rotateX(Math.PI / 2);
        torus.applyQuaternion(q);
        torus.translate(hit.x + dir.x * 0.0002, y + dir.y * 0.0002, 0);
        rings.push(stripUV(torus));
      }
    }
    parts.push({
      name: "part_screws",
      prims: [
        ...heads.map((geometry) => ({ geometry, material: steel })),
        ...rings.map((geometry) => ({ geometry, material: ring })),
      ],
    });
  }

  const gripTex = await gripTexture(design.colors.grip, design.colors.gripDots, L.gripTexture);
  addHandle(parts, lod, {
    neckY: t.neckY,
    rx: t.grip.halfWidth,
    rz: t.grip.halfWidth * 0.8,
    x0: t.gripAxisOffsetM,
    grip: { name: "grip_wrap", color: "#ffffff", roughness: 0.88, texture: gripTex },
    collar: { name: "collar", color: design.colors.collar, roughness: 0.45, clearcoat: 0.4, clearcoatRoughness: 0.3 },
    cap: { name: "butt_cap", color: design.colors.collar, roughness: 0.5 },
    core: { name: "handle_core", color: "#1a1c20", roughness: 0.7 },
  });
  return parts;
}

/* -------------------------------------------------- placeholder models */

async function buildPlaceholder(r: SeedRacket, lod: Lod): Promise<Part[]> {
  const L = LOD[lod];
  const v = r.visual;
  const bp = buildBlueprint(r.specs.shape, v, { samples: lod === "full" ? 72 : 40, sweetSpotScore: r.evaluation.sweetSpot });
  const T = DIMS.frameThickness;
  const F = DIMS.faceThickness;
  const skin = DIMS.skinThickness;
  const frameMat: MatSpec = { name: "frame_finish", color: v.frame, roughness: 0.34, clearcoat: 1, clearcoatRoughness: 0.12 };
  const faceMat: MatSpec = { name: "face_skin", color: v.face, roughness: r.specs.surfaceFinish === "smooth" ? 0.42 : 0.66, clearcoat: 0.25, clearcoatRoughness: 0.4 };
  const faceEdge: MatSpec = { name: "face_edge", color: v.frame, roughness: 0.7 };
  const coreMat: MatSpec = { name: "core_eva", color: "#d9dbd5", roughness: 0.95 };
  const accent: MatSpec = { name: "decal_accent", color: v.accent, roughness: 0.55 };
  const accent2: MatSpec = { name: "decal_accent2", color: v.accent2, roughness: 0.55 };
  const bumperMat: MatSpec = { name: "bumper", color: "#2a2e35", roughness: 0.58 };

  const parts: Part[] = [];
  const frame = slab(shapeFrom(bp.frameOuter, [bp.face, bp.heart]), -T / 2, T / 2, L.curve, { t: 0.004, s: 0.003, seg: lod === "full" ? 3 : 1 });
  taperNeck(frame.caps, DIMS.neckBottom, 0.05, 0.72);
  taperNeck(frame.sides, DIMS.neckBottom, 0.05, 0.72);
  frame.caps.computeVertexNormals();
  parts.push({ name: "part_frame", prims: [{ geometry: stripUV(frame.caps), material: frameMat }, { geometry: stripUV(frame.sides), material: frameMat }] });

  parts.push(...faceLayers(() => shapeFrom(bp.face, [], bp.holes), F, skin, L.curve, lod, { front: faceMat, back: faceMat, edge: faceEdge, core: coreMat }));

  // Printed graphics as thin layers on both faces (mirrored on the back so they read correctly).
  // The preview keeps only the visible top surface of each print.
  const decalPrims: Part["prims"] = [];
  for (const d of bp.decals) {
    const holes = d.holes.map((i) => bp.holes[i]);
    const inner = d.inner ? [d.inner] : [];
    const mat = d.tone === "accent" ? accent : accent2;
    const f = slab(shapeFrom(d.polygon, inner, holes), F / 2, F / 2 + DIMS.decalThickness, L.curve);
    decalPrims.push({ geometry: stripUV(onlyFacing(f.caps, 1)), material: mat });
    if (lod === "full") decalPrims.push({ geometry: stripUV(f.sides), material: mat });
    const mirrorPoly = d.polygon.map(([x, y]) => [-x, y] as V2).reverse();
    const mirrorInner = inner.map((poly) => poly.map(([x, y]) => [-x, y] as V2).reverse());
    const b = slab(shapeFrom(mirrorPoly, mirrorInner, holes.map((h) => ({ ...h, x: -h.x }))), -F / 2 - DIMS.decalThickness, -F / 2, L.curve);
    decalPrims.push({ geometry: stripUV(onlyFacing(b.caps, -1)), material: mat });
    if (lod === "full") decalPrims.push({ geometry: stripUV(b.sides), material: mat });
  }
  if (decalPrims.length) parts.push({ name: "part_print", prims: decalPrims });

  const bumper = slab(shapeFrom(bp.bumper), -T / 2 - 0.0012, T / 2 + 0.0012, L.curve, { t: 0.0015, s: 0.0012, seg: 1 });
  parts.push({ name: "part_bumper", prims: [{ geometry: stripUV(bumper.caps), material: bumperMat }, { geometry: stripUV(bumper.sides), material: bumperMat }] });

  if (bp.bridge) {
    const bridge = slab(shapeFrom(bp.bridge), -T / 2 + 0.003, T / 2 - 0.003, L.curve, { t: 0.0015, s: 0.0012, seg: 1 });
    parts.push({ name: "part_bridge", prims: [{ geometry: stripUV(bridge.caps), material: frameMat }, { geometry: stripUV(bridge.sides), material: frameMat }] });
  }

  const gripTex = await gripTexture(v.grip, v.grip === "#f1f3ee" ? "#9aa4ae" : "#d6dadf", L.gripTexture);
  addHandle(parts, lod, {
    neckY: DIMS.neckBottom,
    rx: DIMS.handle.rx + 0.0008,
    rz: DIMS.handle.rz + 0.0008,
    x0: 0,
    grip: { name: "grip_wrap", color: "#ffffff", roughness: 0.88, texture: gripTex },
    collar: { name: "collar", color: v.frame, roughness: 0.45 },
    cap: { name: "butt_cap", color: v.frame, roughness: 0.5 },
    core: { name: "handle_core", color: "#1a1c20", roughness: 0.7 },
  });
  return parts;
}

/* ------------------------------------------------------------ glTF out */

interface BuildInfo {
  bytes: number;
  triangles: number;
  bbox: { min: [number, number, number]; max: [number, number, number] };
}

async function writeGlb(parts: Part[], file: string, extras: Record<string, unknown>): Promise<BuildInfo> {
  const doc = new Document();
  doc.getRoot().getAsset().generator = `paladex-model-generator ${GENERATOR_VERSION}`;
  const buffer = doc.createBuffer();
  const clearcoatExt = doc.createExtension(KHRMaterialsClearcoat);
  doc.createExtension(EXTTextureWebP).setRequired(true);
  const scene = doc.createScene("racket");
  const root = doc.createNode("racket").setExtras({ paladex: extras });
  scene.addChild(root);

  const materials = new Map<string, Material>();
  const textures = new Map<Buffer, Texture>();
  const getMaterial = (m: MatSpec): Material => {
    const key = `${m.name}|${m.color}|${m.roughness}`;
    const hit = materials.get(key);
    if (hit) return hit;
    const mat = doc
      .createMaterial(m.name)
      .setBaseColorFactor([...hexLinear(m.color), 1])
      .setRoughnessFactor(m.roughness)
      .setMetallicFactor(m.metalness ?? 0);
    if (m.texture) {
      let tex = textures.get(m.texture);
      if (!tex) {
        tex = doc.createTexture(`${m.name}_basecolor`).setMimeType("image/webp").setImage(new Uint8Array(m.texture));
        textures.set(m.texture, tex);
      }
      mat.setBaseColorTexture(tex);
    }
    if (m.clearcoat) {
      mat.setExtension(
        "KHR_materials_clearcoat",
        clearcoatExt.createClearcoat().setClearcoatFactor(m.clearcoat).setClearcoatRoughnessFactor(m.clearcoatRoughness ?? 0.1),
      );
    }
    materials.set(key, mat);
    return mat;
  };

  let triangles = 0;
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (const part of parts) {
    const mesh = doc.createMesh(part.name);
    for (const { geometry, material } of part.prims) {
      const g = geometry.index ? geometry.toNonIndexed() : geometry;
      const pos = g.getAttribute("position") as THREE.BufferAttribute;
      if (!pos || pos.count === 0) continue;
      if (!g.getAttribute("normal")) g.computeVertexNormals();
      const prim = doc.createPrimitive();
      const posArr = new Float32Array(pos.array as Float32Array);
      for (let i = 0; i < pos.count; i++) {
        for (let k = 0; k < 3; k++) {
          min[k] = Math.min(min[k], posArr[i * 3 + k]);
          max[k] = Math.max(max[k], posArr[i * 3 + k]);
        }
      }
      prim.setAttribute("POSITION", doc.createAccessor().setType("VEC3").setArray(posArr).setBuffer(buffer));
      prim.setAttribute(
        "NORMAL",
        doc.createAccessor().setType("VEC3").setArray(new Float32Array((g.getAttribute("normal") as THREE.BufferAttribute).array as Float32Array)).setBuffer(buffer),
      );
      const uv = g.getAttribute("uv") as THREE.BufferAttribute | undefined;
      if (uv && material.texture) {
        prim.setAttribute("TEXCOORD_0", doc.createAccessor().setType("VEC2").setArray(new Float32Array(uv.array as Float32Array)).setBuffer(buffer));
      }
      prim.setMaterial(getMaterial(material));
      mesh.addPrimitive(prim);
      triangles += pos.count / 3;
    }
    root.addChild(doc.createNode(part.name).setMesh(mesh));
  }

  await MeshoptEncoder.ready;
  await doc.transform(weld(), dedup(), prune(), meshopt({ encoder: MeshoptEncoder, level: "medium" }));
  const io = new NodeIO()
    .registerExtensions([EXTMeshoptCompression, KHRMeshQuantization, KHRMaterialsClearcoat, EXTTextureWebP])
    .registerDependencies({ "meshopt.encoder": MeshoptEncoder });
  const glb = await io.writeBinary(doc);
  writeFileSync(file, glb);
  return {
    bytes: statSync(file).size,
    triangles: Math.round(triangles),
    bbox: {
      min: min.map((n) => +n.toFixed(4)) as [number, number, number],
      max: max.map((n) => +n.toFixed(4)) as [number, number, number],
    },
  };
}

/* ----------------------------------------------------------------- main */

export interface ModelManifestEntry {
  kind: "platform" | "placeholder";
  url: string;
  previewUrl: string;
  bytes: number;
  previewBytes: number;
  triangles: number;
  bbox: BuildInfo["bbox"];
  version: string;
  generatedAt: string;
}

async function main() {
  const onlyIdx = process.argv.indexOf("--only");
  const only = onlyIdx > -1 ? process.argv[onlyIdx + 1] : null;
  const manifestPath = "src/data/models.generated.json";
  const manifest: Record<string, ModelManifestEntry> = existsSync(manifestPath) ? JSON.parse(readFileSync(manifestPath, "utf8")) : {};
  mkdirSync("public/models/platform", { recursive: true });
  mkdirSync("public/models/placeholders", { recursive: true });

  for (const r of seedRackets) {
    if (only && r.slug !== only) continue;
    if (r.noModel) {
      delete manifest[r.slug];
      console.log(`skipped     ${r.slug} (no model planned)`);
      continue;
    }
    const design = photoDesigns[r.slug];
    const kind = design ? "platform" : "placeholder";
    const dir = design ? "platform" : "placeholders";
    const extras = {
      kind,
      slug: r.slug,
      shape: r.specs.shape,
      generator: GENERATOR_VERSION,
      units: "m",
      orientation: "+Y butt-to-tip, +Z front face",
      source: design ? `Built by Paladex from reference photos (${design.frontImage})` : "Generic placeholder; not the real design",
    };
    const fullParts = design ? await buildPhotoRacket(design, "full") : await buildPlaceholder(r, "full");
    const full = await writeGlb(fullParts, `public/models/${dir}/${r.slug}.glb`, extras);
    const previewParts = design ? await buildPhotoRacket(design, "preview") : await buildPlaceholder(r, "preview");
    const preview = await writeGlb(previewParts, `public/models/${dir}/${r.slug}.preview.glb`, { ...extras, lod: "preview" });
    const version = `${GENERATOR_VERSION}-${full.bytes.toString(36)}`;
    manifest[r.slug] = {
      kind,
      url: `/models/${dir}/${r.slug}.glb?v=${version}`,
      previewUrl: `/models/${dir}/${r.slug}.preview.glb?v=${version}`,
      bytes: full.bytes,
      previewBytes: preview.bytes,
      triangles: full.triangles,
      bbox: full.bbox,
      version,
      generatedAt: new Date().toISOString(),
    };
    console.log(
      `${kind.padEnd(11)} ${r.slug.padEnd(36)} full ${(full.bytes / 1024).toFixed(0).padStart(4)} KB · preview ${(preview.bytes / 1024).toFixed(0).padStart(4)} KB · ${full.triangles} tris`,
    );
  }
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 1));
  console.log(`manifest -> ${manifestPath}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
