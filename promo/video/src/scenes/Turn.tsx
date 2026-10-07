// Scene 4, turn: "Pick any racket and turn it in your hand. Front. Side. Back.
// Every detail, up close."
//
// A browser window shows the hero racket's real page (captured footage, one clip per
// language, word-synced). The camera ORBITS the window, pivoting on the 3D viewer,
// and pushes in as the cursor reaches for the racket, grabs it and turns it round on
// "turn it in your hand". On "Front / Side / Back" the cursor clicks the viewer's
// real buttons exactly on the words (the site's camera glides between views); each
// click nudges the camera. On "Every detail, up close" the racket BREAKS OUT of the
// screen: the captured racket is replaced pixel for pixel (same place, size, view
// angle and perspective, from the site camera recorded during capture) by the
// WebGL hero racket, the window tilts back and falls away under it while the racket
// comes up huge; then the camera cranes and pushes into a macro glide across the
// face texture toward the frame edge, a strip light sweeps the face and a faint
// ball-lime ring marks the sweet spot.
import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Browser3D, Space3D } from "../components/Browser3D";
import { Cursor } from "../components/Cursor";
import { Footage, PageStill, clip, footageCursor, type ClipInfo } from "../components/Footage";
import { Sfx } from "../components/Sfx";
import { clamp, drift, easeInOut, easeOut, enterExit } from "../lib/motion";
import { wordAt, type Lang } from "../timeline";
import type { SceneProps } from "./types";
import { HeroRacket, TurnStage, type HeroCam, type Vec3 } from "./turn/TurnStage";
import { browserPose, bump, hermite, mix, projectPage, smooth, type OrbitPose } from "./turn/rig";

/** Voice words this scene syncs to, per language (fallbacks are the English frames). */
const WORDS = {
  en: { pick: "Pick", turn: "turn", hand: "hand", front: "Front", side: "Side", back: "Back", every: "Every", detail: "detail", up: "up", close: "close" },
} as const;

const PATH = "/rackets/nox-at10-luxury-genius-18k-alum";

// CSS 3D space for the browser.
const PERSP = 2200;
const ORIGIN_X = 50;
const ORIGIN_Y = 45;

/** Site viewer camera: fov 30°, canvas 878 px tall (capture). */
const SITE_FOV = 30;

/** Per capture frame: site camera azimuth, polar, racket centre x/y (page px), page px per metre. */
type CamSample = [number, number, number, number, number];
type TurnClip = ClipInfo & { cam?: CamSample[]; canvas?: { x: number; y: number; w: number; h: number } };

type Marks = {
  pick: number;
  turn: number;
  handEnd: number;
  front: number;
  side: number;
  back: number;
  every: number;
  detail: number;
  up: number;
  close: number;
  grab: number;
  release: number;
  clicks: number[];
  /** Break-out start. */
  B: number;
  END: number;
};

const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

// Easing curves for weighted moves.
const breakEase = Easing.bezier(0.55, 0, 0.22, 1); // slow lift-off, long soft landing
const emergeEase = Easing.bezier(0.5, 0, 0.18, 1);
const macroEase = Easing.bezier(0.42, 0, 0.3, 1);
const swapEase = Easing.bezier(0.45, 0, 0.55, 1); // an even dissolve, not a 3-frame snap
/** The macro glide's ease runs this many frames past the scene end (renormalised), so
 *  the camera is still gliding (~20 % of its peak speed) into the cut instead of parking. */
const MACRO_TAIL = 60;

/* ------------------------------------------------------------------ browser */

