// Scene 2, "problem": "And you're choosing it from one flat photo... and a spec sheet nobody explains."
//
// One shared 3D world for CSS and WebGL. The CSS perspective is set to the WebGL
// camera's distance in px (fov 30, z 1.4), so a point placed at the same world px
// coordinates lands on the same screen pixel in both renderers. That lets the real
// hero racket (WebGL) sit exactly inside a CSS "product listing" card while both
// are carried by one camera rig, and lets spec chips (CSS) float in front of and
// behind it with real parallax.
//
// Beats (scene-local frames, derived from the voice's word timings):
//   0          macro: the camera slides across the hero's face (gold glints)
//   choosing   cut: the hero turns between two other rackets (the choice)
//   from       cut: push in on the hero alone; a punch on "one"
//   flat       it is pressed paper-flat, turns front-on, the light goes dull and
//              a dull grey listing card forms around it
//   photo      shutter blink, then the card multiplies into a cold grid of identical
//              flat listings as the camera pulls back
//   and        the grid recedes, a lateral track starts; spec chips burst from depth
//              in waves on "spec", "sheet", "nobody", "explains" (depth of field)
//   end − ~50  everything is pulled into one point (swirl, accelerating) that
//              flares as the scene hands over to the reveal's impact.
import { useThree } from "@react-three/fiber";
import React, { useLayoutEffect, useMemo } from "react";
import { AbsoluteFill, Easing, interpolate, random, useCurrentFrame, useVideoConfig } from "remotion";
import type * as THREE from "three";
import { Space3D } from "../components/Browser3D";
import { HERO_SLUG, RacketModel, RacketStage } from "../components/Racket3D";
import { Sfx } from "../components/Sfx";
import { clamp, drift, easeInOut, easeOut, enterExit, mix } from "../lib/motion";
import { C, FONT, display } from "../theme";
import { wordAt, type SceneTiming } from "../timeline";
import type { SceneProps } from "./types";

// ---------------------------------------------------------------------------
// Shared projection: CSS px world <-> three units.
// ---------------------------------------------------------------------------
const FOV = 30;
const CAM_D = 1.4;
/** px per three unit on the z = 0 plane (1080 px frame height). */
const K = 540 / (CAM_D * Math.tan(((FOV / 2) * Math.PI) / 180));
/** CSS perspective that reproduces the WebGL camera. */
const PERSP = CAM_D * K;
const DEG = Math.PI / 180;

const SMOOTH = Easing.bezier(0.42, 0, 0.58, 1);
const PULL = Easing.bezier(0.5, 0, 0.86, 0.32); // accelerating suck-in
const EMERGE = Easing.bezier(0.25, 0.55, 0.3, 1); // chips surfacing from depth
const ramp = (f: number, a: number, b: number, easing: (t: number) => number = easeInOut) =>
  interpolate(f, [a, b], [0, 1], { ...clamp, easing });

// ---------------------------------------------------------------------------
// Timing (scene-local frames from the voice).
// ---------------------------------------------------------------------------
type Marks = {
  choosing: number;
  from: number;
  one: number;
  flat: number;
  photo: number;
  and: number;
  spec: number;
  sheet: number;
  nobody: number;
  explains: number;
  col: number;
  end: number;
};

const marks = (timing: SceneTiming): Marks => {
  const end = timing.duration;
  const explains = wordAt(timing, "explains", 267);
  return {
    choosing: wordAt(timing, "choosing", 49),
    from: wordAt(timing, "from", 90),
    one: wordAt(timing, "one", 108),
    flat: wordAt(timing, "flat", 123),
    photo: wordAt(timing, "photo", 141),
    // The second "and" (the first opens the line).
    and: wordAt(timing, "and", 185, 1),
    spec: wordAt(timing, "spec", 209),
    sheet: wordAt(timing, "sheet", 226),
    nobody: wordAt(timing, "nobody", 245),
    explains,
    // The storm peaks on "explains", then the collapse lands on the cut.
    col: Math.max(explains + 14, end - 52),
    end,
  };
};

// ---------------------------------------------------------------------------
// Camera rig: lateral track through depth with a slow push.
// ---------------------------------------------------------------------------
type Cam = { x: number; y: number; z: number };
const camAt = (f: number, T: Marks): Cam => ({
  x: 760 * ramp(f, T.and - 16, T.end + 40, SMOOTH) + drift("pb-cam-x", f, 14, 0.07),
  y: drift("pb-cam-y", f, 10, 0.06) - 24 * ramp(f, T.and, T.end, SMOOTH),
  z:
    -40 +
    60 * ramp(f, T.flat - 20, T.flat + 20, SMOOTH) +
    // The pull-back that reveals the grid of identical listings.
    820 * ramp(f, T.photo + 6, T.photo + 40, Easing.bezier(0.5, 0, 0.15, 1)) -
    180 * ramp(f, T.and - 6, T.col + 10, SMOOTH) +
    170 * ramp(f, T.col - 10, T.end + 30, Easing.bezier(0.5, 0, 0.8, 0.6)),
});
const camCss = (c: Cam) => `translate3d(${-c.x}px, ${-c.y}px, ${-c.z}px)`;

