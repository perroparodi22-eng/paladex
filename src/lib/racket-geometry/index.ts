/**
 * Racket geometry: one parametric description of a padel racket, shared by
 *  - scripts/generate-placeholder-models.ts (builds the placeholder .glb files)
 *  - components/racket/RacketIllustration.tsx (the SVG poster / fallback image)
 * so the 3D placeholder and the illustration always match.
 *
 * Units are metres. Axes follow the 3D model convention (docs/3D-PIPELINE.md):
 *   +Y along the racket from the butt cap (y = 0) to the tip (y = 0.455)
 *   +X to the right when looking at the front face
 *   +Z out of the front face
 * Dimensions follow the regulation maxima (length 45.5 cm, width 26 cm,
 * profile 38 mm). This is a generic racket of the right shape class, not any
 * real model's geometry.
 */
import type { RacketShape, RacketVisual } from "@/domain/types";

export type Vec2 = [number, number];

export const DIMS = {
  length: 0.455,
  headHalfWidth: 0.13,
  headBottom: 0.178,
  frameWidth: 0.014,
  frameThickness: 0.038,
  faceThickness: 0.034,
  skinThickness: 0.0012,
  decalThickness: 0.0004,
  neckBottom: 0.135,
  heartBottom: 0.15,
  neckHalfWidth: 0.0185,
  handle: { y0: 0.011, y1: 0.142, rx: 0.0165, rz: 0.0135 },
  grip: { y0: 0.013, y1: 0.124, pad: 0.0013 },
  cap: { y0: 0, y1: 0.012, rx: 0.0188, rz: 0.0158 },
  holeRadius: 0.0062,
  holeSpacing: 0.0228,
  bumperFrom: 0.6,
  bumperOut: 0.0016,
  bumperIn: 0.0085,
} as const;

/** Shape parameters: superellipse exponent and relative height of the widest point. */
const SHAPE_PARAMS: Record<RacketShape, { n: number; peak: number; sweet: number; sweetSize: number }> = {
  round: { n: 2.1, peak: 0.48, sweet: 0.45, sweetSize: 1.15 },
  teardrop: { n: 2.25, peak: 0.58, sweet: 0.5, sweetSize: 1.0 },
  hybrid: { n: 2.35, peak: 0.63, sweet: 0.53, sweetSize: 0.94 },
  diamond: { n: 2.5, peak: 0.7, sweet: 0.58, sweetSize: 0.84 },
};

/* ------------------------------------------------------------ math utils */

export const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const sub = (a: Vec2, b: Vec2): Vec2 => [a[0] - b[0], a[1] - b[1]];
const add = (a: Vec2, b: Vec2): Vec2 => [a[0] + b[0], a[1] + b[1]];
const scale = (a: Vec2, s: number): Vec2 => [a[0] * s, a[1] * s];
const len = (a: Vec2) => Math.hypot(a[0], a[1]);
const norm = (a: Vec2): Vec2 => {
  const l = len(a) || 1;
  return [a[0] / l, a[1] / l];
};

export function cubicBezier(p0: Vec2, p1: Vec2, p2: Vec2, p3: Vec2, steps: number): Vec2[] {
  const out: Vec2[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const mt = 1 - t;
    const a = mt * mt * mt;
    const b = 3 * mt * mt * t;
    const c = 3 * mt * t * t;
    const d = t * t * t;
    out.push([
      a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
      a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    ]);
  }
  return out;
}

/** Signed area (positive = counter-clockwise). */
export function polygonArea(poly: Vec2[]): number {
  let s = 0;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    s += (poly[j][0] - poly[i][0]) * (poly[j][1] + poly[i][1]);
  }
  return s / 2;
}

