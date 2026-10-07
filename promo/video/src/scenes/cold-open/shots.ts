// The cold open's montage, as data: a list of shots, each a pure function of its
// own local frame that returns the camera, the rackets in frame (real finished
// models from public/models), the light and the motion blur. ColdOpen renders the
// active shot in ONE WebGL stage, so a "cut" is just the next shot taking over.
//
// World: metres, Y up, a racket stands ~0.46 tall along Y with its face toward +Z
// at rotation 0. All shot boundaries come from the voice (see `cuts()`).
import { Easing, interpolate } from "remotion";
import { HERO_SLUG } from "../../components/Racket3D";
import { clamp, drift, mix } from "../../lib/motion";
import { wordAt, type SceneTiming } from "../../timeline";
import type { Vec3 } from "./ColdStage";

export type Inst = { key: string; slug: string; pos: Vec3; rot: Vec3; scale?: number };
export type Cam = { position: Vec3; target: Vec3; fov: number; roll: number };
export type ShotFrame = {
  cam: Cam;
  items: Inst[];
  /** Directional motion blur on the whole WebGL layer (px, x and y). */
  blur: [number, number];
  /** Strip light passing in front of the rackets (glints): world x and strength. */
  sweepX: number;
  sweep: number;
  fog: [number, number];
  /** Where the CSS light pool sits behind the rackets (% of frame) and how strong. */
  pool: { x: number; y: number; a: number };
};
export type Shot = { id: string; from: number; to: number; at: (lt: number, len: number, f: number) => ShotFrame };

// ---------------------------------------------------------------- helpers
const snap = Easing.bezier(0.12, 0.8, 0.2, 1); // fast start, soft settle
const swing = Easing.bezier(0.55, 0, 0.35, 1);
const accel = Easing.bezier(0.6, 0, 0.9, 0.4);
export const ramp = (f: number, a: number, b: number, easing: (t: number) => number = snap) =>
  b <= a ? (f >= b ? 1 : 0) : interpolate(f, [a, b], [0, 1], { ...clamp, easing });
/** d/dt of a 0..1 ramp, in units per frame (for motion blur). */
const speed = (fn: (t: number) => number, t: number) => Math.abs(fn(t + 0.5) - fn(t - 0.5));

/** Camera on a sphere around `target`: azimuth (rad, 0 = on +Z), elevation, distance. */
export const orbit = (target: Vec3, az: number, el: number, d: number, fov = 30, roll = 0): Cam => ({
  position: [target[0] + Math.sin(az) * Math.cos(el) * d, target[1] + Math.sin(el) * d, target[2] + Math.cos(az) * Math.cos(el) * d],
  target,
  fov,
  roll,
});

/** Finished models only (all of public/models), grouped so neighbours differ. The hero is kept for the landing. */
export const MONTAGE = [
  "bullpadel-vertex-05-27",
  "head-radical-pro-2026",
  "babolat-technical-viper-2026",
  "adidas-metalbone-hrd-plus-2026",
  "siux-electra-pro-shadow-red-2026",
  "head-speed-pro-2025",
  "bullpadel-hack-04-2026",
  "wilson-defy-pro-v1",
  "nox-ea10-ventus-attack-12k-xtrem-2026",
  "lok-maxx-hype-gen-2-yanguas-2026",
  "babolat-viper-juan-lebron-3-0-2026",
  "drop-shot-axion-attack-1-5-2025",
  "head-coello-pro-2026",
  "bullpadel-neuron-02-edge-27",
  "adidas-arrow-hit-pro-edt-2026",
  "siux-fenix-pro-2026",
  "bullpadel-xplo-27",
  "head-extreme-motion-2026",
  "wilson-endure-pro-v1-2026",
  "babolat-counter-viper-2-6-2026",
  "bullpadel-wonder-27",
  "adidas-metalbone-team-2026",
  "nox-ml10-ventus-control-3k-2026",
  "head-radical-motion-2026",
  "bullpadel-hack-05-hybrid-27",
  "head-speed-one-x-2025",
  "bullpadel-flow-27",
  "nox-ea10-ventus-hybrid-12k-xtrem-2026",
  "bullpadel-vertex-05-geo-27",
  "adidas-metalbone-3-4",
  "head-speed-motion-2025",
  "bullpadel-icon-27",
] as const;
const pick = (i: number) => MONTAGE[((i % MONTAGE.length) + MONTAGE.length) % MONTAGE.length];