/** The point everything collapses into (world px): screen centre at the cut. */
const collapsePoint = (T: Marks) => {
  const c = camAt(T.end, T);
  return { x: c.x, y: c.y - 30, z: -520 };
};

/** Swirl a world point toward P by progress c (0..1). */
const pull = (p: { x: number; y: number; z: number }, P: { x: number; y: number; z: number }, c: number, swirl: number) => {
  const th = c * swirl;
  const ox = p.x - P.x;
  const oy = p.y - P.y;
  const k = 1 - c;
  return {
    x: P.x + (ox * Math.cos(th) - oy * Math.sin(th)) * k,
    y: P.y + (ox * Math.sin(th) + oy * Math.cos(th)) * k,
    z: P.z + (p.z - P.z) * k,
    th,
  };
};

// ---------------------------------------------------------------------------
// The listing card and the racket inside it (card-local px).
// ---------------------------------------------------------------------------
const CARD_W = 520;
const CARD_H = 760;
const CARD_Y = -40;
const PANEL = { x: 20, y: 20, w: CARD_W - 40, h: 540 };
const PHOTO_CY = -CARD_H / 2 + PANEL.y + PANEL.h / 2; // racket centre in the photo
const RK_FLAT = 470 / (0.46 * K); // racket ~470 px tall in the photo
const RK_HERO = 0.84;

type CardPose = { x: number; y: number; z: number; ry: number; rx: number; rz: number; s: number; opacity: number; c: number };

const cardAt = (f: number, T: Marks, cam: Cam, P: { x: number; y: number; z: number }): CardPose => {
  const appear = ramp(f, T.flat + 4, T.flat + 28, Easing.bezier(0.3, 0, 0.2, 1));
  const recede = ramp(f, T.and - 16, T.nobody + 30, SMOOTH);
  const base = {
    x: cam.x * 0.85 + drift("pb-card-x", f, 8, 0.07),
    y: CARD_Y + drift("pb-card-y", f, 7, 0.09),
    z: -280 * recede,
  };
  const c = ramp(f, T.col + 4, T.end - 2, PULL);
  const p = pull(base, P, c, 0.9);
  return {
    x: p.x,
    y: p.y,
    z: p.z,
    ry: -10 * ramp(f, T.flat + 8, T.photo + 30, SMOOTH) + 22 * ramp(f, T.and - 10, T.end, SMOOTH) + drift("pb-card-ry", f, 1.6, 0.1),
    rx: 4 * ramp(f, T.flat, T.photo + 30, SMOOTH) + 10 * ramp(f, T.and, T.end, SMOOTH) + drift("pb-card-rx", f, 1.4, 0.08),
    rz: drift("pb-card-rz", f, 0.8, 0.06) + p.th / DEG,
    s: mix(1.07, 1, appear) * (1 - 0.9 * c),
    opacity: appear * (1 - interpolate(c, [0.72, 1], [0, 1], clamp)),
    c,
  };
};

type V3 = [number, number, number];
const PRESS = Easing.bezier(0.65, 0, 0.2, 1); // a firm press with a soft landing
const SWING = Easing.bezier(0.45, 0, 0.12, 1); // the pressed sheet swings round to the lens
/**
 * The hero racket: turning in the studio, then on "flat" it is pressed paper-thin
 * WHILE still at a three-quarter angle (so the thickness visibly collapses), and only
 * then swings front-on into the listing photo.
 */
/** Before "flat": three quick shots of the hero (macro, the choice, the push-in). */
const heroPre = (f: number, T: Marks) => {
  if (f < T.choosing) {
    const t = ramp(f, -20, T.choosing + 6, Easing.bezier(0.25, 0.3, 0.5, 1));
    return { x: mix(-185, -120, t), y: 150, z: 1430, rx: 0.06, ry: mix(-0.62, -0.3, t), rz: mix(-0.2, -0.12, t) };
  }
  if (f < T.from) {
    const t = ramp(f, T.choosing - 2, T.from + 10, Easing.bezier(0.15, 0.7, 0.3, 1));
    return { x: 0, y: 10, z: mix(260, 380, t), rx: 0.12, ry: mix(-1.5, -0.75, t), rz: -0.05 };
  }
  const push = ramp(f, T.from - 2, T.from + 22, Easing.bezier(0.1, 0.8, 0.25, 1));
  const punch = ramp(f, T.one - 2, T.one + 12, Easing.bezier(0.1, 0.8, 0.25, 1));
  return { x: 12, y: 6, z: 260 + 130 * push + 80 * punch, rx: 0.14, ry: -1.28 + f * 0.0058, rz: -0.12 };
};

/** The two other rackets the hero is weighed against on "choosing" (world px). */
const RIVALS = [
  { slug: "head-radical-pro-2026", x: -600, y: 10, z: -420, ry: 0.75 },
  { slug: "bullpadel-vertex-05-27", x: 610, y: 0, z: -460, ry: -0.7 },
] as const;
/** Dim rackets deep behind the hero before it goes flat (continuity with the cold open). */
const FAR = [
  { slug: "babolat-technical-viper-2026", x: -1700, y: -450, z: -2600 },
  { slug: "adidas-metalbone-hrd-plus-2026", x: 1800, y: -380, z: -2900 },
  { slug: "wilson-defy-pro-v1", x: -1300, y: 560, z: -2400 },
  { slug: "siux-electra-pro-shadow-red-2026", x: 1450, y: 520, z: -2500 },
  { slug: "head-speed-pro-2025", x: -350, y: -700, z: -3200 },
  { slug: "bullpadel-hack-04-2026", x: 520, y: 700, z: -3000 },
] as const;

