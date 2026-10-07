// Scene 7, brands: "Sixty-two rackets. Thirteen brands. All in one place."
//
// Three beats, each on its words (scene-local frames from the voice timing):
//
//   "Sixty-two rackets"  a concave showroom wall of real racket models (WebGL, 22
//                        different .glb files) with the camera tracking fast along it;
//                        each racket idles on its own axis so the wall reads as 3D. A
//                        big counter rises to 62.
//   "Thirteen brands"    the camera cranes up and back, the wall sinks into the dark,
//                        and the site's real brand tiles (dpr 2 crops of the /rackets
//                        rail) sweep in on a curved rail, turning like a carousel. The
//                        counter rolls over to 13.
//   "All in one place"   a browser window rises from depth with the real /rackets page;
//                        the rail unrolls and every tile flies into its exact slot on
//                        the page (same 3D pose as the window), then hands over to the
//                        footage, where the captured cursor picks Nox and the grid
//                        filters. House exit to the end card.
import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, random, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Browser3D, CHROME_H, Space3D, type Pose } from "../components/Browser3D";
import { Cursor } from "../components/Cursor";
import { Footage, clip, footageCursor, still } from "../components/Footage";
import { RacketModel, RacketStage } from "../components/Racket3D";
import { Sfx } from "../components/Sfx";
import { clamp, drift, easeIn, easeInOut, easeOut, enterExit, mix } from "../lib/motion";
import { C, FONT, display } from "../theme";
import { wordAt } from "../timeline";
import type { SceneProps } from "./types";

/** What the counters say (the catalogue today, as the voice says it). */
const RACKETS = 62;
const BRANDS = 13;

/* ------------------------------------------------------------------ wall */
/** Real traced models, brands interleaved so neighbours always differ. */
const WALL = [
  "bullpadel-vertex-05-27",
  "head-speed-pro-2025",
  "nox-at10-luxury-genius-attack-18k-alum-2026",
  "adidas-metalbone-hrd-plus-2026",
  "babolat-technical-viper-2026",
  "siux-electra-pro-shadow-red-2026",
  "bullpadel-hack-04-2026",
  "wilson-defy-pro-v1",
  "head-coello-pro-2026",
  "nox-ea10-ventus-hybrid-12k-xtrem-2026",
  "lok-maxx-hype-gen-2-yanguas-2026",
  "bullpadel-neuron-27",
  "adidas-arrow-hit-pro-edt-2026",
  "drop-shot-axion-attack-1-5-2025",
  "head-radical-pro-2026",
  "babolat-viper-juan-lebron-3-0-2026",
  "nox-ml10-ventus-control-3k-2026",
  "bullpadel-xplo-27",
  "siux-fenix-pro-2026",
  "wilson-endure-pro-v1-2026",
  "head-extreme-motion-2026",
  "bullpadel-elite-02-27",
];
/** The wall curves toward the camera (a showroom wrapping round the viewer). */
const ARC_R = 3.4;
const STEP = 0.1; // rad between rackets (≈ 0.34 m)
const WALL_Z = -0.3;

type V3 = [number, number, number];

const wallPose = (i: number, f: number): { position: V3; rotation: V3 } => {
  const th = (i - (WALL.length - 1) / 2) * STEP;
  const y = (random(`br-y-${i}`) - 0.5) * 0.05 + drift(`br-fy-${i}`, f, 0.006, 0.2);
  // Faces the centre of the curve, plus a slow idle turn of its own (phase per racket).
  const yaw = -th + Math.sin(f * 0.021 + i * 1.9) * 0.34;
  return {
    position: [ARC_R * Math.sin(th), y, WALL_Z + ARC_R * (1 - Math.cos(th))],
    rotation: [drift(`br-tx-${i}`, f, 0.05, 0.15), yaw, (random(`br-z-${i}`) - 0.5) * 0.08],
  };
};

/* ------------------------------------------------------------- brand rail */
/** The /rackets rail, in the page's order (tile crops captured by capture/shots/brands.mjs). */
const TILES = ["bullpadel", "head", "nox", "adidas", "babolat", "siux", "wilson", "black-crown", "drop-shot", "kuikma", "lok", "starvie"];

