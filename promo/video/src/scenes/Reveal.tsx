// Scene 3, reveal (v2): "Not anymore. Meet Paladex. Every padel racket, in 3D."
//
// Fast and hit-driven. The scene opens on the impact the Problem scene collapses into.
//
//   0          impact bloom + shock rings (no empty black frame).
//   "Not"      "Not" slams in (flash, shake); "anymore." slams in on its word.
//   +30        the line splits and slides apart; a thin light line draws across the
//              dark (the horizon of the studio) and widens while the voice breathes.
//   "Meet"     small "Meet" punches in on the light line.
//   "Paladex"  the mark swings in with the ball pop-off (flash), wordmark letters rise.
//   "Every"    the lockup lifts past the lens; the real home page (plus two ghosts at
//              depth) swings in FAST on a single camera; it lands at "padel racket".
//   "3D"       the camera pushes in and the window kicks into its final pose (impact);
//              the captured cursor then drifts to "Browse rackets" until the exit.
import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { Browser3D, Space3D } from "../components/Browser3D";
import { Cursor } from "../components/Cursor";
import { Footage, clip, footageCursor } from "../components/Footage";
import { LogoMark } from "../components/Logo";
import { Sfx } from "../components/Sfx";
import { clamp, drift, easeIn, easeInOut, easeOut, enterExit, mix } from "../lib/motion";
import { display } from "../theme";
import { wordAt } from "../timeline";
import type { SceneProps } from "./types";

/** Voice words this scene syncs to, per language (fallbacks are the English frames). */
const WORDS = {
  en: { not: "Not", anymore: "anymore", meet: "Meet", paladex: "Paladex", every: "Every", racket: "racket", threeD: "3D" },
} as const;

const CLIP = "reveal-home";
const CLIP_EVENTS = clip(CLIP).events ?? [];
/** Clip frame captured to land on "3D" (the racket's chosen pose). */
const POSE_FRAME = CLIP_EVENTS.find((e) => e.type === "pose")?.frame ?? 150;
/** Clip frame where the captured cursor starts drifting to "Browse rackets". */
const MOVE_FRAME = CLIP_EVENTS.find((e) => e.type === "move-start")?.frame ?? 160;

/* ----------------------------------------------------------------- world */
/** Perspective distance (px): the eye sits this far in front of the z = 0 plane. */
const PERSP = 2000;
/** Where the browser window waits: lower, a little right, and deep behind the logo. */
const WIN_POS = { x: 300, y: 560, z: -2300 };
/** How far the logo lifts (up and toward the lens) when the camera passes under it. */
const LOGO_LIFT = { y: -650, z: 350, rotateX: 22 };
/** World scale of the window (its on-screen size at the settle also depends on the dolly). */
const WIN_SCALE = 0.62;

const MARK = 196; // logo mark size, px
const WORD = 152; // wordmark font size, px
const GAP = 34;

// Easing curves for the weighted camera moves.
const travelEase = Easing.bezier(0.2, 0, 0.06, 1); // fast start, soft landing
const lateralEase = Easing.bezier(0.3, 0, 0.1, 1); // sideways component lags a touch: the path arcs
const swingEase = Easing.bezier(0.26, 0, 0.08, 1); // the window's turn lags its travel
const punchEase = Easing.bezier(0.12, 0.9, 0.2, 1); // hard hit, soft settle
const liftEase = Easing.bezier(0.5, 0, 0.8, 0.55); // accelerates away

type Cam = { tx: number; ty: number; tz: number; yaw: number; pitch: number; roll: number; dolly: number };

/** The orbit camera as a CSS transform for the world container. */
const camTransform = (c: Cam) =>
  `translateZ(${c.dolly}px) rotateZ(${c.roll}deg) rotateX(${c.pitch}deg) rotateY(${c.yaw}deg) translate3d(${-c.tx}px, ${-c.ty}px, ${-c.tz}px)`;