const racketAt = (f: number, T: Marks): { pos: V3; rot: V3; scale: V3 } => {
  const sq = ramp(f, T.flat - 5, T.flat + 7, PRESS);
  const b = ramp(f, T.flat + 1, T.flat + 27, SWING);
  const hp = heroPre(f, T);
  const hero = { x: hp.x, y: hp.y, z: hp.z };
  const flat = { x: 0, y: PHOTO_CY, z: 2 };
  const ry = hp.ry + drift("pb-rk-ry", f, 0.05, 0.1);
  const rx = hp.rx + drift("pb-rk-rx", f, 0.04, 0.1);
  const rz = hp.rz + drift("pb-rk-rz", f, 0.03, 0.08);
  // Pressed things spread a little; the spread eases out as it lands in the photo.
  const spread = 1 + 0.035 * sq * (1 - b);
  const s = mix(RK_HERO, RK_FLAT, b) * spread;
  return {
    pos: [mix(hero.x, flat.x, b) / K, -mix(hero.y, flat.y, b) / K, mix(hero.z, flat.z, b) / K],
    rot: [rx * (1 - b), ry * (1 - b), rz * (1 - b)],
    scale: [s, s, s * mix(1, 0.02, sq)],
  };
};

/** Dims the studio rig toward flat, catalogue light (frame-driven). */
const FlatLight: React.FC<{ dir: number; env: number }> = ({ dir, env }) => {
  const scene = useThree((s) => s.scene);
  useLayoutEffect(() => {
    scene.environmentIntensity = env;
    scene.traverse((o) => {
      const l = o as THREE.DirectionalLight & THREE.HemisphereLight;
      if (!l.isDirectionalLight && !l.isHemisphereLight) return;
      if (l.userData.pbBase === undefined) l.userData.pbBase = l.intensity;
      l.intensity = l.userData.pbBase * dir;
    });
  }, [scene, dir, env]);
  return null;
};

// ---------------------------------------------------------------------------
// Copy: the jargon a buyer is left alone with.
// ---------------------------------------------------------------------------
const TITLE = "Padel racket";
const PILLS: readonly (readonly [string, string?])[] = [
  ["Balance", "265 mm"],
  ["EVA Soft 30"],
  ["12K Carbon"],
  ["Hardness", "7/10"],
  ["Profile", "38 mm"],
  ["Swingweight", "162"],
  ["Fiberglass 3K"],
  ["Weight", "360–375 g"],
  ["HR3 Core"],
  ["Tubular Bi-Carbon"],
  ["3D Rough Surface"],
  ["High balance"],
  ["Graphene"],
  ["Polyethylene foam"],
  ["18K Carbon"],
  ["Shore 50"],
  ["Rigidity", "Medium"],
  ["Sweet spot", "High"],
  ["Kevlar"],
  ["Thickness", "38 mm"],
  ["Anti-vibration"],
  ["Hole pattern", "54"],
  ["Core", "Black EVA"],
  ["Inertia", "High"],
  ["Face", "Carbon 24K"],
  ["Frame", "Tubular"],
  ["Rough", "Sand finish"],
  ["Grip", "Ø 24 mm"],
  ["Density", "High"],
  ["Bridge", "Open"],
  ["Power", "8.5"],
  ["Control", "7.5"],
];
const QUESTIONS = ["Teardrop?", "Diamond?", "Round?", "Soft or hard?", "Power or control?", "Head-heavy?", "Which core?"];
const ROWS: readonly { head: string; rows: readonly (readonly [string, string])[] }[] = [
  { head: "SPECIFICATIONS", rows: [["Shape", "Hybrid"], ["Core", "Black EVA"], ["Balance", "Medium-high"], ["Weight", "355–370 g"]] },
  { head: "TECHNICAL DATA", rows: [["Surface", "3D sand"], ["Frame", "100% carbon"], ["Swingweight", "158–166"], ["Thickness", "38 mm"]] },
  { head: "MATERIALS", rows: [["Face", "3K fiberglass"], ["Core", "EVA Pro 30"], ["Hardness", "7/10"]] },
];