const PERSP = 2000;
/** Convex carousel (centre behind the tiles), right of the counter. */
const RAIL = { cx: 380, cy: -10, r: 1250, gap: 11, scale: 1.5 };
const RAIL_CZ = -RAIL.r - 220;

/* ------------------------------------------------------------- the page */
const CLIP = "brands-rail";
const PAGE = still("brands-page");
const CLICK_FRAME = clip(CLIP).events?.find((e) => e.type === "click")?.frame ?? 84;
/** The page's own background behind the rail (covers the footage's tiles until ours land). */
const PAGE_BG = "#0b0c0e";
/** Where the window settles (world px, frame centre = 0). */
const WIN_REST: Required<Pose> = { x: 0, y: -26, z: 0, rotateX: 3, rotateY: -6, rotateZ: 0, scale: 0.74 };
const WIN_FAR: Required<Pose> = { x: 120, y: 420, z: -2600, rotateX: 22, rotateY: -28, rotateZ: -3, scale: 0.74 };

const DEG = Math.PI / 180;
type P7 = { x: number; y: number; z: number; rx: number; ry: number; rz: number; s: number };

/** World position of a page point (CSS px) on a window with this pose (CSS transform order). */
const onWindow = (w: Required<Pose>, px: number, py: number): P7 => {
  // Window-local offset from the window centre (the content box sits under the chrome bar).
  let x = (px - 1920 / 2) * w.scale;
  let y = (py + CHROME_H - (1080 + CHROME_H) / 2) * w.scale;
  let z = 0;
  // rotateZ, then rotateY, then rotateX (the CSS list applies right to left).
  const c = Math.cos(w.rotateZ * DEG);
  const s = Math.sin(w.rotateZ * DEG);
  [x, y] = [x * c - y * s, x * s + y * c];
  const cy = Math.cos(w.rotateY * DEG);
  const sy = Math.sin(w.rotateY * DEG);
  [x, z] = [x * cy + z * sy, -x * sy + z * cy];
  const cx = Math.cos(w.rotateX * DEG);
  const sx = Math.sin(w.rotateX * DEG);
  [y, z] = [y * cx - z * sx, y * sx + z * cx];
  return { x: w.x + x, y: w.y + y, z: w.z + z, rx: w.rotateX, ry: w.rotateY, rz: w.rotateZ, s: w.scale };
};

const mixPose = (a: Required<Pose>, b: Required<Pose>, t: number): Required<Pose> => ({
  x: mix(a.x, b.x, t),
  y: mix(a.y, b.y, t),
  z: mix(a.z, b.z, t),
  rotateX: mix(a.rotateX, b.rotateX, t),
  rotateY: mix(a.rotateY, b.rotateY, t),
  rotateZ: mix(a.rotateZ, b.rotateZ, t),
  scale: mix(a.scale, b.scale, t),
});

const travelEase = Easing.bezier(0.3, 0, 0.12, 1);
const trackEase = Easing.bezier(0.42, 0, 0.3, 1);