/** Screen position (offset from the frame centre), scale and depth of a world point. */
const project = (c: Cam, p: { x: number; y: number; z: number }) => {
  const r = Math.PI / 180;
  let x = p.x - c.tx;
  let y = p.y - c.ty;
  let z = p.z - c.tz;
  const cy = Math.cos(c.yaw * r);
  const sy = Math.sin(c.yaw * r);
  [x, z] = [x * cy + z * sy, -x * sy + z * cy];
  const cp = Math.cos(c.pitch * r);
  const sp = Math.sin(c.pitch * r);
  [y, z] = [y * cp - z * sp, y * sp + z * cp];
  z += c.dolly;
  const k = PERSP / Math.max(1, PERSP - z);
  return { x: x * k, y: y * k, k, z };
};

/** A full-frame 3D layer filmed by the scene camera. */
const World: React.FC<{ cam: Cam; children: React.ReactNode; style?: React.CSSProperties }> = ({ cam, children, style }) => (
  <AbsoluteFill style={style}>
    <Space3D perspective={PERSP} originY={50}>
      <AbsoluteFill style={{ transformStyle: "preserve-3d", transform: camTransform(cam) }}>{children}</AbsoluteFill>
    </Space3D>
  </AbsoluteFill>
);

/** Decaying shake after each hit: [frame, strength px]. */
const shakeAt = (frame: number, hits: [number, number][]) => {
  let x = 0;
  let y = 0;
  let r = 0;
  for (const [at, a] of hits) {
    const t = (frame - at) / 16;
    if (t < 0 || t > 1) continue;
    const k = (1 - t) ** 2.2;
    x += Math.sin(t * 46 + at) * a * k;
    y += Math.cos(t * 39 + at * 2) * a * 0.8 * k;
    r += Math.sin(t * 31 + at * 3) * a * 0.012 * k;
  }
  return { x, y, r };
};