/** The camera on the browser (orbit around the viewer), as an orbit pose. */
const orbitAt = (f: number, m: Marks): OrbitPose => {
  const { turn, handEnd, front, every, B, END } = m;
  // Look at the page centre, then at the 3D viewer as the hand reaches for the racket.
  const px = smooth(f, [0, turn - 4, handEnd + 12], [930, 705, 662]);
  const py = smooth(f, [0, turn, front, every], [548, 562, 584, 590]);
  // Where that point sits on screen (offset from the frame centre).
  const sx = smooth(f, [0, turn, front, every], [20, -86, -122, -128]);
  const sy = smooth(f, [0, turn, front, every], [-6, -38, -60, -66]);
  // Push in: a gentle approach, then a real push while the racket is turned.
  let s = smooth(f, [0, turn - 8, handEnd + 8, every], [0.6, 0.665, 0.875, 0.93]);
  // Orbit: from the window's left side round to its right, slowing on the clicks.
  const ry = smooth(f, [0, front, every], [-17, 3.5, 7]);
  const rx = smooth(f, [0, front, every], [7.5, 3.2, 1.8]);
  const rz = smooth(f, [0, every], [-1.3, 0.5]);
  // Each click lands with a small push.
  const punch = m.clicks.reduce((a, c) => a + bump(f, c - 2, 5, 36), 0);
  s *= 1 + 0.016 * punch;

  // Break-out: the window tilts back, recedes and drops away under the racket.
  const u = interpolate(f, [B, B + 62], [0, 1], { ...clamp, easing: breakEase });
  const late = interpolate(f, [B + 40, END], [0, 1], clamp);
  const hand = (k: string, a: number, sp = 0.1) => drift(`turn-b-${k}`, f, a, sp);
  return {
    px,
    py,
    sx: sx + hand("sx", 7) - 40 * u,
    sy: sy + hand("sy", 5) + 250 * u + 160 * late,
    z: -1150 * u - 520 * late,
    rx: rx + hand("rx", 0.55) + 50 * u + 10 * late,
    ry: ry + hand("ry", 0.75) - 6 * u,
    rz: rz + hand("rz", 0.25),
    s,
  };
};

/* ------------------------------------------------------------- the hand-off */

type Match = { shiftX: number; shiftY: number; dist: number; fov: number; yaw: number; pitch: number };

/**
 * Where the captured racket is on screen at frame f, as a WebGL camera that puts
 * the hero model in exactly the same place, at the same size, from the same angle,
 * with the same perspective (same camera distance as the site's viewer).
 */
const matchAt = (f: number, m: Marks, cams: CamSample[]): Match => {
  const cs = cams[Math.max(0, Math.min(cams.length - 1, Math.round(f)))];
  const pose = browserPose(orbitAt(f, m));
  const c = projectPage(pose, cs[2], cs[3], PERSP, ORIGIN_X, ORIGIN_Y);
  const a = projectPage(pose, cs[2], cs[3] - 80, PERSP, ORIGIN_X, ORIGIN_Y);
  const b = projectPage(pose, cs[2], cs[3] + 80, PERSP, ORIGIN_X, ORIGIN_Y);
  const k = Math.hypot(b.x - a.x, b.y - a.y) / 160; // screen px per page px at the racket
  const pxm = cs[4] * k; // screen px per metre
  const dist = 439 / Math.tan(rad(SITE_FOV / 2)) / cs[4]; // the site camera's distance
  const fov = 2 * deg(Math.atan(540 / (dist * pxm)));
  return { shiftX: c.x - 960, shiftY: c.y - 540, dist, fov, yaw: -cs[0], pitch: Math.PI / 2 - cs[1] };
};

/* ---------------------------------------------------------------- the scene */