export function pointInPolygon(p: Vec2, poly: Vec2[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function distToSegment(p: Vec2, a: Vec2, b: Vec2): number {
  const ab = sub(b, a);
  const t = clamp01(((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / (ab[0] * ab[0] + ab[1] * ab[1] || 1));
  return len(sub(p, add(a, scale(ab, t))));
}

export function distanceToPolygonEdge(p: Vec2, poly: Vec2[]): number {
  let d = Infinity;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) d = Math.min(d, distToSegment(p, poly[j], poly[i]));
  return d;
}

/** Sutherland–Hodgman: clip `subject` by a convex `clip` polygon (both CCW). */
export function clipPolygon(subject: Vec2[], clip: Vec2[]): Vec2[] {
  let output = subject;
  for (let i = 0; i < clip.length; i++) {
    const a = clip[i];
    const b = clip[(i + 1) % clip.length];
    const input = output;
    output = [];
    if (input.length === 0) break;
    const inside = (p: Vec2) => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0;
    const intersect = (p: Vec2, q: Vec2): Vec2 => {
      const a1 = b[1] - a[1];
      const b1 = a[0] - b[0];
      const c1 = a1 * a[0] + b1 * a[1];
      const a2 = q[1] - p[1];
      const b2 = p[0] - q[0];
      const c2 = a2 * p[0] + b2 * p[1];
      const det = a1 * b2 - a2 * b1 || 1e-12;
      return [(b2 * c1 - b1 * c2) / det, (a1 * c2 - a2 * c1) / det];
    };
    for (let j = 0; j < input.length; j++) {
      const cur = input[j];
      const prev = input[(j + input.length - 1) % input.length];
      const curIn = inside(cur);
      const prevIn = inside(prev);
      if (curIn) {
        if (!prevIn) output.push(intersect(prev, cur));
        output.push(cur);
      } else if (prevIn) {
        output.push(intersect(prev, cur));
      }
    }
  }
  return output;
}

/** Reduce near-duplicate consecutive points (clipping can create them). */
function dedupe(poly: Vec2[], eps = 1e-6): Vec2[] {
  const out: Vec2[] = [];
  for (const p of poly) {
    const last = out[out.length - 1];
    if (!last || Math.abs(last[0] - p[0]) > eps || Math.abs(last[1] - p[1]) > eps) out.push(p);
  }
  if (out.length > 1) {
    const a = out[0];
    const b = out[out.length - 1];
    if (Math.abs(a[0] - b[0]) <= eps && Math.abs(a[1] - b[1]) <= eps) out.pop();
  }
  return out;
}

/* --------------------------------------------------------------- outline */

function profile(shape: RacketShape) {
  const p = SHAPE_PARAMS[shape];
  const k = Math.log(0.5) / Math.log(p.peak);
  return (t: number) => {
    const tt = Math.pow(clamp01(t), k);
    const s = Math.abs(2 * tt - 1);
    return Math.pow(Math.max(0, 1 - Math.pow(s, p.n)), 1 / p.n);
  };
}

/** A point on the right side of the head outline at relative height t (0 bottom, 1 top), inset by `inset`. */
export function headPoint(shape: RacketShape, inset: number, t: number): Vec2 {
  const a = DIMS.headHalfWidth - inset;
  const y0 = DIMS.headBottom + inset;
  const y1 = DIMS.length - inset;
  return [a * profile(shape)(t), y0 + (y1 - y0) * clamp01(t)];
}

/** Closed CCW head outline: bottom point, right side up, top, left side down. */
export function headOutline(shape: RacketShape, inset = 0, samples = 64): Vec2[] {
  const right: Vec2[] = [];
  for (let i = 0; i <= samples; i++) {
    const u = i / samples;
    right.push(headPoint(shape, inset, (1 - Math.cos(Math.PI * u)) / 2));
  }
  const left = right
    .slice(1, -1)
    .reverse()
    .map(([x, y]) => [-x, y] as Vec2);
  return [...right, ...left];
}

/**
 * Right side of the head outline between t0 and t1 (inclusive). Samples are
 * packed towards the top and bottom of the head, where the curve turns fastest.
 */
function headArc(shape: RacketShape, inset: number, t0: number, t1: number, samples: number): Vec2[] {
  const pts: Vec2[] = [];
  for (let i = 0; i <= samples; i++) {
    const u = i / samples;
    let f = u;
    if (t1 >= 1 && t0 > 0) f = Math.sin((Math.PI / 2) * u);
    else if (t0 <= 0 && t1 < 1) f = 1 - Math.cos((Math.PI / 2) * u);
    else if (t0 <= 0 && t1 >= 1) f = (1 - Math.cos(Math.PI * u)) / 2;
    pts.push(headPoint(shape, inset, t0 + (t1 - t0) * f));
  }
  return pts;
}

const mirror = (pts: Vec2[]): Vec2[] => pts.map(([x, y]) => [-x, y] as Vec2);

/* ---------------------------------------------------------------- frame */

const T_ARM_OUTER = 0.2;
const T_ARM_INNER = 0.07;

/** Outer contour of the frame: head, both arms and the neck, CCW. */
export function frameOuter(shape: RacketShape, samples = 64): Vec2[] {
  const neck: Vec2 = [DIMS.neckHalfWidth, DIMS.neckBottom];
  const J = headPoint(shape, 0, T_ARM_OUTER);
  const tangent = norm(sub(headPoint(shape, 0, T_ARM_OUTER + 0.01), J));
  const armR = cubicBezier(neck, [neck[0] + 0.004, neck[1] + 0.036], sub(J, scale(tangent, 0.05)), J, 18);
  // Head from the arm junction over the top: right side up, then left side down.
  const right = headArc(shape, 0, T_ARM_OUTER, 1, Math.round(samples * 0.6)).slice(1);
  const leftDown = mirror(headArc(shape, 0, T_ARM_OUTER, 1, Math.round(samples * 0.6)))
    .reverse()
    .slice(1);
  const armL = mirror(armR).reverse().slice(1);
  return dedupe([...armR, ...right, ...leftDown, ...armL]);
}

/** The throat ("heart") opening between the arms, CCW. */
export function heartOpening(shape: RacketShape): Vec2[] {
  const V: Vec2 = [0, DIMS.heartBottom];
  const K = headPoint(shape, 0, T_ARM_INNER);
  const innerR = cubicBezier(V, [0.016, V[1] + 0.004], [K[0] - 0.006, K[1] - 0.02], K, 14);
  // Bottom arc of the head from K (right) through the lowest point to K (left).
  const arcRight = headArc(shape, 0, 0, T_ARM_INNER, 10).reverse(); // K -> bottom
  const arcLeft = mirror(headArc(shape, 0, 0, T_ARM_INNER, 10)).slice(1); // bottom -> K_L
  const innerL = mirror(innerR).reverse(); // K_L -> V
  const poly = dedupe([...innerR, ...arcRight.slice(1), ...arcLeft, ...innerL.slice(1)]);
  // Ensure CCW orientation.
  return polygonArea(poly) < 0 ? poly.reverse() : poly;
}

/** Optional vertical bridge in the throat (a separate solid). */
export function bridgeBar(): Vec2[] {
  const w = 0.0045;
  return [
    [-w, DIMS.heartBottom - 0.004],
    [w, DIMS.heartBottom - 0.004],
    [w, DIMS.headBottom + 0.006],
    [-w, DIMS.headBottom + 0.006],
  ];
}

/** Protective bumper band over the top of the frame, CCW. */
export function bumperBand(shape: RacketShape, samples = 40): Vec2[] {
  const outer = headArc(shape, -DIMS.bumperOut, DIMS.bumperFrom, 1, samples);
  const inner = headArc(shape, DIMS.bumperIn, DIMS.bumperFrom, 1, samples);
  const right = outer; // up the right side
  const left = mirror(outer).reverse().slice(1); // down the left side
  const innerLeft = mirror(inner); // left inner, from start up to top
  const innerRight = inner.slice(0, -1).reverse(); // right inner, from top back down
  const poly = dedupe([...right, ...left, ...innerLeft, ...innerRight.slice(0)]);
  return polygonArea(poly) < 0 ? poly.reverse() : poly;
}

/* ----------------------------------------------------------------- holes */

export interface Hole {
  x: number;
  y: number;
  r: number;
}

function faceCenter(shape: RacketShape): Vec2 {
  const inset = DIMS.frameWidth;
  const y0 = DIMS.headBottom + inset;
  const y1 = DIMS.length - inset;
  return [0, y0 + (y1 - y0) * 0.5];
}

export function racketHoles(shape: RacketShape, pattern: RacketVisual["holes"]): Hole[] {
  const r = DIMS.holeRadius;
  const safe = headOutline(shape, DIMS.frameWidth + r + 0.0062, 72);
  const holes: Hole[] = [];
  if (pattern === "rings") {
    const c = faceCenter(shape);
    const base = headOutline(shape, DIMS.frameWidth + r + 0.0066, 96);
    for (const s of [0.88, 0.69, 0.5, 0.31, 0.13]) {
      const ring = base.map(([x, y]) => [c[0] + (x - c[0]) * s, c[1] + (y - c[1]) * s] as Vec2);
      // Perimeter and evenly spaced samples by arc length.
      const seg: number[] = [];
      let per = 0;
      for (let i = 0; i < ring.length; i++) {
        const d = len(sub(ring[(i + 1) % ring.length], ring[i]));
        seg.push(d);
        per += d;
      }
      const count = Math.max(4, Math.floor(per / (DIMS.holeSpacing * 1.04)));
      const step = per / count;
      let target = step / 2;
      let acc = 0;
      for (let i = 0; i < ring.length && holes.length < 400; i++) {
        while (acc + seg[i] >= target && target < per) {
          const f = (target - acc) / seg[i];
          const p = add(ring[i], scale(sub(ring[(i + 1) % ring.length], ring[i]), f));
          if (pointInPolygon(p, safe)) holes.push({ x: p[0], y: p[1], r });
          target += step;
        }
        acc += seg[i];
      }
    }
    holes.push({ x: c[0], y: c[1], r });
  } else {
    const c = faceCenter(shape);
    const s = DIMS.holeSpacing;
    const dy = s * Math.sin(Math.PI / 3);
    for (let row = -12; row <= 12; row++) {
      const y = c[1] + row * dy;
      const offset = row % 2 === 0 ? 0 : s / 2;
      for (let col = -8; col <= 8; col++) {
        const x = col * s + offset;
        if (pointInPolygon([x, y], safe)) holes.push({ x, y, r });
      }
    }
  }
  return holes;
}

/* --------------------------------------------------------------- decals */

export interface Decal {
  polygon: Vec2[];
  /** Indexes into the hole list for holes that pass through this decal. */
  holes: number[];
  tone: "accent" | "accent2";
}

function band(from: Vec2, to: Vec2, width: number): Vec2[] {
  const d = norm(sub(to, from));
  const n: Vec2 = [-d[1] * (width / 2), d[0] * (width / 2)];
  return [sub(from, n), sub(to, n), add(to, n), add(from, n)];
}

function decalShapes(shape: RacketShape, pattern: RacketVisual["pattern"]): Array<{ poly: Vec2[]; tone: Decal["tone"]; ring?: { cx: number; cy: number; r0: number; r1: number } }> {
  const face = headOutline(shape, DIMS.frameWidth + 0.003, 72);
  const c = faceCenter(shape);
  const clip = (p: Vec2[]) => dedupe(clipPolygon(p, face));
  switch (pattern) {
    case "sweep":
      return [
        { poly: clip(band([-0.16, c[1] - 0.13], [0.16, c[1] + 0.09], 0.046)), tone: "accent" },
        { poly: clip(band([-0.16, c[1] - 0.075], [0.16, c[1] + 0.145], 0.012)), tone: "accent2" },
      ];
    case "split": {
      const cut = c[1] + 0.035;
      const half: Vec2[] = [
        [-0.2, cut - 0.012],
        [0.2, cut + 0.012],
        [0.2, 0.6],
        [-0.2, 0.6],
      ];
      return [
        { poly: clip(half), tone: "accent" },
        { poly: clip(band([-0.2, cut - 0.034], [0.2, cut - 0.01], 0.008)), tone: "accent2" },
      ];
    }
    case "chevron": {
      const tip: Vec2 = [0, c[1] + 0.07];
      return [
        { poly: clip(band([-0.17, c[1] - 0.12], [0.012, tip[1] + 0.006], 0.034)), tone: "accent" },
        { poly: clip(band([0.17, c[1] - 0.12], [-0.012, tip[1] + 0.006], 0.034)), tone: "accent" },
      ];
    }
    case "blade":
      return [
        { poly: clip(band([0, DIMS.headBottom - 0.02], [0, DIMS.length + 0.02], 0.03)), tone: "accent" },
        { poly: clip(band([-0.03, DIMS.headBottom - 0.02], [-0.03, DIMS.length + 0.02], 0.006)), tone: "accent2" },
        { poly: clip(band([0.03, DIMS.headBottom - 0.02], [0.03, DIMS.length + 0.02], 0.006)), tone: "accent2" },
      ];
    case "border": {
      const outer = headOutline(shape, DIMS.frameWidth + 0.0025, 72);
      return [{ poly: outer, tone: "accent", ring: { cx: 0, cy: 0, r0: DIMS.frameWidth + 0.0025, r1: DIMS.frameWidth + 0.0105 } }];
    }
    case "ring":
    default: {
      const sweetY = sweetSpot(shape).y;
      return [{ poly: [], tone: "accent", ring: { cx: 0, cy: sweetY, r0: 0.05, r1: 0.062 } }];
    }
  }
}

function circlePoly(cx: number, cy: number, r: number, n = 64): Vec2[] {
  const out: Vec2[] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    out.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
  }
  return out;
}

export interface DecalWithInner extends Decal {
  /** Optional inner contour (for ring/border bands) cut out of the polygon. */
  inner?: Vec2[];
}

/* ------------------------------------------------------------ blueprint */

export interface SweetSpot {
  x: number;
  y: number;
  rx: number;
  ry: number;
}

/** Illustrative sweet-spot zone. A platform visualization, not a measurement. */
export function sweetSpot(shape: RacketShape, sweetSpotScore = 7): SweetSpot {
  const p = SHAPE_PARAMS[shape];
  const y0 = DIMS.headBottom + DIMS.frameWidth;
  const y1 = DIMS.length - DIMS.frameWidth;
  const k = (0.78 + sweetSpotScore * 0.035) * p.sweetSize;
  return { x: 0, y: y0 + (y1 - y0) * p.sweet, rx: 0.042 * k, ry: 0.05 * k };
}

/** Balance point in mm from the butt, estimated from a balance category when the brand does not publish one. */
export function estimatedBalanceMm(balance: string | null | undefined): number {
  switch (balance) {
    case "low":
      return 254;
    case "medium-low":
      return 260;
    case "medium":
      return 265;
    case "medium-high":
      return 268;
    case "high":
      return 272;
    default:
      return 265;
  }
}

export interface Blueprint {
  shape: RacketShape;
  frameOuter: Vec2[];
  face: Vec2[];
  heart: Vec2[];
  bridge: Vec2[] | null;
  bumper: Vec2[];
  holes: Hole[];
  decals: DecalWithInner[];
  sweetSpot: SweetSpot;
}

export function buildBlueprint(
  shape: RacketShape,
  visual: Pick<RacketVisual, "pattern" | "holes" | "bridge">,
  opts: { samples?: number; sweetSpotScore?: number } = {},
): Blueprint {
  const samples = opts.samples ?? 64;
  const face = headOutline(shape, DIMS.frameWidth, samples);
  let holes = racketHoles(shape, visual.holes);
  const gap = 0.0016;

  const rawDecals = decalShapes(shape, visual.pattern);
  const decals: DecalWithInner[] = [];
  const removed = new Set<number>();

  for (const d of rawDecals) {
    let outer: Vec2[];
    let inner: Vec2[] | undefined;
    if (d.ring && d.poly.length === 0) {
      outer = circlePoly(d.ring.cx, d.ring.cy, d.ring.r1);
      inner = circlePoly(d.ring.cx, d.ring.cy, d.ring.r0).reverse();
    } else if (d.ring) {
      outer = d.poly;
      inner = headOutline(shape, d.ring.r1, 72).reverse();
    } else {
      outer = d.poly;
    }
    if (outer.length < 3) continue;
    const inside: number[] = [];
    holes.forEach((h, i) => {
      const p: Vec2 = [h.x, h.y];
      const inOuter = pointInPolygon(p, outer);
      const dOuter = distanceToPolygonEdge(p, outer);
      const inInner = inner ? pointInPolygon(p, inner) : false;
      const dInner = inner ? distanceToPolygonEdge(p, inner) : Infinity;
      const touches = dOuter < h.r + gap || dInner < h.r + gap;
      if (touches) removed.add(i);
      else if (inOuter && !inInner) inside.push(i);
    });
    decals.push({ polygon: outer, inner, holes: inside, tone: d.tone });
  }

  if (removed.size) {
    const remap = new Map<number, number>();
    const kept: Hole[] = [];
    holes.forEach((h, i) => {
      if (!removed.has(i)) {
        remap.set(i, kept.length);
        kept.push(h);
      }
    });
    holes = kept;
    for (const d of decals) d.holes = d.holes.filter((i) => remap.has(i)).map((i) => remap.get(i)!);
  }

  return {
    shape,
    frameOuter: frameOuter(shape, samples),
    face,
    heart: heartOpening(shape),
    bridge: visual.bridge ? bridgeBar() : null,
    bumper: bumperBand(shape),
    holes,
    decals,
    sweetSpot: sweetSpot(shape, opts.sweetSpotScore),
  };
}

/** Bounding box of a generated placeholder model (used to normalise hotspots in docs/tests). */
export const PLACEHOLDER_BOUNDS = {
  min: [-(DIMS.headHalfWidth + DIMS.bumperOut), 0, -(DIMS.frameThickness / 2 + 0.0015)] as const,
  max: [DIMS.headHalfWidth + DIMS.bumperOut, DIMS.length + DIMS.bumperOut, DIMS.frameThickness / 2 + 0.0015] as const,
};