export const Brands: React.FC<SceneProps> = ({ timing, timeline }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const D = timing.duration;
  const ov = timeline.overlapFrames;
  const END = D + ov;

  // Voice sync.
  const sixtyAt = wordAt(timing, "Sixty-two", 24);
  const racketsAt = wordAt(timing, "rackets", 61);
  const thirteenAt = wordAt(timing, "Thirteen", 121);
  const brandsAt = wordAt(timing, "brands", 142);
  const allAt = wordAt(timing, "All", 197);
  const placeAt = wordAt(timing, "place", 216);

  const env = enterExit(frame, D, ov);

  /* ------------------------------------------------------------- the wall */
  // Fast lateral track along the wall, then (on "Thirteen") a crane up and back.
  const track = interpolate(frame, [0, thirteenAt + 50], [0, 1], { ...clamp, easing: trackEase });
  const crane = interpolate(frame, [thirteenAt - 14, allAt + 20], [0, 1], { ...clamp, easing: easeInOut });
  const camX = mix(-2.05, 1.05, track) + interpolate(frame, [thirteenAt + 50, END], [0, 0.25], clamp);
  const camY = mix(0.02, 0.42, crane) + drift("br-cy", frame, 0.012, 0.1);
  const camZ = mix(1.45, 2.5, crane);
  const wallIn = interpolate(frame, [0, 14], [0, 1], { ...clamp, easing: easeOut });
  const wallDim = interpolate(frame, [thirteenAt - 12, brandsAt + 8, allAt + 6, allAt + 18], [1, 0.3, 0.16, 0], clamp);
  const wallBlur = interpolate(frame, [thirteenAt - 12, brandsAt + 10], [0, 7], clamp);
  const wallOn = frame < allAt + 18;

  /* ------------------------------------------------------------ counters */
  const count62 = Math.round(RACKETS * interpolate(frame, [sixtyAt - 3, racketsAt + 12], [0, 1], { ...clamp, easing: Easing.bezier(0.2, 0.6, 0.3, 1) }));
  const count13 = Math.round(BRANDS * interpolate(frame, [thirteenAt - 2, brandsAt + 12], [0, 1], { ...clamp, easing: Easing.bezier(0.2, 0.6, 0.3, 1) }));
  const in62 = interpolate(frame, [sixtyAt - 8, sixtyAt + 14], [0, 1], { ...clamp, easing: easeOut });
  const out62 = interpolate(frame, [thirteenAt - 12, thirteenAt + 6], [0, 1], { ...clamp, easing: easeIn });
  const in13 = interpolate(frame, [thirteenAt - 6, thirteenAt + 16], [0, 1], { ...clamp, easing: easeOut });
  const out13 = interpolate(frame, [allAt - 10, allAt + 8], [0, 1], { ...clamp, easing: easeIn });
  const labelR = interpolate(frame, [racketsAt - 6, racketsAt + 16], [0, 1], { ...clamp, easing: easeOut });
  const labelB = interpolate(frame, [brandsAt - 6, brandsAt + 16], [0, 1], { ...clamp, easing: easeOut });
  const scrim = Math.max(in62 * (1 - out62), in13 * (1 - out13));

  /* --------------------------------------------------------------- window */
  const L = placeAt + 18; // the tiles land and the window settles
  const flyStart = allAt - 16;
  const fly = interpolate(frame, [flyStart, L], [0, 1], { ...clamp, easing: travelEase });
  const hand = (seed: string, amp: number) => drift(`br-w-${seed}`, frame, amp, 0.11);
  const winPose: Required<Pose> = (() => {
    const p = mixPose(WIN_FAR, WIN_REST, fly);
    return {
      ...p,
      x: p.x + hand("x", 3) + interpolate(frame, [L, END], [0, -18], clamp),
      y: p.y + hand("y", 2.5),
      // A slow push-in after the settle, so the hold never stops.
      z: p.z + interpolate(frame, [L, END], [0, 70], clamp),
      rotateY: p.rotateY + hand("ry", 0.35) + interpolate(frame, [L, END], [0, 3.5], clamp),
      rotateX: p.rotateX + hand("rx", 0.25),
    };
  })();
  const winOpacity = interpolate(frame, [flyStart, flyStart + 22], [0, 1], { ...clamp, easing: easeOut });
  const winBlur = interpolate(fly, [0, 0.7], [6, 0], clamp);
  const winOn = frame >= flyStart;

  // Footage: the captured click on Nox lands 30 frames after the settle.
  const clipStart = L + 30 - CLICK_FRAME;
  const clipF = frame - clipStart;
  const cur = footageCursor(CLIP, clipF);
  const curOpacity = interpolate(frame, [L - 10, L + 6], [0, 1], { ...clamp, easing: easeOut });
  const patch = interpolate(frame, [L - 6, L + 8], [1, 0], { ...clamp, easing: easeInOut });

  /* ---------------------------------------------------------------- tiles */
  const tilesOn = frame >= thirteenAt - 24 && frame < L + 14;
  const spin = interpolate(frame, [thirteenAt - 22, allAt], [128, 24], { ...clamp, easing: Easing.bezier(0.2, 0.7, 0.25, 1) }) + interpolate(frame, [allAt, L], [0, -6], clamp);
  const conv = (j: number) => interpolate(frame, [allAt - 8 + j * 1.6, L - 2], [0, 1], { ...clamp, easing: Easing.bezier(0.55, 0, 0.18, 1) });
  const tileFade = interpolate(frame, [L, L + 12], [1, 0], { ...clamp, easing: easeIn });

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: env.blur > 0.01 ? `blur(${env.blur}px)` : undefined }}>
      {/* The wall of rackets (WebGL). */}
      {wallOn && (
        <AbsoluteFill style={{ opacity: wallIn * wallDim, filter: wallBlur > 0.05 ? `blur(${wallBlur}px)` : undefined }}>
          <RacketStage width={width} height={height} cameraPosition={[camX, camY, camZ]} cameraTarget={[camX + 0.32, camY * 0.35, WALL_Z]} fov={30}>
            {WALL.map((slug, i) => {
              const p = wallPose(i, frame);
              return <RacketModel key={slug} slug={slug} position={p.position} rotation={p.rotation} />;
            })}
          </RacketStage>
        </AbsoluteFill>
      )}

      {/* Legibility: the dark settles behind the counter. */}
      <AbsoluteFill
        style={{
          opacity: scrim,
          background: "radial-gradient(ellipse 980px 760px at 16% 48%, rgba(7,8,9,0.82) 0%, rgba(7,8,9,0.55) 45%, rgba(7,8,9,0) 75%)",
        }}
      />

      {/* The browser window with the real /rackets page. */}
      {winOn && (
        <AbsoluteFill style={{ filter: winBlur > 0.05 ? `blur(${winBlur}px)` : undefined }}>
          <Space3D perspective={PERSP} originY={50}>
            <Browser3D {...winPose} path="/rackets" opacity={winOpacity} glare={mix(2.2, 1, fly)}>
              <Footage name={CLIP} frame={clipF} />
              {patch > 0.001 && (
                <PagePatch box={PAGE.marks?.rail ?? { x: 240, y: 320, w: 1440, h: 221 }} opacity={patch} />
              )}
              {cur && curOpacity > 0.001 && (
                <Cursor x={cur.x} y={cur.y} down={cur.down} frame={clipF} clicks={[CLICK_FRAME]} opacity={curOpacity} />
              )}
            </Browser3D>
          </Space3D>
        </AbsoluteFill>
      )}

      {/* The brand tiles: a carousel, then each one flies to its slot on the page. */}
      {tilesOn && (
        <AbsoluteFill>
          <Space3D perspective={PERSP} originY={50}>
            {TILES.map((slug, j) => {
              const info = still(`brands-tile-${slug}`);
              const phi = (j - (TILES.length - 1) / 2) * RAIL.gap + spin;
              const rail: P7 = {
                x: RAIL.cx + RAIL.r * Math.sin(phi * DEG),
                y: RAIL.cy + drift(`br-ty-${j}`, frame, 6, 0.18),
                z: RAIL_CZ + RAIL.r * Math.cos(phi * DEG),
                rx: drift(`br-trx-${j}`, frame, 2, 0.15),
                ry: phi,
                rz: 0,
                s: RAIL.scale,
              };
              const m = PAGE.marks?.[`card-${slug}`];
              const slot = m ? onWindow(winPose, m.x + m.w / 2, m.y + m.h / 2) : rail;
              const t = conv(j);
              const p: P7 = {
                x: mix(rail.x, slot.x, t),
                y: mix(rail.y, slot.y, t),
                z: mix(rail.z, slot.z, t),
                rx: mix(rail.rx, slot.rx, t),
                ry: mix(rail.ry, slot.ry, t),
                rz: mix(rail.rz, slot.rz, t),
                s: mix(rail.s, slot.s, t),
              };
              // On the carousel, tiles fade at the far left (the counter's side) and far right.
              const railOp = interpolate(phi, [-48, -30, 62, 84], [0, 1, 1, 0], clamp);
              // Slots outside the page's rail box are scrolled out of view on the site: fade them as they arrive.
              const railBox = PAGE.marks?.rail;
              const offRail = m && railBox ? interpolate(m.x + m.w, [railBox.x + railBox.w - 40, railBox.x + railBox.w + 40], [0, 1], clamp) : 0;
              const op = mix(railOp, 1 - offRail, t) * tileFade;
              if (op < 0.002) return null;
              return (
                <div
                  key={slug}
                  style={{
                    position: "absolute",
                    left: "50%",
                    top: "50%",
                    width: info.width,
                    height: info.height,
                    marginLeft: -info.width / 2,
                    marginTop: -info.height / 2,
                    transform: `translate3d(${p.x}px, ${p.y}px, ${p.z}px) rotateX(${p.rx}deg) rotateY(${p.ry}deg) rotateZ(${p.rz}deg) scale(${p.s})`,
                    opacity: op,
                    borderRadius: 14,
                    overflow: "hidden",
                    boxShadow: t < 0.98 ? `0 ${30 * (1 - t)}px ${60 * (1 - t)}px rgba(0,0,0,${0.55 * (1 - t)})` : undefined,
                  }}
                >
                  <Img src={staticFile(info.file)} style={{ width: info.width, height: info.height, display: "block" }} />
                </div>
              );
            })}
          </Space3D>
        </AbsoluteFill>
      )}

      {/* Counters. */}
      <Counter value={count62} label="rackets" inP={in62} outP={out62} labelP={labelR} frame={frame} seed="r" />
      <Counter value={count13} label="brands" inP={in13} outP={out13} labelP={labelB} frame={frame} seed="b" />

      <Sfx name="whoosh-soft" at={4} volume={0.35} />
      <Sfx name="swipe" at={thirteenAt - 16} volume={0.4} />
      <Sfx name="whoosh" at={flyStart} volume={0.45} />
      <Sfx name="pop" at={L - 2} volume={0.3} />
      <Sfx name="click" at={clipStart + CLICK_FRAME} volume={0.55} />
    </AbsoluteFill>
  );
};