// ---------------------------------------------------------------- timing
export type Cuts = ReturnType<typeof cuts>;
export const cuts = (timing: SceneTiming) => {
  const two = wordAt(timing, "Two", 26);
  const hundred = wordAt(timing, "hundred", 43);
  const euros = wordAt(timing, "euros", 74);
  const maybe = wordAt(timing, "Maybe", 132);
  const more = wordAt(timing, "more", 155);
  const forW = wordAt(timing, "For", 205);
  const one = wordAt(timing, "one", 221);
  const padel = wordAt(timing, "padel", 237);
  const racket = wordAt(timing, "racket", 259);
  const would = wordAt(timing, "Would", 227);
  const buy = wordAt(timing, "buy", 249);
  const it = wordAt(timing, "it", 261);
  const blind = wordAt(timing, "blind", 272);
  return {
    would,
    buy,
    it,
    blind,
    two,
    hundred,
    euros,
    maybe,
    more,
    forW,
    one,
    padel,
    racket,
    // Flash cuts before the slam, and mid-phrase cuts halfway between words.
    flash1: Math.round(two * 0.4),
    flash2: Math.round(two * 0.72),
    mid1: Math.round((euros + maybe) / 2),
    mid2: Math.round((more + forW) / 2),
    end: timing.duration,
  };
};

