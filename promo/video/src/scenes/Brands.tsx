// Scene 9, brands: "All the top brands. All in one place."  (no counts: the catalogue grows)
//
//   "All the top brands"  the site's real brand cards (dpr 2 crops of the /rackets rail) sweep
//                         past in 3D: a long row whips across on "All" (turning as it passes
//                         the lens), whips out on "top" as a carousel ring spins in, punches
//                         on "brands" and keeps turning while the camera pushes. A line of
//                         real racket models (WebGL) streams behind it all.
//   "All in one place"    a browser window rises from depth with the real /rackets page; the
//                         ring unrolls: the seven cards the page's rail shows at scroll 0 fly
//                         into their exact slots, where a clean plate of the page shows the
//                         slots empty until each card lands, then hand over to the footage;
//                         the captured cursor picks Nox on "place" and the grid filters
//                         (finished rackets only) while the camera keeps pushing in.
import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, random, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Browser3D, CHROME_H, Space3D, type Pose } from "../components/Browser3D";
import { Cursor } from "../components/Cursor";
import { Footage, clip, still } from "../components/Footage";
import { RacketModel, RacketStage } from "../components/Racket3D";
import { Sfx } from "../components/Sfx";
import { C, FONT } from "../theme";
import { clamp, drift, easeIn, easeInOut, easeOut, enterExit, mix } from "../lib/motion";
import { wordAt } from "../timeline";
import type { SceneProps } from "./types";

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
/** The line runs along -X from the origin (metres); rackets stand on it, turned toward the aisle. */
const WALL_STEP = 0.4;
const WALL_YAW = 0.45; // rad toward the camera side
/** Darkness the far end of the line fades into (close to the backdrop). */
const FOG = "#08090b";

type V3 = [number, number, number];

const wallPose = (i: number, f: number): { position: V3; rotation: V3 } => ({
  position: [-i * WALL_STEP, (random(`br-y-${i}`) - 0.5) * 0.04 + drift(`br-fy-${i}`, f, 0.006, 0.2), 0],
  // Turned toward the aisle, plus a slow idle turn of its own (phase per racket).
  rotation: [drift(`br-tx-${i}`, f, 0.04, 0.15), WALL_YAW + Math.sin(f * 0.02 + i * 1.9) * 0.22, (random(`br-z-${i}`) - 0.5) * 0.06],
});

/* ------------------------------------------------------------- brand ring */
/** The /rackets rail, in the page's order (logo cards captured by capture/shots/brands.mjs). */
const TILES = ["bullpadel", "head", "nox", "adidas", "babolat", "siux", "wilson", "black-crown", "drop-shot", "kuikma", "lok", "starvie"];
/** Cards that are inside the page's visible rail at scroll 0 (the rest are scrolled off to the right). */
const ON_RAIL = 7;

const PERSP = 2000;
/** A carousel ring (world px, frame centre = 0), seen from slightly above, right of the counter. */
const RING = { x: 0, y: -30, z: -200, r: 780, tilt: -12, s: 1.95 };
const RING_STEP = 360 / TILES.length;
/** Card j sits at (j - FRONT) * RING_STEP + spin; spin glides to 0, so the front half then
 * reads left to right in the rail's order (Bullpadel … Wilson) before it unrolls. */
const FRONT = 3;

/* ------------------------------------------------------------- the page */
const CLIP = "brands-rail";
const PAGE = still("brands-page");
const PLATE = still("brands-plate");
const CLICK_FRAME = clip(CLIP).events?.find((e) => e.type === "click")?.frame ?? 84;
/** The captured cursor leaves its rest pose at clip frame 18 (static page before that). */
const MOVE_FROM = 18;
const RAIL_BOX = PAGE.marks?.rail ?? { x: 240, y: 320, w: 1440, h: 221 };
const NOX = PAGE.marks?.["card-nox"] ?? { x: 853, y: 329.3, w: 158, h: 160 };
/** First clip frame where the cursor is over the Nox tile (the site starts its hover there). */
const HOVER_FRAME = (() => {
  const cur = clip(CLIP).cursor ?? [];
  const i = cur.findIndex((c, k) => k > MOVE_FROM && c[1] >= NOX.y - 12);
  return i < 0 ? 49 : i;
})();
/** Where the window settles (world px, frame centre = 0). */
const WIN_REST: Required<Pose> = { x: 0, y: -100, z: 0, rotateX: 3, rotateY: -6, rotateZ: 0, scale: 0.88 };
const WIN_FAR: Required<Pose> = { x: 420, y: 520, z: -2600, rotateX: 22, rotateY: -26, rotateZ: -3, scale: 0.75 };