// ---------------------------------------------------------------------------
// Spec chips: where each one appears on screen (px from centre) at its entry,
// at which depth, in which wave (0: "and", 1: "spec", 2: "sheet", 3: "nobody").
// ---------------------------------------------------------------------------
type Kind = "p" | "q" | "r";
type ChipSpec = { k: Kind; i: number; w: 0 | 1 | 2 | 3 | 4; sx: number; sy: number; z: number };
const SPECS: ChipSpec[] = [
  // wave 0: far, faint, the cloud starts to form
  { k: "p", i: 12, w: 0, sx: 560, sy: -380, z: -1700 },
  { k: "p", i: 15, w: 0, sx: -640, sy: 300, z: -1500 },
  { k: "p", i: 13, w: 0, sx: -380, sy: -440, z: -1900 },
  { k: "p", i: 18, w: 0, sx: 820, sy: 300, z: -1800 },
  // wave 1, "spec": readable mid-depth chips
  { k: "p", i: 0, w: 1, sx: 560, sy: -300, z: -380 },
  { k: "p", i: 1, w: 1, sx: -560, sy: -150, z: -420 },
  { k: "p", i: 2, w: 1, sx: 500, sy: 200, z: -340 },
  { k: "p", i: 3, w: 1, sx: -540, sy: 250, z: -480 },
  { k: "p", i: 4, w: 1, sx: 900, sy: -250, z: -860 },
  { k: "p", i: 14, w: 1, sx: -860, sy: -360, z: -1400 },
  { k: "p", i: 20, w: 1, sx: 300, sy: -470, z: -1600 },
  // wave 2, "sheet": spec-sheet fragments, nearer layers
  { k: "r", i: 0, w: 2, sx: 860, sy: 90, z: -380 },
  { k: "r", i: 1, w: 2, sx: -720, sy: 40, z: -820 },
  { k: "p", i: 5, w: 2, sx: 420, sy: 310, z: 120 },
  { k: "p", i: 6, w: 2, sx: -420, sy: -390, z: 200 },
  { k: "p", i: 7, w: 2, sx: 1000, sy: -330, z: -300 },
  { k: "p", i: 8, w: 2, sx: -920, sy: -220, z: -1100 },
  { k: "p", i: 9, w: 2, sx: 1080, sy: 320, z: -1200 },
  { k: "p", i: 10, w: 2, sx: 880, sy: 230, z: 700 },
  // wave 3, "nobody": the questions, and too much of everything
  { k: "q", i: 0, w: 3, sx: 520, sy: -110, z: 380 },
  { k: "q", i: 1, w: 3, sx: -500, sy: 130, z: 300 },
  { k: "q", i: 2, w: 3, sx: 180, sy: -430, z: 520 },
  { k: "q", i: 3, w: 3, sx: 760, sy: 250, z: -150 },
  { k: "q", i: 4, w: 3, sx: -720, sy: -290, z: -400 },
  { k: "r", i: 2, w: 3, sx: 1100, sy: -30, z: -700 },
  { k: "p", i: 11, w: 3, sx: -980, sy: 320, z: 100 },
  { k: "p", i: 16, w: 3, sx: 620, sy: 330, z: -600 },
  { k: "p", i: 17, w: 3, sx: -250, sy: -450, z: -900 },
  { k: "p", i: 19, w: 3, sx: 1150, sy: -390, z: 400 },
  { k: "p", i: 21, w: 3, sx: 1020, sy: -150, z: 900 },
  // wave 4, "explains": the storm peaks, chips right in front of the lens
  { k: "p", i: 22, w: 4, sx: -300, sy: 60, z: 950 },
  { k: "p", i: 23, w: 4, sx: 340, sy: -260, z: 1050 },
  { k: "q", i: 5, w: 4, sx: -60, sy: -280, z: 700 },
  { k: "q", i: 6, w: 4, sx: 120, sy: 300, z: 800 },
  { k: "p", i: 24, w: 4, sx: -820, sy: -40, z: 600 },
  { k: "p", i: 25, w: 4, sx: 760, sy: 40, z: 750 },
  { k: "p", i: 26, w: 4, sx: -560, sy: 360, z: 1100 },
  { k: "p", i: 27, w: 4, sx: 460, sy: 420, z: 300 },
  { k: "p", i: 28, w: 4, sx: -700, sy: -400, z: 450 },
  { k: "p", i: 29, w: 4, sx: 900, sy: -420, z: 200 },
  { k: "p", i: 30, w: 4, sx: 40, sy: -470, z: -300 },
  { k: "p", i: 31, w: 4, sx: -1000, sy: 200, z: -200 },
];

type Chip = ChipSpec & { id: number; appear: number; x: number; y: number; swirl: number; ry0: number; rz0: number; j1: number; j2: number };

const waveAt = (T: Marks, w: number) => [T.and - 6, T.spec - 6, T.sheet - 6, T.nobody - 6, T.explains - 6][w];

/** A second, mirrored layer for every wave from "spec" on, with different copy: twice the storm. */
const ALL_SPECS: ChipSpec[] = [
  ...SPECS,
  ...SPECS.filter((c) => c.w >= 1 && c.k === "p").map((c, n) => ({ ...c, i: (c.i + 11 + n) % PILLS.length, sx: -c.sx * 0.82 + 60, sy: -c.sy * 0.9 - 30, z: c.z - 260 })),
];