/** A light burst (hot core, wash, thin shock ring) that fires at `at` and fades fast. */
const Burst: React.FC<{ frame: number; at: number; amp?: number; size?: number; ring?: boolean }> = ({ frame, at, amp = 1, size = 1, ring = true }) => {
  const f = frame - at;
  if (f < 0 || f > 46) return null;
  const core = amp * 0.85 * interpolate(f, [0, 28], [1, 0], { ...clamp, easing: Easing.bezier(0.15, 0.55, 0.35, 1) });
  const coreR = size * interpolate(f, [0, 28], [150, 1000], { ...clamp, easing: easeOut });
  const wash = amp * 0.09 * interpolate(f, [0, 14], [1, 0], { ...clamp, easing: easeOut });
  const rg = interpolate(f, [0, 44], [0, 1], { ...clamp, easing: easeOut });
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <AbsoluteFill style={{ backgroundColor: `rgba(236,238,241,${wash})` }} />
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle ${coreR}px at 50% 50%, rgba(255,255,255,${core}) 0%, rgba(236,238,241,${core * 0.45}) 22%, rgba(236,238,241,${core * 0.12}) 55%, rgba(236,238,241,0) 100%)`,
        }}
      />
      {ring && (
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: "50%",
            width: 1700,
            height: 1700,
            marginLeft: -850,
            marginTop: -850,
            borderRadius: "50%",
            border: "1.5px solid rgba(236,238,241,1)",
            scale: mix(0.05, 1, rg) * size,
            opacity: 0.42 * amp * (1 - rg) ** 1.3,
          }}
        />
      )}
    </AbsoluteFill>
  );
};

/** Light streaks fired out of the impact point: radial rays plus an anamorphic bar. */
const Streaks: React.FC<{ frame: number }> = ({ frame }) => {
  if (frame > 34) return null;
  const t = interpolate(frame, [0, 26], [0, 1], { ...clamp, easing: easeOut });
  const fade = 1 - interpolate(frame, [4, 34], [0, 1], { ...clamp, easing: easeIn });
  const rays = Array.from({ length: 22 }, (_, i) => {
    const a = (i / 22) * 360 + (i % 2) * 7;
    const len = (260 + ((i * 97) % 5) * 150) * t;
    const start = 120 + t * 260;
    return { a, len, start, w: i % 3 === 0 ? 3 : 1.5 };
  });
  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity: fade }}>
      {rays.map((r, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: "50%",
            top: "50%",
            width: r.len,
            height: r.w,
            marginTop: -r.w / 2,
            transformOrigin: "0 50%",
            transform: `rotate(${r.a}deg) translateX(${r.start}px)`,
            background: "linear-gradient(90deg, rgba(236,238,241,0.9), rgba(236,238,241,0))",
          }}
        />
      ))}
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: "50%",
          width: 2600,
          height: 7,
          marginLeft: -1300,
          marginTop: -3.5,
          background: "linear-gradient(90deg, rgba(236,238,241,0), rgba(255,255,255,1) 50%, rgba(236,238,241,0))",
          boxShadow: "0 0 70px 14px rgba(236,238,241,0.35)",
          scale: `${mix(0.08, 1, t)} ${mix(1.6, 0.3, t)}`,
        }}
      />
      {[0.55, 0.8].map((k, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: "50%",
            top: "50%",
            width: 1300,
            height: 1300,
            marginLeft: -650,
            marginTop: -650,
            borderRadius: "50%",
            border: "2px solid rgba(236,238,241,0.5)",
            scale: interpolate(frame, [i * 5, 30 + i * 5], [0.1, k * 1.9], { ...clamp, easing: easeOut }),
            opacity: 0.5 * (1 - interpolate(frame, [i * 5, 30 + i * 5], [0, 1], clamp)),
          }}
        />
      ))}
    </AbsoluteFill>
  );
};

const TITLE = 214; // "Not anymore." font size, px

/** One slammed word of the opening line. */
const SlamWord: React.FC<{ frame: number; at: number; text: string; dir: number }> = ({ frame, at, text, dir }) => {
  const t = interpolate(frame, [at - 2, at + 9], [0, 1], { ...clamp, easing: punchEase });
  const settle = interpolate(frame, [at, at + 26], [0, 1], { ...clamp, easing: easeOut });
  return (
    <span
      style={{
        display: "inline-block",
        opacity: interpolate(frame, [at - 2, at + 2], [0, 1], clamp),
        scale: mix(1.4, 1, t),
        transformOrigin: dir < 0 ? "100% 60%" : "0% 60%", // grows away from its neighbour: the gap stays
        translate: `${(1 - t) * dir * 70}px 0px`,
        rotate: `${(1 - settle) * dir * 1.6}deg`,
        filter: t < 0.999 ? `blur(${(1 - t) * 22}px)` : undefined,
      }}
    >
      {text}
    </span>
  );
};

export const Reveal: React.FC<SceneProps> = ({ timing, timeline, lang }) => {
  const frame = useCurrentFrame();
  const D = timing.duration;
  const ov = timeline.overlapFrames;
  const END = D + ov;
  const W = WORDS[lang];

  // Voice sync (scene-local frames).
  const notAt = wordAt(timing, W.not, 23) - 7; // lands on the beat just ahead of the voice
  const anymoreAt = wordAt(timing, W.anymore, 40);
  const meetAt = wordAt(timing, W.meet, 100);
  const paladexAt = wordAt(timing, W.paladex, 120);
  const everyAt = wordAt(timing, W.every, 180);
  const racketAt = wordAt(timing, W.racket, 222);
  const threeDAt = wordAt(timing, W.threeD, 263);
  const browserAt = wordAt(timing, "browser", 290);

  const env = enterExit(frame, D, ov);

  // Beat frames derived from the words.
  const splitAt = anymoreAt + 28; // the opening line breaks apart
  const lineAt = splitAt + 4; // the light line starts drawing
  const punchAt = paladexAt - 3; // the mark lands just ahead of the word
  const wordStart = paladexAt - 1;
  const swingStart = everyAt - 6;
  const swingEnd = Math.max(racketAt, everyAt + 38); // the window has arrived
  const shake = shakeAt(frame, [
    [0, 16],
    [notAt, 12],
    [anymoreAt, 22],
    [punchAt, 18],
    [threeDAt, 8],
  ]);

  /* ---------------------------------------------------------------- camera */
  const camAt = (f: number): Cam => {
    const sp = interpolate(f, [swingStart, swingEnd], [0, 1], clamp);
    const t = travelEase(sp);
    const tl = lateralEase(sp);
    const hand = (seed: string, amp: number) => drift(`rv-cam-${seed}`, f, amp, 0.1);
    // After the arrival the camera swings in closer and rolls flat to face the page,
    // landing on "3D" (a second decisive move).
    const fin = easeOut(interpolate(f, [swingEnd - 6, threeDAt + 4], [0, 1], clamp));
    // "right in your browser": pull back and orbit so the whole window, chrome and address
    // bar included, shows the racket turning live in it; it rises clear of the subtitle.
    const post = easeInOut(interpolate(f, [threeDAt + 6, END - 20], [0, 1], clamp));
    return {
      tx: WIN_POS.x * tl + interpolate(f, [swingStart, END], [0, 60], clamp) + hand("x", 6),
      ty: WIN_POS.y * t + 75 * post + hand("y", 5),
      tz: WIN_POS.z * t,
      yaw: interpolate(f, [0, END], [11, -4]) + hand("yaw", 0.5) - 5 * fin + 9 * post,
      pitch: interpolate(f, [0, END], [2.5, -0.5]) + hand("pitch", 0.4),
      roll: hand("roll", 0.25) + 1.4 * (1 - fin) * t,
      dolly: -130 + 1.5 * f + 200 * fin - 230 * post + interpolate(f, [threeDAt, END], [0, 30], clamp),
    };
  };
  const cam = camAt(frame);

  /* ------------------------------------------------------------ opening line */
  const splitP = interpolate(frame, [splitAt, splitAt + 16], [0, 1], { ...clamp, easing: easeIn });
  const titleOn = frame < splitAt + 18;
  const titleShift = (1 - interpolate(frame, [notAt - 2, anymoreAt - 2], [0, 1], { ...clamp, easing: easeOut })) * 0; // layout is reserved
  const drive = interpolate(frame, [notAt, splitAt], [1, 1.08], clamp); // the line creeps toward the lens
  const line = (clipPath: string, dx: number) => (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        clipPath,
        translate: `${dx}px ${titleShift}px`,
        scale: drive,
        opacity: 1 - splitP * 0.6,
      }}
    >
      <div style={{ ...display, fontSize: TITLE, whiteSpace: "nowrap", letterSpacing: "-0.04em", display: "flex", gap: 64 }}>
        <SlamWord frame={frame} at={notAt} text="Not" dir={-1} />
        <SlamWord frame={frame} at={anymoreAt} text="anymore." dir={1} />
      </div>
    </div>
  );

  // The studio horizon: a thin light line draws across the dark, then widens to a glow.
  const lineP = interpolate(frame, [lineAt, meetAt - 2], [0, 1], { ...clamp, easing: Easing.bezier(0.5, 0, 0.1, 1) });
  const lineOut = 1 - interpolate(frame, [punchAt, punchAt + 14], [0, 1], { ...clamp, easing: easeIn });
  // "Meet", on the line.
  const meetIn = interpolate(frame, [meetAt - 2, meetAt + 9], [0, 1], { ...clamp, easing: punchEase });
  const meetOut = interpolate(frame, [punchAt - 2, punchAt + 8], [0, 1], { ...clamp, easing: easeIn });

  /* ------------------------------------------------------------ logo lockup */
  const punch = interpolate(frame, [punchAt, punchAt + 22], [0, 1], { ...clamp, easing: punchEase });
  const hit = interpolate(frame, [punchAt + 3, punchAt + 30], [0, 1], { ...clamp, easing: easeOut });
  const open = interpolate(frame, [wordStart, wordStart + 30], [0, 1], { ...clamp, easing: easeInOut });
  const sweep = interpolate(frame, [wordStart + 22, wordStart + 52], [0, 1], { ...clamp, easing: easeInOut });

  const liftAt = (f: number) => interpolate(f, [swingStart - 2, swingStart + 28], [0, 1], { ...clamp, easing: liftEase });
  const logoPos = (f: number) => ({ x: 0, y: LOGO_LIFT.y * liftAt(f), z: LOGO_LIFT.z * liftAt(f) });
  const lift = liftAt(frame);
  const L = project(cam, logoPos(frame));
  const Lp = project(camAt(frame - 1), logoPos(frame - 1));
  const logoSpeed = Math.hypot(L.x - Lp.x, L.y - Lp.y) + Math.abs(L.k - Lp.k) * 400;
  const logoOpacity = interpolate(L.z, [520, 1080], [1, 0], { ...clamp, easing: Easing.bezier(0.4, 0, 0.7, 1) });
  const logoBlur = Math.min(18, logoSpeed * 0.1) + interpolate(L.z, [250, 1000], [0, 10], clamp);
  const halo = (0.05 + 0.1 * (1 - punch)) * logoOpacity;
  const showLogo = frame >= punchAt - 1 && logoOpacity > 0.001;

  /* ---------------------------------------------------------------- window */
  const sp = interpolate(frame, [swingStart, swingEnd], [0, 1], clamp);
  const pR = swingEase(sp);
  const kick = interpolate(frame, [threeDAt - 2, threeDAt + 4, threeDAt + 22], [0, 1, 0], { ...clamp, easing: easeOut });
  const winHand = (seed: string, amp: number) => drift(`rv-w-${seed}`, frame, amp, 0.11);
  const winPose = {
    x: WIN_POS.x + winHand("x", 4),
    y: WIN_POS.y + winHand("y", 3),
    z: WIN_POS.z,
    rotateX: mix(26, 1.5, pR) + winHand("rx", 0.35),
    rotateY: mix(-44, -8, pR) + interpolate(frame, [swingStart, END], [0, 6], clamp) + winHand("ry", 0.5) + 2.5 * kick,
    rotateZ: mix(-6, 0, pR),
    scale: WIN_SCALE * (1 + 0.025 * kick),
  };
  const winOpacity = interpolate(frame, [swingStart, swingStart + 12], [0, 1], { ...clamp, easing: easeOut });
  const winBlur = interpolate(travelEase(sp), [0, 0.6], [6, 0], clamp);
  // Two ghost windows at depth, left and right: the catalogue stretching away.
  const ghostOpacity = interpolate(frame, [swingStart + 8, swingStart + 34], [0, 0.5], { ...clamp, easing: easeOut });
  const ghost = (sign: number) => ({
    x: WIN_POS.x + sign * 1560 + winHand(`gx${sign}`, 6),
    y: WIN_POS.y - 120 + winHand(`gy${sign}`, 5),
    z: WIN_POS.z - 520,
    rotateX: mix(26, 3, pR),
    rotateY: sign * -38 + mix(-44, -8, pR) * 0.4,
    rotateZ: sign * 3,
    scale: WIN_SCALE,
  });

  /* ------------------------------------------------------------ footage sync */
  const clipF = frame - (threeDAt - POSE_FRAME);
  const cur = footageCursor(CLIP, clipF);
  const curOpacity = interpolate(clipF, [MOVE_FRAME - 4, MOVE_FRAME + 8], [0, 1], { ...clamp, easing: easeOut });

  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{
          opacity: env.opacity,
          scale: env.scale,
          filter: env.blur > 0.01 ? `blur(${env.blur}px)` : undefined,
        }}
      >
        <AbsoluteFill style={{ translate: `${shake.x}px ${shake.y}px`, rotate: `${shake.r}deg` }}>
          {/* Opening: the slammed line, then the light line. */}
          {titleOn && (
            <AbsoluteFill>
              {line("inset(0 0 49.7% 0)", -splitP * 1150)}
              {line("inset(50% 0 0 0)", splitP * 1150)}
            </AbsoluteFill>
          )}
          {lineP > 0 && lineOut > 0.001 && (
            <AbsoluteFill style={{ opacity: lineOut }}>
              <div
                style={{
                  position: "absolute",
                  left: "50%",
                  top: "50%",
                  width: 1920,
                  height: 3,
                  marginLeft: -960,
                  marginTop: -1.5,
                  background: "linear-gradient(90deg, rgba(236,238,241,0) 0%, rgba(236,238,241,0.95) 50%, rgba(236,238,241,0) 100%)",
                  boxShadow: "0 0 60px 8px rgba(236,238,241,0.3)",
                  scale: `${mix(0.02, 1.1, lineP)} ${mix(1, 1.6, meetIn)}`,
                  opacity: 0.4 + 0.6 * lineP,
                }}
              />
              <div
                style={{
                  position: "absolute",
                  left: "50%",
                  top: "50%",
                  width: 1500,
                  height: 700,
                  marginLeft: -750,
                  marginTop: -350,
                  background: "radial-gradient(ellipse 50% 50% at 50% 50%, rgba(236,238,241,0.13) 0%, rgba(236,238,241,0) 70%)",
                  opacity: lineP,
                  scale: mix(0.5, 1, lineP),
                }}
              />
              {meetIn > 0 && (
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    paddingBottom: 190,
                  }}
                >
                  <div
                    style={{
                      ...display,
                      fontSize: 150,
                      scale: mix(0.7, 1, meetIn) * mix(1, 1.5, meetOut),
                      opacity: meetIn * (1 - meetOut),
                      filter: `blur(${(1 - meetIn) * 16 + meetOut * 14}px)`,
                    }}
                  >
                    Meet
                  </div>
                </div>
              )}
            </AbsoluteFill>
          )}

          {/* Ghost windows (depth). */}
          {frame >= swingStart && (
            <World cam={cam} style={{ filter: "blur(5px)", opacity: ghostOpacity / 0.5 }}>
              {[-1, 1].map((sg) => (
                <Browser3D key={sg} {...ghost(sg)} path="/" opacity={ghostOpacity} glare={0.4}>
                  <Footage name={CLIP} frame={Math.max(0, Math.min(250, clipF + (sg < 0 ? 70 : 130)))} />
                </Browser3D>
              ))}
            </World>
          )}

          {/* The browser window with the real home page, deep in the same world. */}
          {frame >= swingStart && (
            <World cam={cam} style={{ filter: winBlur > 0.01 ? `blur(${winBlur}px)` : undefined }}>
              <Browser3D {...winPose} path="/" opacity={winOpacity} glare={mix(2.4, 1, pR)}>
                <Footage name={CLIP} frame={Math.max(0, clipF)} />
                {cur && curOpacity > 0 && <Cursor x={cur.x} y={cur.y} down={cur.down} frame={clipF} opacity={curOpacity} />}
              </Browser3D>
            </World>
          )}

          {/* The logo lockup, at the world origin, with its halo a little behind it. */}
          {showLogo && (
            <World cam={cam}>
              <AbsoluteFill
                style={{
                  transform: `translate3d(0px, ${LOGO_LIFT.y * lift}px, ${LOGO_LIFT.z * lift - 220}px)`,
                  background: `radial-gradient(ellipse 36% 32% at 50% 50%, rgba(236,238,241,${halo}) 0%, rgba(236,238,241,${halo * 0.3}) 45%, rgba(7,8,9,0) 75%)`,
                }}
              />
              <AbsoluteFill
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  transform: `translate3d(0px, ${LOGO_LIFT.y * lift}px, ${LOGO_LIFT.z * lift}px) rotateX(${LOGO_LIFT.rotateX * lift}deg)`,
                  opacity: logoOpacity,
                  filter: logoBlur > 0.05 ? `blur(${logoBlur}px)` : undefined,
                }}
              >
                {/* Row = mark + word. Shifted right by (row/2 - mark/2) the mark sits dead
                    centre; as `open` goes to 1 the row glides back to the centred lockup. */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    translate: `calc(${(1 - open) * 50}% - ${((1 - open) * MARK) / 2}px) 0px`,
                  }}
                >
                  <div
                    style={{
                      width: MARK,
                      height: MARK,
                      flexShrink: 0,
                      scale: mix(0.3, 1, punch) * mix(1.4, 1, open),
                      rotate: `${mix(-52, 0, punch)}deg`,
                      filter: punch < 0.999 ? `blur(${(1 - punch) * 14}px)` : undefined,
                      opacity: interpolate(frame, [punchAt, punchAt + 2], [0, 1], clamp),
                      translate: "0px -6px",
                    }}
                  >
                    <LogoMark size={MARK} hit={hit} />
                  </div>
                  <Word frame={frame} at={wordStart + 3} sweep={sweep} />
                </div>
              </AbsoluteFill>
            </World>
          )}
        </AbsoluteFill>
      </AbsoluteFill>

      {/* Impact flourishes, over the transition (not faded in by the envelope). */}
      <Streaks frame={frame} />
      <Burst frame={frame} at={0} amp={1.35} size={1.3} />
      <Burst frame={frame} at={notAt} amp={0.4} size={0.7} ring={false} />
      <Burst frame={frame} at={anymoreAt} amp={0.75} size={0.9} />
      <Burst frame={frame} at={punchAt} amp={0.9} />
      <Burst frame={frame} at={threeDAt} amp={0.3} size={0.8} ring={false} />

      <Sfx name="impact" at={0} volume={0.85} />
      <Sfx name="impact" at={notAt} volume={0.55} />
      <Sfx name="impact" at={anymoreAt} volume={0.9} />
      <Sfx name="swipe" at={splitAt} volume={0.6} />
      <Sfx name="riser" at={lineAt} volume={0.45} />
      <Sfx name="pop" at={meetAt} volume={0.5} />
      <Sfx name="impact" at={punchAt} volume={0.9} />
      <Sfx name="shimmer" at={wordStart + 22} volume={0.3} />
      <Sfx name="whoosh" at={swingStart} volume={0.7} />
      <Sfx name="whoosh-soft" at={swingEnd - 8} volume={0.35} />
      <Sfx name="impact" at={threeDAt} volume={0.55} />
      <Sfx name="whoosh-soft" at={browserAt - 40} volume={0.35} />
      <Sfx name="tick" at={browserAt} volume={0.3} />
    </AbsoluteFill>
  );
};

/** "Paladex", letters rising out of a soft blur, then one light sweep across it. */
const Word: React.FC<{ frame: number; at: number; sweep: number }> = ({ frame, at, sweep }) => {
  const letters = "Paladex".split("");
  return (
    <div style={{ ...display, fontSize: WORD, lineHeight: 1, letterSpacing: "-0.03em", whiteSpace: "nowrap", paddingLeft: GAP, position: "relative" }}>
      {letters.map((ch, i) => {
        const t = interpolate(frame, [at + i * 2, at + i * 2 + 20], [0, 1], { ...clamp, easing: easeOut });
        const glow = Math.max(0, 1 - Math.abs(sweep * (letters.length + 3) - 1.5 - i) / 1.6);
        return (
          <span
            key={i}
            style={{
              display: "inline-block",
              opacity: t,
              translate: `0px ${(1 - t) * 0.42 * WORD}px`,
              filter: t < 0.999 ? `blur(${(1 - t) * 10}px)` : undefined,
              textShadow: glow > 0.01 ? `0 0 ${26 * glow}px rgba(255,255,255,${0.7 * glow})` : undefined,
            }}
          >
            {ch}
          </span>
        );
      })}
    </div>
  );
};