/** A plain patch of the page background over the rail (the footage's own tiles). */
const PagePatch: React.FC<{ box: { x: number; y: number; w: number; h: number }; opacity: number }> = ({ box, opacity }) => (
  <div style={{ position: "absolute", left: box.x - 6, top: box.y - 6, width: box.w + 12, height: box.h + 12, background: PAGE_BG, opacity }} />
);

/** Big number with its label underneath, rising in and lifting out of a soft blur. */
const Counter: React.FC<{ value: number; label: string; inP: number; outP: number; labelP: number; frame: number; seed: string }> = ({
  value,
  label,
  inP,
  outP,
  labelP,
  frame,
  seed,
}) => {
  const vis = inP * (1 - outP);
  if (vis < 0.002) return null;
  const SIZE = 300;
  return (
    <div
      style={{
        position: "absolute",
        left: 170 + drift(`br-cx-${seed}`, frame, 4, 0.1),
        top: 250 + drift(`br-cy-${seed}`, frame, 3, 0.1),
        opacity: vis,
        translate: `0px ${(1 - inP) * 90 - outP * 70}px`,
        filter: inP < 0.999 || outP > 0.001 ? `blur(${(1 - inP) * 16 + outP * 12}px)` : undefined,
      }}
    >
      <div style={{ ...display, fontSize: SIZE, lineHeight: 0.86, fontVariantNumeric: "tabular-nums", letterSpacing: "-0.045em" }}>{value}</div>
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 520,
          fontSize: 64,
          letterSpacing: "-0.01em",
          color: C.ink2,
          marginTop: 26,
          marginLeft: 10,
          opacity: labelP,
          translate: `0px ${(1 - labelP) * 30}px`,
          filter: labelP < 0.999 ? `blur(${(1 - labelP) * 8}px)` : undefined,
        }}
      >
        {label}
      </div>
    </div>
  );
};
