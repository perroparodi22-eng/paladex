// Camera maths for the "turn" scene.
//
// 1. Smooth multi-key paths (monotone cubic) so camera moves pass through their
//    keys without stop-and-go.
// 2. An "orbit around a page point" rig for <Browser3D>: we say which page pixel
//    the camera looks at, where on screen it should sit, and how the window is
//    turned; the rig works out Browser3D's translate so the window turns around
//    that point (a real orbit) instead of around its own centre.
// 3. The CSS 3D projection of a page point (same maths the browser does), used to
//    find exactly where the captured racket sits on screen at the break-out frame,
//    so the WebGL racket can take its place pixel for pixel.
import type { Pose } from "../../components/Browser3D";
import { CHROME_H } from "../../components/Browser3D";

export const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/**
 * Monotone cubic (Fritsch–Carlson) through keys, flat at both ends: continuous
 * velocity through intermediate keys, no overshoot. Holds outside the range.
 */
export const smooth = (x: number, xs: number[], ys: number[]): number => {
  const n = xs.length;
  if (n === 1 || x <= xs[0]) return ys[0];
  if (x >= xs[n - 1]) return ys[n - 1];
  const d: number[] = [];
  for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]));
  const m: number[] = new Array(n).fill(0);
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
  return hermite(x, xs[i], xs[i + 1], ys[i], ys[i + 1], m[i], m[i + 1]);
};

/** Cubic Hermite between (x0, y0, slope v0) and (x1, y1, slope v1). Clamped outside. */
export const hermite = (x: number, x0: number, x1: number, y0: number, y1: number, v0: number, v1: number) => {
  if (x <= x0) return y0;
  if (x >= x1) return y1;
  const h = x1 - x0;
  const t = (x - x0) / h;
  const t2 = t * t;
  const t3 = t2 * t;
  return (2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * h * v0 + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * h * v1;
};

/** A smooth 0→1→0 bump: rises over `up` frames from `at`, falls over `down`. */
export const bump = (f: number, at: number, up: number, down: number) => {
  const t = f - at;
  if (t <= 0 || t >= up + down) return 0;
  if (t < up) return 0.5 - 0.5 * Math.cos((t / up) * Math.PI);
  return 0.5 + 0.5 * Math.cos(((t - up) / down) * Math.PI);
};

/* ------------------------------------------------------------------ CSS 3D */

const PAGE_W = 1920;
const PAGE_H = 1080;
const ELEM_H = PAGE_H + CHROME_H;
const FRAME_W = 1920;
const FRAME_H = 1080;

type V3 = [number, number, number];
const rad = (d: number) => (d * Math.PI) / 180;

/** CSS rotateX(a) rotateY(b) rotateZ(c) applied to v (rightmost first). y down, z toward viewer. */
const rotate = (rx: number, ry: number, rz: number, [x, y, z]: V3): V3 => {
  const [a, b, c] = [rad(rx), rad(ry), rad(rz)];
  // rotateZ
  let x1 = x * Math.cos(c) - y * Math.sin(c);
  let y1 = x * Math.sin(c) + y * Math.cos(c);
  let z1 = z;
  // rotateY
  const x2 = x1 * Math.cos(b) + z1 * Math.sin(b);
  const z2 = -x1 * Math.sin(b) + z1 * Math.cos(b);
  x1 = x2;
  z1 = z2;
  // rotateX
  const y3 = y1 * Math.cos(a) - z1 * Math.sin(a);
  const z3 = y1 * Math.sin(a) + z1 * Math.cos(a);
  return [x1, y3, z3];
};

/** A page pixel relative to Browser3D's transform origin (the window's centre). */
const local = (px: number, py: number): V3 => [px - PAGE_W / 2, py + CHROME_H - ELEM_H / 2, 0];

/** Orbit rig: look at page point (px, py), put it at (sx, sy, z) (offset from frame centre). */
export type OrbitPose = { px: number; py: number; sx: number; sy: number; z: number; rx: number; ry: number; rz: number; s: number };

export const browserPose = (o: OrbitPose): Required<Pose> => {
  const [lx, ly, lz] = local(o.px, o.py);
  const r = rotate(o.rx, o.ry, o.rz, [lx * o.s, ly * o.s, lz * o.s]);
  return { x: o.sx - r[0], y: o.sy - r[1], z: o.z - r[2], rotateX: o.rx, rotateY: o.ry, rotateZ: o.rz, scale: o.s };
};

/** Screen position (frame px) of page pixel (px, py) for a Browser3D pose inside <Space3D>. */
export const projectPage = (pose: Required<Pose>, px: number, py: number, perspective: number, originX: number, originY: number) => {
  const [lx, ly, lz] = local(px, py);
  const r = rotate(pose.rotateX, pose.rotateY, pose.rotateZ, [lx * pose.scale, ly * pose.scale, lz * pose.scale]);
  const X = FRAME_W / 2 + pose.x + r[0];
  const Y = FRAME_H / 2 + pose.y + r[1];
  const Z = pose.z + r[2];
  const ox = (originX / 100) * FRAME_W;
  const oy = (originY / 100) * FRAME_H;
  const k = perspective / (perspective - Z);
  return { x: ox + (X - ox) * k, y: oy + (Y - oy) * k };
};