const DEG = Math.PI / 180;
type P7 = { x: number; y: number; z: number; rx: number; ry: number; rz: number; s: number };

/** Rotate a vector by CSS rotateX(rx) rotateY(ry) rotateZ(rz) (applied right to left). */
const rotate = (v: V3, rx: number, ry: number, rz: number): V3 => {
  let [x, y, z] = v;
  const c = Math.cos(rz * DEG);
  const s = Math.sin(rz * DEG);
  [x, y] = [x * c - y * s, x * s + y * c];
  const cy = Math.cos(ry * DEG);
  const sy = Math.sin(ry * DEG);
  [x, z] = [x * cy + z * sy, -x * sy + z * cy];
  const cx = Math.cos(rx * DEG);
  const sx = Math.sin(rx * DEG);
  [y, z] = [y * cx - z * sx, y * sx + z * cx];
  return [x, y, z];
};

/** World pose of a page point (CSS px) on a window with this pose (same maths as Browser3D). */
const onWindow = (w: Required<Pose>, px: number, py: number): P7 => {
  const [x, y, z] = rotate([(px - 1920 / 2) * w.scale, (py + CHROME_H - (1080 + CHROME_H) / 2) * w.scale, 0], w.rotateX, w.rotateY, w.rotateZ);
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

/** Cosine between a card's face normal and the direction to the lens (CSS perspective camera). */
const facing = (p: P7) => {
  const [nx, ny, nz] = rotate([0, 0, 1], p.rx, p.ry, p.rz);
  const vx = -p.x;
  const vy = -p.y;
  const vz = PERSP - p.z;
  return (nx * vx + ny * vy + nz * vz) / Math.hypot(vx, vy, vz);
};

/** Pick the equivalent angle (± 360) nearest to `to`, so a card never spins the long way round. */
const nearAngle = (a: number, to: number) => a - 360 * Math.round((a - to) / 360);

const travelEase = Easing.bezier(0.3, 0, 0.12, 1);
const rowEase = Easing.bezier(0.08, 0.8, 0.22, 1);
const spinEase = Easing.bezier(0.12, 0.7, 0.25, 1);
const flightEase = Easing.bezier(0.5, 0, 0.2, 1);
const pushEase = Easing.bezier(0.45, 0, 0.75, 0.85);
const whipEase = Easing.bezier(0.75, 0, 0.95, 0.5);

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const clamp11 = (v: number) => Math.max(-1, Math.min(1, v));

/** Fast spike that decays (a punch on a beat). */
const punch = (f: number, at: number, tau: number) => (f < at ? 0 : Math.exp(-(f - at) / tau));

export const Brands: React.FC<SceneProps> = ({ timing, timeline }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const D = timing.duration;
  const ov = timeline.overlapFrames;
  const END = D + ov;

  // Voice sync: "All the top brands. All in one place."
  const allAt0 = wordAt(timing, "All", 17);
  const topAt = wordAt(timing, "top", 47);
  const brandsAt = wordAt(timing, "brands", 63);
  const inAt = wordAt(timing, "in", 131);
  const side1 = wordAt(timing, "side", 62);
  const side2 = wordAt(timing, "side", 91, 1);
  const updAt = wordAt(timing, "updated", 180);
  const everyAt = wordAt(timing, "every", 203);
  const seasonAt = wordAt(timing, "season", 226);
  const allAt = inAt - 17;

  const env = enterExit(frame, D, ov);

  /* ------------------------------------------------------- landing plan */
  // Cards land left to right a beat apart; each hands over to the footage right after.
  const FLIGHT = 32;
  const landAt = (j: number) => allAt + 33 + j * 2.4;
  const flyAt = (j: number) => landAt(j) - FLIGHT;
  const HAND = 10; // frames for a landed card to dissolve into the footage
  const release = flyAt(0);

  /* ------------------------------------------------------------- the wall */
  // A fast dolly along the line (decelerating), then a crane up and back.
  const track = interpolate(frame, [0, release], [0, 1], { ...clamp, easing: Easing.bezier(0.2, 0.5, 0.3, 1) });
  const crane = interpolate(frame, [topAt - 12, release], [0, 1], { ...clamp, easing: easeInOut });
  const camX = mix(0.4, -2.75, track) - interpolate(frame, [release, END], [0, 0.3], clamp);
  const camY = mix(0.08, 1.1, crane) + drift("br-cy", frame, 0.01, 0.1);
  const camZ = mix(1.55, 2.9, crane);
  const look = mix(3.75, 5, crane);
  const camTarget: V3 = [camX - look, mix(0, 0.2, crane), 0];
  const wallIn = interpolate(frame, [0, 8], [0, 1], { ...clamp, easing: easeOut });
  const wallDim = interpolate(frame, [0, topAt, brandsAt + 20, release + 6, release + 26], [0.9, 0.7, 0.55, 0.3, 0], clamp);
  const wallBlur = interpolate(frame, [topAt - 10, brandsAt + 10], [0, 4], clamp);
  const wallOn = frame < release + 28;

  /* ------------------------------------------------------------ brand rows */
  // Three rows of the real brand cards sweep across and turn as they pass the lens.
  const ROW_SCALE = 1.9;
  const ROW_STEP = 158 * ROW_SCALE + 64;
  const t1 = topAt - 8;
  const rowBase =
    frame < t1 ? mix(1500, -300, rowEase(clamp01(frame / t1))) : mix(-300, -4600, whipEase(clamp01((frame - t1) / 13)));
  // Rows are fully gone before the ring appears (no double exposure).
  const rowsOn = frame < t1 + 14;
  const rowFade = 1;
  const rowPunch = punch(frame, allAt0, 7);

  /* --------------------------------------------------------------- window */
  const MOVE = 30; // scene frames for clip frames MOVE_FROM → CLICK_FRAME
  const moveStart = landAt(2) + HAND - 2 - ((HOVER_FRAME - MOVE_FROM) * MOVE) / (CLICK_FRAME - MOVE_FROM);
  const clickAt = moveStart + MOVE;
  const flyStart = release - 8;
  const settle = landAt(ON_RAIL - 1) + 6;
  const fly = interpolate(frame, [flyStart, settle], [0, 1], { ...clamp, easing: travelEase });
  const hand = (seed: string, amp: number) => drift(`br-w-${seed}`, frame, amp, 0.11);
  const winPose: Required<Pose> = (() => {
    const p = mixPose(WIN_FAR, WIN_REST, fly);
    return {
      ...p,
      x: p.x + hand("x", 3) + interpolate(frame, [settle, END], [0, -16], clamp),
      y: p.y + hand("y", 2.5),
      // After the settle the camera keeps pushing in on the rail and the click (never stops).
      z: p.z + interpolate(frame, [settle, END], [0, 200], { ...clamp, easing: pushEase }) + 140 * interpolate(frame, [clickAt, clickAt + 14], [0, 1], { ...clamp, easing: easeOut }),
      rotateY: p.rotateY + hand("ry", 0.35) + interpolate(frame, [settle, END], [0, 3], clamp),
      rotateX: p.rotateX + hand("rx", 0.25),
    };
  })();
  const winOpacity = interpolate(frame, [flyStart, flyStart + 16], [0, 1], { ...clamp, easing: easeOut });
  const winBlur = interpolate(fly, [0, 0.6], [6, 0], clamp);
  const winOn = frame >= flyStart;

  // Footage time: the page holds (cursor at rest) until the Nox card has dissolved into
  // the footage, then the captured approach plays ~2x so the cursor only reaches the Nox
  // tile (where the site starts its hover) after that; the click lands on "place".
  const clipF =
    frame < moveStart
      ? MOVE_FROM
      : frame < clickAt
        ? MOVE_FROM + ((frame - moveStart) * (CLICK_FRAME - MOVE_FROM)) / MOVE
        : Math.min(clip(CLIP).frames - 1, CLICK_FRAME + (frame - clickAt));
  const cur = cursorLerp(clipF);
  const curOpacity = interpolate(frame, [moveStart - 14, moveStart], [0, 1], { ...clamp, easing: easeOut });

  /* ---------------------------------------------------------------- ring */
  const RING_FROM = t1 + 12;
  const ringIn = interpolate(frame, [RING_FROM, RING_FROM + 26], [0, 1], { ...clamp, easing: easeOut });
  const ringOp = interpolate(frame, [RING_FROM, RING_FROM + 8], [0, 1], clamp);
  const ringF = Math.min(frame, release);
  // Spins in fast and glides to rest at the release; then keeps a slow turn while it unrolls.
  const spin = interpolate(ringF, [RING_FROM, release], [330, 0], { ...clamp, easing: spinEase }) - Math.max(0, frame - release) * 0.12;
  const bPunch = Math.max(punch(frame, brandsAt, 6), 0.7 * punch(frame, side1, 6), 0.7 * punch(frame, side2, 6));
  const ringTilt = RING.tilt + interpolate(frame, [brandsAt + 14, release], [0, 9], { ...clamp, easing: easeInOut });
  const ringScale = RING.s * (1 + 0.1 * bPunch) * mix(1, 1.08, interpolate(frame, [brandsAt, release], [0, 1], clamp));
  const ringC = {
    x: RING.x + (1 - ringIn) * 1500,
    y: RING.y + (1 - ringIn) * -80,
    z: RING.z - (1 - ringIn) * 700 + bPunch * 140,
  };
  const tilesOn = frame >= RING_FROM && frame < landAt(ON_RAIL - 1) + HAND + 2;

  const card = (slug: string, key: string, pose: P7, op: number, extra?: React.CSSProperties) => {
    const info = still(`brands-tile-${slug}`);
    const face = facing(pose);
    return (
      <div
        key={key}
        style={{
          position: "absolute",
          left: "50%",
          top: "50%",
          width: info.width,
          height: info.height,
          marginLeft: -info.width / 2,
          marginTop: -info.height / 2,
          transform: `translate3d(${pose.x}px, ${pose.y}px, ${pose.z}px) rotateX(${pose.rx}deg) rotateY(${pose.ry}deg) rotateZ(${pose.rz}deg) scale(${pose.s})`,
          opacity: op,
          borderRadius: 16,
          overflow: "hidden",
          ...extra,
        }}
      >
        {face >= 0 ? (
          <>
            <Img src={staticFile(info.file)} style={{ width: info.width, height: info.height, display: "block" }} />
            {face < 0.97 && <AbsoluteFill style={{ background: "#050607", opacity: interpolate(face, [0, 0.97], [0.75, 0], clamp) }} />}
          </>
        ) : (
          <AbsoluteFill style={{ background: "#0f1114", boxShadow: "inset 0 0 0 1.5px rgba(255,255,255,0.07)", opacity: 0.4 }} />
        )}
      </div>
    );
  };

  const ROWS = [
    { y: -30, s: ROW_SCALE, dir: 1, off: 0, z: 0, op: 1 },
    { y: -400, s: 1.25, dir: -1, off: 1.5, z: -520, op: 0.6 },
    { y: 330, s: 1.25, dir: -1, off: 4.5, z: -520, op: 0.6 },
  ];

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: env.blur > 0.01 ? `blur(${env.blur}px)` : undefined }}>
      {/* The line of rackets (WebGL), behind everything. */}
      {wallOn && (
        <AbsoluteFill style={{ opacity: wallIn * wallDim, filter: wallBlur > 0.05 ? `blur(${wallBlur}px)` : undefined }}>
          <RacketStage width={width} height={height} cameraPosition={[camX, camY, camZ]} cameraTarget={camTarget} fov={30}>
            <fog attach="fog" args={[FOG, mix(2.15, 3.2, crane), mix(7, 9.2, crane)]} />
            {WALL.map((slug, i) => {
              const p = wallPose(i, frame);
              return <RacketModel key={slug} slug={slug} position={p.position} rotation={p.rotation} />;
            })}
          </RacketStage>
        </AbsoluteFill>
      )}

      {/* "All the top brands": rows of real brand cards whipping across, turning in 3D. */}
      {rowsOn && (
        <AbsoluteFill>
          <Space3D perspective={PERSP} originY={50}>
            {ROWS.map((row, r) => {
              const step = ROW_STEP * (row.s / ROW_SCALE);
              const base = row.dir * rowBase * (r === 0 ? 1 : 0.7);
              return TILES.map((slug, j) => {
                const x = base + (j - 5.5 + row.off) * step;
                const ry = -clamp11(x / 1500) * 62;
                const z = row.z - Math.abs(x) * 0.28 + (r === 0 ? rowPunch * 90 : 0);
                const op = rowFade * row.op * interpolate(Math.abs(x), [1500, 2100], [1, 0], clamp);
                if (op < 0.01) return null;
                const pose: P7 = { x, y: row.y + Math.sin(frame * 0.05 + j) * 6, z, rx: 6, ry, rz: 0, s: row.s * (1 + 0.06 * rowPunch) };
                return card(slug, `r${r}-${slug}`, pose, op);
              });
            })}
          </Space3D>
        </AbsoluteFill>
      )}

      {/* The browser window with the real /rackets page. */}
      {winOn && (
        <AbsoluteFill style={{ filter: winBlur > 0.05 ? `blur(${winBlur}px)` : undefined }}>
          <Space3D perspective={PERSP} originY={50}>
            <Browser3D {...winPose} path="/rackets" opacity={winOpacity} glare={mix(2.2, 1, fly)}>
              <Footage name={CLIP} frame={clipF} />
              {/* Clean plate: each brand's slot shows empty until its card has landed. */}
              {TILES.slice(0, ON_RAIL).map((slug, j) => {
                const m = PAGE.marks?.[`card-${slug}`];
                if (!m || frame >= landAt(j)) return null;
                return <PlateSlot key={slug} box={m} railRight={RAIL_BOX.x + RAIL_BOX.w} />;
              })}
              {/* "updated every season": the site's own "New" badges on the fresh rackets light up in turn. */}
              {[updAt, everyAt, seasonAt].map((at, k) => (
                <SeasonTag key={k} frame={frame} at={at} x={601 + k * 355 + 238} y={840} />
              ))}
              {cur && curOpacity > 0.001 && <Cursor x={cur.x} y={cur.y} down={cur.down} frame={clipF} clicks={[CLICK_FRAME]} opacity={curOpacity} />}
            </Browser3D>
          </Space3D>
        </AbsoluteFill>
      )}

      {/* The brand cards: a carousel ring, then each one flies into its slot on the page. */}
      {tilesOn && (
        <AbsoluteFill>
          <Space3D perspective={PERSP} originY={50}>
            {TILES.map((slug, j) => {
              const ringPose = (a: number): P7 => {
                const [x, y, z] = rotate([RING.r * Math.sin(a * DEG), 0, RING.r * Math.cos(a * DEG)], ringTilt, 0, 0);
                return { x: ringC.x + x, y: ringC.y + y + drift(`br-ty-${j}`, frame, 5, 0.18), z: ringC.z + z, rx: ringTilt, ry: a, rz: 0, s: ringScale };
              };
              const onRail = j < ON_RAIL;
              const m = PAGE.marks?.[`card-${slug}`];
              // Only the cards inside the page's visible rail fly; the back of the ring (brands
              // scrolled off the rail on the page) sinks away and dissolves as the ring unrolls.
              const slot = m && onRail ? onWindow(winPose, m.x + m.w / 2, m.y + m.h / 2) : null;
              const t = slot ? interpolate(frame, [flyAt(j), landAt(j)], [0, 1], { ...clamp, easing: flightEase }) : 0;
              const sink = onRail ? 0 : interpolate(frame, [release - 8, release + 16], [0, 1], { ...clamp, easing: easeIn });
              const a = (j - FRONT) * RING_STEP + spin;
              const src = ringPose(slot ? nearAngle(a, slot.ry) : a);
              let p = sink > 0 ? { ...src, z: src.z - sink * 320, y: src.y - sink * 30 } : src;
              if (slot && t > 0) {
                // Straight to the slot, arcing toward the lens on the way (depth), no overshoot.
                const arc = Math.sin(t * Math.PI);
                p = {
                  x: mix(src.x, slot.x, t),
                  y: mix(src.y, slot.y, t) - arc * 40,
                  z: mix(src.z, slot.z, t) + arc * 240,
                  rx: mix(src.rx, slot.rx, t),
                  ry: mix(src.ry, slot.ry, t),
                  rz: mix(src.rz, slot.rz, t),
                  s: mix(src.s, slot.s, t),
                };
              }
              // Landed cards dissolve into the footage.
              const op = onRail ? ringOp * (1 - interpolate(frame, [landAt(j) + 2, landAt(j) + 2 + HAND], [0, 1], { ...clamp, easing: easeInOut })) : ringOp * (1 - sink);
              if (op < 0.002) return null;
              // The rail clips the last visible card (Wilson) at its right edge: match it as the card lands.
              const cut = m ? Math.max(0, m.x + m.w - (RAIL_BOX.x + RAIL_BOX.w)) * interpolate(t, [0.55, 1], [0, 1], { ...clamp, easing: easeInOut }) : 0;
              return card(slug, slug, p, op, {
                clipPath: cut > 0.01 ? `inset(0 ${cut}px 0 0 round 16px ${Math.max(0, 16 - cut)}px ${Math.max(0, 16 - cut)}px 16px)` : undefined,
                boxShadow: t < 0.98 ? `0 ${34 * (1 - t)}px ${70 * (1 - t)}px rgba(0,0,0,${0.6 * (1 - t)})` : undefined,
              });
            })}
          </Space3D>
        </AbsoluteFill>
      )}

      <Sfx name="whoosh" at={2} volume={0.5} />
      <Sfx name="impact" at={allAt0} volume={0.55} />
      <Sfx name="swipe" at={topAt - 8} volume={0.6} />
      <Sfx name="impact" at={brandsAt} volume={0.8} />
      <Sfx name="swipe" at={brandsAt + 20} volume={0.4} />
      <Sfx name="whoosh" at={flyStart} volume={0.55} />
      {Array.from({ length: ON_RAIL }, (_, j) => (
        <Sfx key={j} name={j % 2 ? "tick" : "pop"} at={Math.round(landAt(j))} volume={j === 0 ? 0.5 : 0.3} />
      ))}
      <Sfx name="click" at={Math.round(clickAt)} volume={0.8} />
      <Sfx name="pop" at={Math.round(clickAt) + 6} volume={0.5} />
      <Sfx name="shimmer" at={Math.round(clickAt) + 10} volume={0.4} />
    </AbsoluteFill>
  );
};