const buildChips = (T: Marks): Chip[] =>
  ALL_SPECS.map((c, id) => {
    const j1 = random(`pb-j1-${id}`);
    const j2 = random(`pb-j2-${id}`);
    const appear = waveAt(T, c.w) + Math.round(j1 * 8);
    const cm = camAt(appear, T);
    const s = PERSP / (PERSP - (c.z - cm.z));
    return {
      ...c,
      id,
      j1,
      j2,
      appear,
      x: cm.x + c.sx / s,
      y: cm.y + c.sy / s,
      // Depth is relative to the camera at entry (the camera has pulled back for the grid).
      z: c.z + cm.z,
      swirl: 0.75 + random(`pb-sw-${id}`) * 0.6,
      ry0: -c.sx * 0.011 + (random(`pb-ry-${id}`) - 0.5) * 10,
      rz0: (random(`pb-rz-${id}`) - 0.5) * 6,
    };
  });

/** Sub-frame offsets (frames back) and weights for the collapse trails. */
const GHOSTS = [
  { d: 0.6, o: 0.45 },
  { d: 1.2, o: 0.26 },
  { d: 1.8, o: 0.13 },
];

type ChipState = { x: number; y: number; z: number; ry: number; rz: number; s: number; opacity: number; blur: number; c: number };

const chipAt = (ch: Chip, f: number, T: Marks, P: { x: number; y: number; z: number }, focusZ: number): ChipState | null => {
  const e = ramp(f, ch.appear, ch.appear + 22, EMERGE);
  if (e <= 0) return null;
  const base = {
    x: ch.x + drift(`pb-cx-${ch.id}`, f, 10, 0.1),
    y: ch.y + drift(`pb-cy-${ch.id}`, f, 12, 0.13),
    z: ch.z - 420 * (1 - e),
  };
  const cs = T.col + ch.j2 * 10;
  const ce = T.end - 2 - ch.j1 * 6;
  const c = ramp(f, cs, ce, PULL);
  const p = pull(base, P, c, ch.swirl);
  const opacity = e * (1 - interpolate(c, [0.7, 1], [0, 1], clamp));
  if (opacity <= 0.002) return null;
  return {
    x: p.x,
    y: p.y,
    z: p.z,
    ry: ch.ry0 + drift(`pb-cr-${ch.id}`, f, 6, 0.1),
    rz: ch.rz0 + drift(`pb-cz-${ch.id}`, f, 2, 0.08) + p.th / DEG,
    s: 1 - 0.85 * c,
    opacity,
    blur: Math.min(16, Math.abs(p.z - focusZ) * 0.0065) + (1 - e) * 10 + c * 5,
    c,
  };
};

// ---------------------------------------------------------------------------
// Visual pieces.
// ---------------------------------------------------------------------------
const centred: React.CSSProperties = { position: "absolute", left: 0, top: 0, transform: "translate(-50%, -50%)", whiteSpace: "nowrap" };
const glass = "inset 0 0 0 1.5px rgba(255,255,255,0.08), 0 24px 48px rgba(0,0,0,0.35)";

