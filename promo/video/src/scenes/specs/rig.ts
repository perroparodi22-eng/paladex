// Camera rig helpers for the "specs" scene: smooth multi-key camera paths and
// the transform of a page crop ("slab") that lifts out of a Browser3D page.
import type { Pose } from "../../components/Browser3D";

export type FullPose = Required<Pose>;

/**
 * Monotone cubic (Fritsch–Carlson) interpolation through keys: the value passes
 * every key with continuous velocity (no stop-and-go at intermediate keys) and
 * never overshoots between them. Holds the end values outside the key range.
 */
export const monotone = (xs: number[], ys: number[], x: number): number => {
  const n = xs.length;
  if (n === 1 || x <= xs[0]) return ys[0];
  if (x >= xs[n - 1]) return ys[n - 1];
  const d: number[] = [];
  for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]));
  const m: number[] = new Array(n);
  m[0] = d[0];
  m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / d[i];
    const b = m[i + 1] / d[i];
    const s = a * a + b * b;
    if (s > 9) {
      const t = 3 / Math.sqrt(s);
      m[i] = t * a * d[i];
      m[i + 1] = t * b * d[i];
    }
  }
  let i = 0;
  while (x > xs[i + 1]) i++;
  const h = xs[i + 1] - xs[i];
  const t = (x - xs[i]) / h;
  const t2 = t * t;
  const t3 = t2 * t;
  return (2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h * m[i] + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h * m[i + 1];
};

export type PoseKey = { f: number } & FullPose;

const KEYS: (keyof FullPose)[] = ["x", "y", "z", "rotateX", "rotateY", "rotateZ", "scale"];

/** A pose along monotone-cubic keys (keys sorted by frame). */
export const poseAt = (keys: PoseKey[], frame: number): FullPose => {
  const xs = keys.map((k) => k.f);
  const out = {} as FullPose;
  for (const p of KEYS) out[p] = monotone(xs, keys.map((k) => k[p]), frame);
  return out;
};

export const mixPose = (a: FullPose, b: FullPose, t: number): FullPose => {
  const out = {} as FullPose;
  for (const p of KEYS) out[p] = a[p] + (b[p] - a[p]) * t;
  return out;
};

/**
 * A slab's state: the plane it lives in (`P`, same parametrisation as
 * Browser3D's pose), its centre inside that plane (`cx`, `cy`, px from the
 * plane's centre), how far it floats off the plane (`lz`), a local tilt and a
 * local scale.
 */
export type SlabState = { P: FullPose; cx: number; cy: number; lz: number; lrx: number; lry: number; ls: number };

export const mixSlab = (a: SlabState, b: SlabState, t: number): SlabState => ({
  P: mixPose(a.P, b.P, t),
  cx: a.cx + (b.cx - a.cx) * t,
  cy: a.cy + (b.cy - a.cy) * t,
  lz: a.lz + (b.lz - a.lz) * t,
  lrx: a.lrx + (b.lrx - a.lrx) * t,
  lry: a.lry + (b.lry - a.lry) * t,
  ls: a.ls + (b.ls - a.ls) * t,
});

/**
 * CSS transform for a slab element of size (w·K)×(h·K) placed at the frame
 * centre with transform-origin 0 0. The element is authored K times larger and
 * scaled down by 1/K so Chrome rasterises it sharply when it comes close.
 * The first part matches Browser3D's poseTransform, so at lz = 0 a slab sits
 * exactly on the page it was cropped from.
 */
export const slabTransform = (s: SlabState, w: number, h: number, K: number) => {
  const { P } = s;
  return (
    `translate3d(${P.x}px, ${P.y}px, ${P.z}px) rotateX(${P.rotateX}deg) rotateY(${P.rotateY}deg) rotateZ(${P.rotateZ}deg) scale(${P.scale}) ` +
    `translate3d(${s.cx}px, ${s.cy}px, ${s.lz}px) rotateX(${s.lrx}deg) rotateY(${s.lry}deg) scale(${s.ls}) translate(${-w / 2}px, ${-h / 2}px) scale(${1 / K})`
  );
};