/** The captured cursor at a fractional clip frame (interpolated, for the sped-up approach). */
const cursorLerp = (f: number) => {
  const track = clip(CLIP).cursor;
  if (!track?.length) return null;
  const i = Math.max(0, Math.min(track.length - 1, Math.floor(f)));
  const k = Math.min(track.length - 1, i + 1);
  const u = Math.max(0, Math.min(1, f - i));
  return { x: mix(track[i][0], track[k][0], u), y: mix(track[i][1], track[k][1], u), down: track[i][2] === 1 };
};

/** One card's box of the clean plate (the page with that brand's logo card hidden). */
const PlateSlot: React.FC<{ box: { x: number; y: number; w: number; h: number }; railRight: number }> = ({ box, railRight }) => {
  const x = Math.floor(box.x) - 1;
  const y = Math.floor(box.y) - 1;
  const w = Math.min(Math.ceil(box.x + box.w) + 1, railRight) - x;
  const h = Math.ceil(box.y + box.h) + 1 - y;
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, height: h, overflow: "hidden" }}>
      <Img src={staticFile(PLATE.file)} style={{ position: "absolute", left: -x, top: -y, width: PLATE.width, height: PLATE.height, display: "block" }} />
    </div>
  );
};


/** A "New 2026" pill that pops over a card's "New" badge, with a ring that pulses outward. */
const SeasonTag: React.FC<{ frame: number; at: number; x: number; y: number }> = ({ frame, at, x, y }) => {
  const t = interpolate(frame, [at - 4, at + 10], [0, 1], { ...clamp, easing: Easing.bezier(0.2, 1.4, 0.3, 1) });
  if (t <= 0) return null;
  const ring = interpolate(frame, [at, at + 26], [0, 1], clamp);
  const glow = 0.5 + 0.5 * Math.sin((frame - at) * 0.12);
  return (
    <div style={{ position: "absolute", left: x, top: y, width: 96, height: 40, scale: String(t), transformOrigin: "100% 0%" }}>
      <div style={{ position: "absolute", inset: -ring * 22, borderRadius: 999, border: "2px solid rgba(255,255,255,0.8)", opacity: (1 - ring) * 0.9 }} />
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: 999,
          background: C.court,
          color: C.onCourt,
          fontFamily: FONT,
          fontWeight: 620,
          fontSize: 19,
          display: "grid",
          placeItems: "center",
          whiteSpace: "nowrap",
          boxShadow: `0 0 ${14 + 12 * glow}px rgba(255,255,255,0.35), 0 6px 18px rgba(0,0,0,0.5)`,
        }}
      >
        New 2026
      </div>
    </div>
  );
};