const Pill: React.FC<{ l: string; v?: string }> = ({ l, v }) => (
  <div
    style={{
      ...centred,
      display: "flex",
      alignItems: "center",
      gap: 16,
      height: 84,
      padding: "0 38px",
      borderRadius: 999,
      background: "rgba(26,29,34,0.96)",
      boxShadow: glass,
      fontFamily: FONT,
      fontSize: 38,
      fontWeight: 500,
      color: C.ink2,
      letterSpacing: "-0.005em",
    }}
  >
    <span>{l}</span>
    {v && (
      <>
        <span style={{ width: 5, height: 5, borderRadius: 3, background: C.mist }} />
        <span style={{ color: C.ink, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{v}</span>
      </>
    )}
  </div>
);

const Question: React.FC<{ q: string }> = ({ q }) => (
  <div
    style={{
      ...centred,
      ...display,
      display: "flex",
      alignItems: "center",
      height: 92,
      padding: "0 40px",
      borderRadius: 999,
      border: "2px dashed rgba(169,174,184,0.6)",
      background: "rgba(10,11,13,0.6)",
      fontSize: 54,
      color: C.ink2,
    }}
  >
    {q}
  </div>
);

const Rows: React.FC<{ head: string; rows: readonly (readonly [string, string])[] }> = ({ head, rows }) => (
  <div
    style={{
      ...centred,
      width: 540,
      padding: "22px 30px 8px",
      borderRadius: 18,
      background: "rgba(19,21,25,0.94)",
      boxShadow: glass,
      fontFamily: FONT,
    }}
  >
    <div style={{ fontSize: 17, letterSpacing: "0.16em", color: C.ink3, fontWeight: 600, opacity: 0.8, marginBottom: 8 }}>{head}</div>
    {rows.map(([l, v], i) => (
      <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "13px 0", borderTop: "1px solid rgba(255,255,255,0.07)", fontSize: 28 }}>
        <span style={{ color: C.ink3, fontWeight: 500 }}>{l}</span>
        <span style={{ color: C.ink2, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{v}</span>
      </div>
    ))}
  </div>
);

const ChipBody: React.FC<{ ch: Chip }> = ({ ch }) => {
  if (ch.k === "q") return <Question q={QUESTIONS[ch.i]} />;
  if (ch.k === "r") return <Rows head={ROWS[ch.i].head} rows={ROWS[ch.i].rows} />;
  const [l, v] = PILLS[ch.i];
  return <Pill l={l} v={v} />;
};

const ChipNode: React.FC<{ ch: Chip; st: ChipState }> = ({ ch, st }) => (
  <div
    style={{
      position: "absolute",
      left: 0,
      top: 0,
      transform: `translate3d(${st.x}px, ${st.y}px, ${st.z}px) rotateY(${st.ry}deg) rotateZ(${st.rz}deg) scale(${st.s})`,
      opacity: st.opacity,
      filter: st.blur > 0.25 ? `blur(${st.blur.toFixed(2)}px)` : undefined,
    }}
  >
    <ChipBody ch={ch} />
  </div>
);

/** The grid of identical listings the card multiplies into on "photo" (card-local px offsets). */
const GX = CARD_W + 48;
const GY = CARD_H + 48;
type Cell = { ox: number; oy: number; delay: number };
const GRID: Cell[] = [];
for (let r = -1; r <= 1; r++) {
  for (let c = -3; c <= 4; c++) {
    if (r === 0 && c === 0) continue;
    GRID.push({ ox: c * GX, oy: r * GY, delay: (Math.abs(c) + Math.abs(r)) * 2.5 + (c < 0 ? 1 : 0) });
  }
}
/** 0..1 pop-in of a grid cell. */
const cellIn = (f: number, T: Marks, cell: Cell) => ramp(f, T.photo + 10 + cell.delay, T.photo + 18 + cell.delay, easeOut);

/** One dull "product listing" face (card-local, centred on ox/oy). */
const CardFace: React.FC<{ ox: number; oy: number; title: string; counter: number; flash: number; opacity?: number; scale?: number }> = ({
  ox,
  oy,
  title,
  counter,
  flash,
  opacity = 1,
  scale = 1,
}) => (
  <div
    style={{
      position: "absolute",
      left: ox - CARD_W / 2,
      top: oy - CARD_H / 2,
      width: CARD_W,
      height: CARD_H,
      borderRadius: 22,
      background: "#26292e",
      boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.06), 0 50px 110px rgba(0,0,0,0.6)",
      opacity,
      scale,
      fontFamily: "Arial, Helvetica, sans-serif",
    }}
  >
    <div style={{ position: "absolute", left: PANEL.x, top: PANEL.y, width: PANEL.w, height: PANEL.h, borderRadius: 12, background: "#9a9da3", overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0, background: "#ffffff", opacity: flash * 0.55 }} />
      <div
        style={{
          position: "absolute",
          right: 16,
          top: 16,
          padding: "5px 11px",
          borderRadius: 6,
          background: "rgba(40,42,46,0.55)",
          color: "#e6e7e9",
          fontSize: 17,
          opacity: counter,
        }}
      >
        1 / 1
      </div>
      <div style={{ position: "absolute", left: "50%", bottom: 16, width: 8, height: 8, marginLeft: -4, borderRadius: 4, background: "rgba(40,42,46,0.6)", opacity: counter }} />
    </div>
    <div style={{ position: "absolute", left: 26, top: PANEL.y + PANEL.h + 22, fontSize: 25, color: "#b8bbc1", letterSpacing: "0.005em" }}>{title}</div>
    <div style={{ position: "absolute", left: 26, top: PANEL.y + PANEL.h + 66, width: 290, height: 14, borderRadius: 7, background: "#3e4248" }} />
    <div style={{ position: "absolute", left: 26, top: PANEL.y + PANEL.h + 94, width: 120, height: 22, borderRadius: 6, background: "#474b52" }} />
    <div style={{ position: "absolute", left: 20, right: 20, bottom: 20, height: 48, borderRadius: 10, background: "#33363c" }} />
  </div>
);

/** The generic, dull "product listing" the racket gets pressed into, and its identical copies. */
const ListingCard: React.FC<{ pose: CardPose; title: string; counter: number; flash: number; frame: number; T: Marks; dim?: number }> = ({ pose, title, counter, flash, frame, T, dim = 1 }) => (
  <div
    style={{
      position: "absolute",
      left: 0,
      top: 0,
      width: 0,
      height: 0,
      transform: `translate3d(${pose.x}px, ${pose.y}px, ${pose.z}px) rotateY(${pose.ry}deg) rotateX(${pose.rx}deg) rotateZ(${pose.rz}deg) scale(${pose.s})`,
      opacity: pose.opacity,
      filter: dim < 0.999 ? `brightness(${dim})` : undefined,
    }}
  >
    {GRID.map((cell, i) => {
      const t = cellIn(frame, T, cell);
      return t > 0.001 ? <CardFace key={i} ox={cell.ox} oy={cell.oy} title={title} counter={counter} flash={0} opacity={Math.min(1, t * 2)} scale={mix(0.86, 1, t)} /> : null;
    })}
    <CardFace ox={0} oy={0} title={title} counter={counter} flash={flash} />
  </div>
);

// ---------------------------------------------------------------------------
// Scene.
// ---------------------------------------------------------------------------
export const Problem: React.FC<SceneProps> = ({ timing, timeline }) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const T = useMemo(() => marks(timing), [timing]);
  const chips = useMemo(() => buildChips(T), [T]);
  const P = useMemo(() => collapsePoint(T), [T]);

  const env = enterExit(frame, timing.duration, timeline.overlapFrames);
  const cam = camAt(frame, T);
  const card = cardAt(frame, T, cam, P);
  const rk = racketAt(frame, T);

  // Flat, dull catalogue light, and a shutter blink on "photo" that lands on the
  // freshly formed listing.
  const L = ramp(frame, T.flat + 4, T.flat + 26, easeInOut);
  const flash = interpolate(frame, [T.photo, T.photo + 2], [0, 1], clamp) * interpolate(frame, [T.photo + 2, T.photo + 20], [1, 0], { ...clamp, easing: easeOut });
  const counterAt = Math.max(T.photo, T.flat + 14) + 4;
  const counter = ramp(frame, counterAt, counterAt + 16, easeOut);

  // Chips, plus trailing sub-frame copies while they are sucked in (motion blur).
  type Item = { key: string; ch: Chip; st: ChipState };
  const items: Item[] = [];
  for (const ch of chips) {
    const st = chipAt(ch, frame, T, P, cam.z - 380);
    if (!st) continue;
    const prev = chipAt(ch, frame - 1, T, P, cam.z - 380);
    const speed = Math.min(1, Math.max(0, st.c - (prev?.c ?? st.c)) * 16);
    if (speed > 0.02) {
      for (const g of GHOSTS) {
        const gs = chipAt(ch, frame - g.d, T, P, cam.z - 380);
        if (gs) items.push({ key: `${ch.id}-g${g.d}`, ch, st: { ...gs, opacity: gs.opacity * g.o * speed } });
      }
    }
    items.push({ key: `${ch.id}`, ch, st });
  }
  const back = items.filter((it) => it.st.z <= card.z + 60);
  const front = items.filter((it) => it.st.z > card.z + 60);
  const cardSpeed = Math.min(1, Math.max(0, card.c - cardAt(frame - 1, T, camAt(frame - 1, T), P).c) * 16);
  const cardGhosts =
    cardSpeed > 0.02
      ? GHOSTS.map((g) => {
          const pose = cardAt(frame - g.d, T, camAt(frame - g.d, T), P);
          return { d: g.d, pose: { ...pose, opacity: pose.opacity * g.o * cardSpeed } };
        })
      : [];

  // Tension: the frame closes in from the edges as the cloud thickens.
  const tension = ramp(frame, T.and, T.col + 50, SMOOTH);
  // The point everything collapses into flares just before the cut.
  const glow = interpolate(frame, [T.end - 40, T.end - 2, T.end + 8, T.end + 18], [0, 1, 0.7, 0], { ...clamp, easing: Easing.bezier(0.5, 0, 0.5, 1) });

  // The grid steps back into the dark so the spec storm owns the frame.
  const gridDim = mix(1, 0.24, ramp(frame, T.and - 6, T.spec + 4, SMOOTH));
  const camT = camCss(cam);
  const camGroupPos: V3 = [-cam.x / K, cam.y / K, -cam.z / K];
  const rkOpacity = interpolate(card.c, [0.72, 1], [1, 0], clamp);

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: env.blur > 0.05 ? `blur(${env.blur.toFixed(2)}px)` : undefined }}>
      {/* Behind the racket: the card and the far chips. */}
      <Space3D perspective={PERSP} originX={50} originY={50}>
        <div style={{ position: "absolute", left: "50%", top: "50%", width: 0, height: 0, transformStyle: "preserve-3d", transform: camT }}>
          {back.map(({ key, ch, st }) => (
            <ChipNode key={key} ch={ch} st={st} />
          ))}
          {cardGhosts.map(({ d, pose }) => (
            <ListingCard key={d} pose={pose} title={TITLE} counter={counter} flash={0} frame={frame - d} T={T} dim={gridDim} />
          ))}
          <ListingCard pose={card} title={TITLE} counter={counter} flash={flash} frame={frame} T={T} dim={gridDim} />
        </div>
      </Space3D>

      {/* The real hero racket, in the same world. */}
      <AbsoluteFill
        style={{
          filter: `saturate(${mix(1, 0.2, L)}) contrast(${mix(1, 0.8, L)}) brightness(${(mix(1, 1.1, L) + 0.55 * flash) * gridDim}) blur(${(0.55 * L).toFixed(2)}px)`,
        }}
      >
        <RacketStage width={width} height={height} cameraPosition={[0, 0, CAM_D]} fov={FOV}>
          <FlatLight dir={mix(1, 0.28, L)} env={mix(1, 0.45, L)} />
          <ambientLight intensity={mix(0, 1.7, L)} />
          {frame < T.flat + 8 && <fog attach="fog" args={["#050607", 1.6, 4.6]} />}
          <group position={camGroupPos}>
            {/* The choice ("choosing"): two other rackets either side of the hero. */}
            {frame >= T.choosing &&
              frame < T.from &&
              RIVALS.map((r) => (
                <RacketModel key={r.slug} slug={r.slug} position={[r.x / K, -r.y / K, r.z / K]} rotation={[0.08, r.ry + 0.004 * (frame - T.choosing), 0.03]} />
              ))}
            {/* Dim rackets deep behind until the hero goes flat. */}
            {frame < T.flat + 2 &&
              FAR.map((r, i) => (
                <RacketModel key={r.slug} slug={r.slug} position={[r.x / K, -r.y / K, r.z / K]} rotation={[0.05, 0.6 * Math.sin(i * 2.1) + 0.006 * frame, 0.1 * Math.cos(i)]} />
              ))}
            <group position={[card.x / K, -card.y / K, card.z / K]}>
              <group rotation={[0, card.ry * DEG, 0]}>
                <group rotation={[-card.rx * DEG, 0, 0]}>
                  <group rotation={[0, 0, -card.rz * DEG]}>
                    <group scale={card.s}>
                      <RacketModel slug={HERO_SLUG} position={rk.pos} rotation={rk.rot} scale={rk.scale} opacity={rkOpacity} />
                      {GRID.map((cell, i) => {
                        const t = cellIn(frame, T, cell);
                        if (t <= 0.001) return null;
                        const sc = RK_FLAT * mix(0.86, 1, t);
                        return (
                          <RacketModel
                            key={`g${i}`}
                            slug={HERO_SLUG}
                            position={[cell.ox / K, -(cell.oy + PHOTO_CY * mix(0.86, 1, t)) / K, 2 / K]}
                            scale={[sc, sc, sc * 0.02]}
                            opacity={rkOpacity}
                          />
                        );
                      })}
                    </group>
                  </group>
                </group>
              </group>
            </group>
          </group>
        </RacketStage>
      </AbsoluteFill>

      {/* In front of the racket: near chips and the collapse point. */}
      <Space3D perspective={PERSP} originX={50} originY={50}>
        <div style={{ position: "absolute", left: "50%", top: "50%", width: 0, height: 0, transformStyle: "preserve-3d", transform: camT }}>
          {front.map(({ key, ch, st }) => (
            <ChipNode key={key} ch={ch} st={st} />
          ))}
          {glow > 0.001 && (
            <div style={{ position: "absolute", left: 0, top: 0, transform: `translate3d(${P.x}px, ${P.y}px, ${P.z}px)` }}>
              <div
                style={{
                  position: "absolute",
                  left: -170,
                  top: -170,
                  width: 340,
                  height: 340,
                  borderRadius: "50%",
                  background: "radial-gradient(circle, rgba(236,238,241,0.55) 0%, rgba(236,238,241,0.12) 30%, rgba(236,238,241,0) 68%)",
                  opacity: glow,
                  scale: mix(0.3, 1, glow),
                }}
              />
              <div
                style={{
                  position: "absolute",
                  left: -460,
                  top: -1,
                  width: 920,
                  height: 2,
                  background: "linear-gradient(90deg, rgba(236,238,241,0) 0%, rgba(236,238,241,0.55) 50%, rgba(236,238,241,0) 100%)",
                  opacity: glow * 0.7,
                  scale: `${mix(0.15, 1, glow)} 1`,
                }}
              />
              <div style={{ position: "absolute", left: -5, top: -5, width: 10, height: 10, borderRadius: 5, background: C.ink, opacity: glow, boxShadow: "0 0 18px 6px rgba(236,238,241,0.6)" }} />
            </div>
          )}
        </div>
      </Space3D>

      {/* Shutter blink across the frame on "photo". */}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 60% at 50% 45%, rgba(236,238,241,0.16), rgba(236,238,241,0) 70%)", opacity: flash, pointerEvents: "none" }} />
      {/* Tension vignette. */}
      <AbsoluteFill
        style={{ background: "radial-gradient(ellipse 70% 62% at 50% 46%, rgba(7,8,9,0) 40%, rgba(4,5,6,0.78) 100%)", opacity: tension * 0.85, pointerEvents: "none" }}
      />

      {/* Sound: every cut, press, shutter, multiplication and chip wave has its hit; the riser (2 s) lands on the cut. */}
      <Sfx name="swipe" at={T.choosing - 2} volume={0.55} />
      <Sfx name="whoosh-soft" at={T.from - 3} volume={0.5} />
      <Sfx name="pop" at={T.one} volume={0.45} />
      <Sfx name="whoosh-soft" at={T.flat - 8} volume={0.5} />
      <Sfx name="impact" at={T.flat} volume={0.35} />
      <Sfx name="click" at={T.photo} volume={0.7} />
      <Sfx name="tick" at={T.photo + 10} volume={0.45} />
      <Sfx name="tick" at={T.photo + 15} volume={0.4} />
      <Sfx name="tick" at={T.photo + 20} volume={0.35} />
      <Sfx name="whoosh" at={T.photo + 4} volume={0.45} />
      <Sfx name="swipe" at={T.and - 8} volume={0.45} />
      <Sfx name="pop" at={T.spec - 4} volume={0.5} />
      <Sfx name="pop" at={T.sheet - 4} volume={0.5} />
      <Sfx name="pop" at={T.nobody - 4} volume={0.55} />
      <Sfx name="pop" at={T.explains - 4} volume={0.6} />
      <Sfx name="whoosh" at={T.col} volume={0.55} />
      <Sfx name="riser" at={T.end - 2 * fps} volume={0.45} />
    </AbsoluteFill>
  );
};