// ---------------------------------------------------------------- shots
export const buildShots = (T: Cuts, overlap: number): Shot[] => [
  // 1. Macro: the camera slides across a racket face, a strip light glints over it.
  {
    id: "macro-face",
    from: -1,
    to: T.flash1,
    at: (lt, len, f) => {
      const p = (t: number) => ramp(t, -4, len + 6, Easing.bezier(0.3, 0.2, 0.6, 1));
      const t = p(lt);
      return {
        cam: orbit([mix(-0.1, 0.06, t), mix(0.1, 0.13, t), 0], mix(0.42, 0.3, t), 0.06, mix(0.34, 0.3, t), 30, -0.12),
        items: [{ key: "m1", slug: pick(0), pos: [0, 0, 0], rot: [0.08, mix(0.42, 0.22, t), -0.16] }],
        blur: [4 + 120 * speed(p, lt), 0],
        sweepX: mix(-1.6, 1.8, t),
        sweep: 2.6,
        fog: [3, 9],
        pool: { x: 58, y: 40, a: 0.9 },
      };
    },
  },
  // 2. Whip: a racket swings through frame like a forehand; another crosses far behind.
  {
    id: "whip",
    from: T.flash1,
    to: T.flash2,
    at: (lt, len) => {
      const p = (t: number) => ramp(t, -3, len + 3, swing);
      const t = p(lt);
      const q = ramp(lt, -10, len + 14, Easing.linear);
      return {
        cam: orbit([0, 0.01, 0], 0.12, 0.03, 1.25, 30, 0.05),
        items: [
          { key: "w1", slug: pick(1), pos: [mix(-0.4, 0.55, t), 0.05 - 0.08 * Math.sin(Math.PI * t), 0.15], rot: [0.2, mix(0.9, -0.5, t), mix(1.0, -1.1, t)] },
          { key: "w2", slug: pick(16), pos: [mix(0.75, -0.2, q), 0.1, -0.8], rot: [0.1, 0.6 + q, 0.4] },
          { key: "w3", slug: pick(17), pos: [mix(-0.9, -0.1, q), -0.08, -1.5], rot: [0.1, -0.4 - q, -0.3] },
        ],
        blur: [Math.min(40, 260 * speed(p, lt)), 0],
        sweepX: 0.6,
        sweep: 1.4,
        fog: [2, 5],
        pool: { x: 50, y: 44, a: 0.8 },
      };
    },
  },
  // 3. Macro: the frame edge turning toward the lens as the camera pulls back.
  {
    id: "macro-edge",
    from: T.flash2,
    to: T.two,
    at: (lt, len) => {
      const p = (t: number) => ramp(t, -2, len + 4, Easing.bezier(0.2, 0.6, 0.4, 1));
      const t = p(lt);
      return {
        cam: orbit([0.03, mix(0.16, 0.12, t), 0], -0.25, mix(0.2, 0.1, t), mix(0.36, 0.48, t), 30, 0.08),
        items: [{ key: "m2", slug: pick(2), pos: [0, 0, 0], rot: [0.05, mix(1.25, 0.55, t), 0.1] }],
        blur: [0, 3 + 90 * speed(p, lt)],
        sweepX: mix(1.4, -1.2, t),
        sweep: 2.4,
        fog: [3, 9],
        pool: { x: 44, y: 38, a: 0.9 },
      };
    },
  },
  // 4. SLAM ("Two hundred euros"): a row of rackets, the camera snaps along it.
  {
    id: "row",
    from: T.two,
    to: T.euros,
    at: (lt, len, f) => {
      const p = (t: number) => ramp(t, -2, len + 8, Easing.bezier(0.08, 0.75, 0.25, 1));
      const t = p(lt);
      const items: Inst[] = [];
      for (let i = 0; i < 11; i++) {
        const x = -1.9 + i * 0.38;
        items.push({
          key: `r${i}`,
          slug: pick(3 + i),
          pos: [x, 0.02 * Math.sin(i * 1.7), 0],
          rot: [0.06, 0.62 + 0.18 * Math.sin(i * 2.3) + 0.004 * f, 0.05 * Math.cos(i * 1.3)],
        });
      }
      return {
        cam: orbit([mix(0.95, -0.15, t), 0.02, 0], mix(0.75, 0.55, t), mix(0.1, 0.03, t), mix(1.2, 1.45, t), 30, mix(0.06, -0.02, t)),
        items,
        blur: [Math.min(36, 220 * speed(p, lt)), 0],
        sweepX: mix(2.2, -2.2, ramp(lt, 0, len, Easing.linear)),
        sweep: 1.6,
        fog: [1.2, 3.4],
        pool: { x: 50, y: 46, a: 1 },
      };
    },
  },
  // 5. Carousel ("euros"): a ring of rackets wheels past a low camera.
  {
    id: "carousel",
    from: T.euros,
    to: T.mid1,
    at: (lt, len, f) => {
      const p = (t: number) => ramp(t, -2, len + 20, Easing.bezier(0.1, 0.7, 0.3, 1));
      const t = p(lt);
      const n = 14;
      const R = 0.95;
      const spin = 0.7 * t + 0.003 * lt;
      const items: Inst[] = [];
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2 + spin;
        items.push({ key: `c${i}`, slug: pick(14 + i), pos: [Math.sin(a) * R, 0, Math.cos(a) * R], rot: [0, a + 0.35, 0] });
      }
      return {
        cam: { position: [0, mix(-0.2, -0.14, t), mix(2.3, 2.05, t)], target: [0, 0.04, 0.5], fov: 30, roll: mix(-0.07, -0.03, t) },
        items,
        blur: [Math.min(30, 160 * speed(p, lt)), 0],
        sweepX: 0,
        sweep: 1.2,
        fog: [1.6, 3.6],
        pool: { x: 50, y: 52, a: 1 },
      };
    },
  },
  // 6. Macro: up the face of one racket while another drifts by out of focus behind.
  {
    id: "macro-rise",
    from: T.mid1,
    to: T.maybe,
    at: (lt, len) => {
      const p = (t: number) => ramp(t, -3, len + 6, Easing.bezier(0.15, 0.6, 0.35, 1));
      const t = p(lt);
      const q = ramp(lt, 0, len, Easing.linear);
      return {
        cam: orbit([mix(-0.02, 0.03, t), mix(-0.02, 0.15, t), 0], 0.38, mix(-0.12, 0.05, t), 0.6, 30, 0.1),
        items: [
          { key: "m3", slug: "siux-electra-pro-shadow-red-2026", pos: [0, 0, 0], rot: [0.04, 0.12, 0.08] },
          { key: "m3b", slug: pick(21), pos: [mix(-0.55, -0.35, q), 0.08, -0.9], rot: [0.1, 0.9 + q * 0.4, -0.2] },
        ],
        blur: [0, Math.min(26, 120 * speed(p, lt))],
        sweepX: mix(-1.8, 1.6, t),
        sweep: 2.6,
        fog: [1.0, 2.6],
        pool: { x: 62, y: 36, a: 0.9 },
      };
    },
  },
  // 7. Wall ("Maybe"): a whole wall of different rackets, the camera trucks across it.
  {
    id: "wall",
    from: T.maybe,
    to: T.more,
    at: (lt, len, f) => {
      const p = (t: number) => ramp(t, -2, len + 10, Easing.bezier(0.1, 0.7, 0.3, 1));
      const t = p(lt);
      const items: Inst[] = [];
      const cols = 6;
      for (let r = 0; r < 4; r++) {
        for (let c = 0; c < cols; c++) {
          const i = r * cols + c;
          items.push({
            key: `g${i}`,
            slug: pick(i * 5 + 1),
            pos: [(c - (cols - 1) / 2) * 0.34, (1.5 - r) * 0.52, 0],
            rot: [0, 0.2 * Math.sin(i * 1.9 + lt * 0.05), 0.04 * Math.cos(i * 2.7)],
          });
        }
      }
      return {
        cam: orbit([mix(-0.55, 0.15, t), mix(0.35, 0.05, t), 0], mix(-0.62, -0.45, t), mix(0.1, 0.02, t), mix(1.55, 1.7, t), 30, mix(0.03, 0.01, t)),
        items,
        blur: [Math.min(30, 180 * speed(p, lt)), Math.min(16, 90 * speed(p, lt))],
        sweepX: mix(-2, 2, ramp(lt, 0, len, Easing.linear)),
        sweep: 1.4,
        fog: [1.1, 3.0],
        pool: { x: 46, y: 44, a: 1 },
      };
    },
  },
  // 8. Wave ("more"): a line of rackets flips over one after another.
  {
    id: "wave",
    from: T.more,
    to: T.mid2,
    at: (lt, len, f) => {
      const p = (t: number) => ramp(t, -2, len + 8, Easing.bezier(0.1, 0.7, 0.3, 1));
      const t = p(lt);
      const items: Inst[] = [];
      for (let i = 0; i < 12; i++) {
        const flip = ramp(lt, i * 1.6 - 2, i * 1.6 + 10, Easing.bezier(0.3, 0, 0.2, 1));
        items.push({ key: `v${i}`, slug: pick(i * 3 + 7), pos: [(i - 5.5) * 0.3, 0, 0], rot: [0.05, 0.5 + Math.PI * flip, 0] });
      }
      return {
        cam: orbit([mix(-0.3, 0.2, t), 0.03, 0], mix(-0.42, -0.3, t), mix(0.12, 0.05, t), mix(1.15, 1.0, t), 30, -0.03),
        items,
        blur: [Math.min(16, 100 * speed(p, lt)), 0],
        sweepX: mix(-1.6, 1.6, ramp(lt, 0, len, Easing.linear)),
        sweep: 2,
        fog: [0.9, 2.6],
        pool: { x: 50, y: 46, a: 1 },
      };
    },
  },
  // 9. Corridor: the camera flies forward between two lines of rackets.
  {
    id: "corridor",
    from: T.mid2,
    to: T.forW,
    at: (lt, len, f) => {
      const p = (t: number) => ramp(t, -6, len + 2, Easing.bezier(0.3, 0.1, 0.8, 0.7));
      const t = p(lt);
      const items: Inst[] = [];
      for (let j = 0; j < 9; j++) {
        for (const s of [-1, 1]) {
          items.push({
            key: `t${j}${s}`,
            slug: pick(j * 2 + (s > 0 ? 9 : 22)),
            pos: [s * 0.36, s * 0.04 * Math.sin(j), 0.4 - j * 0.5],
            rot: [0, -s * 0.85 + 0.002 * lt, s * 0.04],
          });
        }
      }
      const z = mix(1.6, -0.9, t);
      return {
        cam: { position: [0.02, 0.0, z], target: [0, 0.0, z - 2], fov: 34, roll: mix(0, 0.12, t) },
        items,
        blur: [Math.min(20, 90 * speed(p, lt)), 0],
        sweepX: 0,
        sweep: 0,
        fog: [0.6, 3.2],
        pool: { x: 50, y: 45, a: 1.1 },
      };
    },
  },
  // 10. The hero ("For one padel racket"): it spins in from deep in the dark and lands.
  {
    id: "hero",
    from: T.forW,
    to: T.end + overlap + 1,
    at: (lt, len, f) => {
      const landAt = T.racket - T.forW;
      const arrive = (t: number) => ramp(t, 0, landAt, Easing.bezier(0.1, 0.75, 0.25, 1));
      const a = arrive(lt);
      const spinOf = (t: number) => -Math.PI * 4 * (1 - arrive(t));
      const after = lt - landAt;
      const settle = ramp(after, 0, 50, Easing.bezier(0.2, 0, 0.2, 1));
      const items: Inst[] = [
        {
          key: "hero",
          slug: HERO_SLUG,
          pos: [mix(0.25, 0, a), mix(-0.12, 0, a) + drift("co-hy", f, 0.004, 0.2), mix(-2.6, 0, a)],
          rot: [mix(0.4, 0.06, a) + drift("co-hp", f, 0.02, 0.12), 0.32 + spinOf(lt) + 0.0042 * Math.max(0, after), mix(-0.6, -0.05, a)],
        },
      ];
      // A dim constellation of other rackets far behind, turning in the fog.
      for (let i = 0; i < 8; i++) {
        const ang = (i / 8) * Math.PI * 2 + 0.3;
        const rr = 1.25 + 0.2 * (i % 2);
        items.push({
          key: `h${i}`,
          slug: pick(i * 4 + 2),
          pos: [Math.sin(ang) * rr, Math.cos(ang) * rr * 0.34, -1.3 - 0.35 * (i % 3) + mix(0.8, 0, a)],
          rot: [0.05, ang + 0.01 * lt, 0.1 * Math.sin(ang)],
        });
      }
      // After the landing the camera keeps pushing in and swinging round, so the hero never hangs still.
      const push = ramp(after, 0, len - landAt, Easing.bezier(0.3, 0.1, 0.6, 1));
      const d = mix(1.25, 0.98, ramp(lt, 0, landAt + 60, Easing.bezier(0.2, 0, 0.3, 1))) - 0.28 * push;
      const sp = Math.abs(spinOf(lt + 0.5) - spinOf(lt - 0.5));
      return {
        cam: orbit([0, -0.01, 0], 0.08 + drift("co-az", f, 0.02, 0.08) - 0.06 * settle + 0.2 * push, 0.02 + drift("co-el", f, 0.01, 0.08), d, 30, drift("co-roll", f, 0.01, 0.07)),
        items,
        blur: [Math.min(28, sp * 55), 0],
        sweepX: mix(-2.4, 2.4, ramp(after, -6, 40, Easing.bezier(0.4, 0, 0.3, 1))),
        sweep: after > -6 && after < 40 ? 3 : 0,
        fog: [1.6, 4.6],
        pool: { x: 50, y: 42, a: 1.2 },
      };
    },
  },
];

export const shotAt = (shots: Shot[], f: number) => shots.find((s) => f >= s.from && f < s.to) ?? shots[shots.length - 1];