export const Turn: React.FC<SceneProps> = ({ timing, timeline, lang }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const D = timing.duration;
  const ov = timeline.overlapFrames;
  const END = D + ov;
  const W = WORDS[lang as Lang];

  const CLIP = `turn-page-${lang}`;
  const EMPTY = `turn-empty-${lang}`;
  const info = clip(CLIP) as TurnClip;
  const cams = info.cam ?? [[Math.PI, Math.PI / 2, 659, 570, 1284]];
  const ev = info.events ?? [];

  const every = wordAt(timing, W.every, 290);
  const m: Marks = {
    pick: wordAt(timing, W.pick, 24),
    turn: wordAt(timing, W.turn, 85),
    handEnd: wordAt(timing, W.hand, 135, 0, "end"),
    front: wordAt(timing, W.front, 162),
    side: wordAt(timing, W.side, 203),
    back: wordAt(timing, W.back, 250),
    every,
    detail: wordAt(timing, W.detail, 302),
    up: wordAt(timing, W.up, 331),
    close: wordAt(timing, W.close, 336),
    grab: ev.find((e) => e.type === "grab")?.frame ?? 82,
    release: ev.find((e) => e.type === "release")?.frame ?? 128,
    clicks: ev.filter((e) => e.type === "click").map((e) => e.frame),
    B: every - 8,
    END,
  };
  const { B } = m;

  const env = enterExit(frame, D, ov);

  /* ----------------------------------------------------------- browser */
  const pose = browserPose(orbitAt(frame, m));
  // The hand-off, in three steps so the racket never dims or doubles:
  //  1. the WebGL hero fades in ON TOP of the full captured racket (exactly over it);
  //  2. only once it is opaque does the page underneath swap to the racket-less still
  //     (fading both at once left the racket ~75 % opaque mid-dissolve);
  //  3. only once the page has no racket left does the hero leave the captured pose.
  const H = 10; // hero dissolve frames
  const heroIn = interpolate(frame, [B, B + H], [0, 1], { ...clamp, easing: swapEase });
  const pageSwap = interpolate(frame, [B + H, B + H + 5], [0, 1], { ...clamp, easing: easeInOut });
  const GLUE = H + 5; // frames the hero stays glued to the captured racket
  // The window's glass glare peaks right over the viewer at the break-out and lifts the
  // captured racket's blacks (~+15 levels); the WebGL racket is not behind glass. Wipe
  // the glare off during the glide to "Back" so both rackets share one tone at the swap.
  const glare = interpolate(frame, [B - 44, B - 6], [1, 0], { ...clamp, easing: easeInOut });
  const fall = interpolate(frame, [B, B + 62], [0, 1], { ...clamp, easing: breakEase });
  const fade = interpolate(frame, [B + 40, END], [0, 1], clamp);
  const browserOpacity = mix(1, 0.5, fall) * mix(1, 0.55, fade);
  const browserBlur = 4.5 * fall + 2 * fade;

  // Captured cursor (page px), fading as the racket leaves the screen.
  const cur = footageCursor(CLIP, frame);
  const curOpacity = interpolate(frame, [B - 4, B + 8], [1, 0], clamp);
  const grab = frame >= m.grab - 16 && frame <= m.release + 4;

  /* --------------------------------------------------------- hero (WebGL) */
  const showHero = frame >= B;
  let heroCam: HeroCam | null = null;
  let yaw = 0;
  let pitch = 0;
  if (showHero) {
    const m0 = matchAt(B, m, cams);
    const u = frame - B;
    const e = interpolate(u, [0, 64], [0, 1], { ...clamp, easing: emergeEase }); // racket comes up huge
    // Macro glide: eased over a span that ends MACRO_TAIL frames after the scene, then
    // renormalised so it still reaches 1 on the last frame, with speed left over.
    const gSpan = END - B - 26 + MACRO_TAIL;
    const gNorm = macroEase((END - B - 26) / gSpan);
    const g = Math.min(1, interpolate(u, [26, 26 + gSpan], [0, 1], { ...clamp, easing: macroEase }) / gNorm);
    const hand = (k: string, a: number, sp = 0.09) => drift(`turn-h-${k}`, frame, a, sp);
    // Free camera path (from the camera matched at the break-out). The racket lands big with
    // the whole head in frame (headroom above the rim, throat clear of the subtitles);
    // only then does the macro push crop in.
    const dist = mix(m0.dist, 0.75, e) * mix(1, 0.405, g);
    const fov = mix(m0.fov, 31, e) - 5 * g;
    const shiftX = mix(m0.shiftX, 190, e) * (1 - g) + hand("sx", 6);
    const shiftY = mix(m0.shiftY, -4, e) * (1 - g) + hand("sy", 4);
    const free = {
      shiftX,
      shiftY,
      dist,
      fov,
    };
    // Through the whole cross-fade the hero stays glued to the captured racket (the
    // window has started to move), so the dissolve never shows two rackets; only once
    // the captured one has gone does the camera ease off the match onto the free path
    // (measured: blending during the dissolve left the last frames 8-14 px apart).
    const w = interpolate(u, [GLUE, GLUE + 18], [0, 1], { ...clamp, easing: swapEase });
    const camAz = w * (0.6 * g + 0.03 * e + hand("az", 0.012));
    const camEl = w * (0.04 * e + 0.2 * g + hand("el", 0.01));
    const target: Vec3 = [w * 0.072 * g, w * (mix(0, 0.05, e) + 0.035 * g), w * 0.017 * g];
    const roll = w * (-0.05 * e + 0.09 * g);
    const mf = matchAt(frame, m, cams);
    const cam = {
      shiftX: mix(mf.shiftX, free.shiftX, w),
      shiftY: mix(mf.shiftY, free.shiftY, w),
      dist: mix(mf.dist, free.dist, w),
      fov: mix(mf.fov, free.fov, w),
    };
    const pos: Vec3 = [
      target[0] + cam.dist * Math.sin(camAz) * Math.cos(camEl),
      target[1] + cam.dist * Math.sin(camEl),
      target[2] + cam.dist * Math.cos(camAz) * Math.cos(camEl),
    ];
    heroCam = { position: pos, target, fov: cam.fov, roll, shiftX: cam.shiftX, shiftY: cam.shiftY };

    // Orientation: the captured view angle through the hand-off (the site's camera is
    // still gliding to "Back"), then the glide continues with the same speed into the
    // exact back view.
    const hEnd = B + GLUE;
    const settle = hEnd + 46;
    const cA = cams[Math.min(cams.length - 1, hEnd)];
    const cP = cams[Math.min(cams.length - 1, hEnd - 1)];
    const yawV = -(cA[0] - cP[0]);
    const pitchV = -(cA[1] - cP[1]);
    if (frame <= hEnd) {
      const cs = cams[Math.min(cams.length - 1, frame)];
      yaw = -cs[0];
      pitch = Math.PI / 2 - cs[1];
    } else {
      yaw = hermite(frame, hEnd, settle, -cA[0], -Math.PI, yawV, 0);
      pitch = hermite(frame, hEnd, settle, Math.PI / 2 - cA[1], 0, -pitchV, 0);
    }
    yaw += 0.05 * g;
  }
  const heroOpacity = heroIn;
  const ring = interpolate(frame, [m.up - 4, m.up + 30], [0, 1], { ...clamp, easing: easeOut });
  const sweepT = interpolate(frame, [m.detail - 6, m.close + 70], [0, 1], { ...clamp, easing: Easing.bezier(0.4, 0, 0.6, 1) });
  const sweepX = mix(-1.8, 1.8, sweepT);
  const sweep = Math.sin(sweepT * Math.PI) * 0.9;

  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{
          opacity: env.opacity,
          scale: env.scale,
          filter: env.blur > 0.01 ? `blur(${env.blur}px)` : undefined,
        }}
      >
        {/* The browser with the real racket page. */}
        <AbsoluteFill style={{ opacity: browserOpacity, filter: browserBlur > 0.01 ? `blur(${browserBlur}px)` : undefined }}>
          <Space3D perspective={PERSP} originX={ORIGIN_X} originY={ORIGIN_Y}>
            <Browser3D {...pose} path={PATH} glare={glare}>
              {pageSwap < 1 && <Footage name={CLIP} frame={frame} />}
              {pageSwap > 0 && <PageStill name={EMPTY} style={{ opacity: pageSwap }} />}
              {cur && curOpacity > 0 && (
                // The grabbing hand is drawn smaller than the arrow: scale it up to read.
                <Cursor x={cur.x} y={cur.y} down={cur.down} grab={grab} clicks={m.clicks} frame={frame} opacity={curOpacity} scale={grab ? 1.55 : 1.35} />
              )}
            </Browser3D>
          </Space3D>
        </AbsoluteFill>

        {/* The hero racket, out of the screen. */}
        {showHero && heroCam && (
          <AbsoluteFill style={{ opacity: heroOpacity }}>
            <TurnStage width={width} height={height} cam={heroCam} sweepX={sweepX} sweep={sweep}>
              <HeroRacket yaw={yaw} pitch={pitch} ring={ring} ringScale={mix(0.9, 1, ring)} />
            </TurnStage>
          </AbsoluteFill>
        )}
      </AbsoluteFill>

      <Sfx name="whoosh-soft" at={m.grab - 2} volume={0.3} />
      {m.clicks.map((c) => (
        <Sfx key={c} name="click" at={c} volume={0.6} />
      ))}
      <Sfx name="whoosh" at={B - 2} volume={0.6} />
      <Sfx name="shimmer" at={m.up - 4} volume={0.2} />
    </AbsoluteFill>
  );
};
