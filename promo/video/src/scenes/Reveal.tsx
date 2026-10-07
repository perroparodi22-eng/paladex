// Scene 3, reveal: "Meet Paladex. Every padel racket, in 3D."
//
// One camera, one 3D world. The logo lockup and the browser window live in the same
// space and are filmed by a single orbit camera (target + yaw/pitch + dolly), so every
// move has real parallax:
//
//   0          impact: a soft light flash and shock ring bloom out of the point the
//              Problem scene collapsed into; the mark punches in like a racket swing
//              and the ball pops off its face. Slow push-in + orbit on the mark.
//   "Paladex"  the wordmark rises letter by letter as the mark glides aside.
//   "Every"    the camera cranes down and pushes forward: the lockup lifts up and past
//              the lens (motion-blurred), and the browser window, waiting deeper and
//              lower in the dark, rises toward us and swings round to face the camera.
//              It shows real captured footage of the home page (the hero racket
//              auto-turning on its stage, the site's own "Every padel racket, in 3D.").
//   "3D"       the swing settles; the dolly and orbit keep creeping in while the
//              captured cursor drifts to "Browse rackets", then the house exit.
import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { Browser3D, Space3D } from "../components/Browser3D";
import { Cursor } from "../components/Cursor";
import { Footage, clip, footageCursor } from "../components/Footage";
import { LogoMark } from "../components/Logo";
import { Sfx } from "../components/Sfx";
import { clamp, drift, easeInOut, easeOut, enterExit, mix } from "../lib/motion";
import { display } from "../theme";
import { wordAt } from "../timeline";
import type { SceneProps } from "./types";

/** Voice words this scene syncs to, per language (fallbacks are the English frames). */
const WORDS = {
  en: { paladex: "Paladex", every: "Every", threeD: "3D" },
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
const WIN_SCALE = 0.525;

const MARK = 196; // logo mark size, px
const WORD = 152; // wordmark font size, px
const GAP = 34;

// Easing curves for the weighted camera moves.
const travelEase = Easing.bezier(0.33, 0, 0.1, 1); // gentle lift-off, long soft landing
const lateralEase = Easing.bezier(0.45, 0, 0.15, 1); // sideways component lags: the path arcs
const swingEase = Easing.bezier(0.4, 0, 0.12, 1); // the window's turn lags its travel
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

export const Reveal: React.FC<SceneProps> = ({ timing, timeline, lang }) => {
  const frame = useCurrentFrame();
  const D = timing.duration;
  const ov = timeline.overlapFrames;
  const END = D + ov;

  // Voice sync (scene-local frames).
  const paladexAt = wordAt(timing, WORDS[lang].paladex, 54);
  const everyAt = wordAt(timing, WORDS[lang].every, 119);
  const threeDAt = wordAt(timing, WORDS[lang].threeD, 217);

  const env = enterExit(frame, D, ov);

  /* ---------------------------------------------------------------- camera */
  // The swing: from just before "Every" until it settles on "3D".
  const swingStart = everyAt - 6;
  const camAt = (f: number): Cam => {
    const sp = interpolate(f, [swingStart, threeDAt], [0, 1], clamp);
    const t = travelEase(sp);
    const tl = lateralEase(sp);
    // Hand-held float, always on (tiny, slow).
    const hand = (seed: string, amp: number) => drift(`rv-cam-${seed}`, f, amp, 0.1);
    return {
      tx: WIN_POS.x * tl + interpolate(f, [swingStart, END], [0, 70], clamp) + hand("x", 6),
      ty: WIN_POS.y * t + hand("y", 5),
      tz: WIN_POS.z * t,
      // A slow orbit for the whole shot (never a stop).
      yaw: interpolate(f, [0, END], [11, -6]) + hand("yaw", 0.5),
      pitch: interpolate(f, [0, END], [2.5, -1]) + hand("pitch", 0.4),
      roll: hand("roll", 0.25),
      // A continuous push-in, from the impact to the last frame.
      dolly: -130 + 2 * f,
    };
  };
  const cam = camAt(frame);

  /* ------------------------------------------------------------ logo lockup */
  const punch = interpolate(frame, [0, 24], [0, 1], { ...clamp, easing: punchEase });
  const hit = interpolate(frame, [3, 30], [0, 1], { ...clamp, easing: easeOut });
  const wordStart = paladexAt - 7;
  const open = interpolate(frame, [wordStart, wordStart + 34], [0, 1], { ...clamp, easing: easeInOut });

  // On "Every" the lockup lifts up and toward the lens while the camera passes under
  // it: fade it by depth and blur it by its on-screen speed (a stand-in for motion
  // blur) and its closeness.
  const liftAt = (f: number) => interpolate(f, [swingStart - 2, swingStart + 36], [0, 1], { ...clamp, easing: liftEase });
  const logoPos = (f: number) => ({ x: 0, y: LOGO_LIFT.y * liftAt(f), z: LOGO_LIFT.z * liftAt(f) });
  const lift = liftAt(frame);
  const L = project(cam, logoPos(frame));
  const Lp = project(camAt(frame - 1), logoPos(frame - 1));
  const logoSpeed = Math.hypot(L.x - Lp.x, L.y - Lp.y) + Math.abs(L.k - Lp.k) * 400;
  const logoOpacity = interpolate(L.z, [520, 1080], [1, 0], { ...clamp, easing: Easing.bezier(0.4, 0, 0.7, 1) });
  const logoBlur = Math.min(18, logoSpeed * 0.1) + interpolate(L.z, [250, 1000], [0, 10], clamp);
  const halo = (0.05 + 0.1 * (1 - punch)) * logoOpacity;

  /* ---------------------------------------------------------------- window */
  const sp = interpolate(frame, [swingStart, threeDAt], [0, 1], clamp);
  const pR = swingEase(sp);
  const winHand = (seed: string, amp: number) => drift(`rv-w-${seed}`, frame, amp, 0.11);
  const winPose = {
    x: WIN_POS.x + winHand("x", 4),
    y: WIN_POS.y + winHand("y", 3),
    z: WIN_POS.z,
    // Swings round to face the camera; keeps turning a touch toward us after the settle.
    rotateX: mix(26, 1.5, pR) + winHand("rx", 0.35),
    rotateY: mix(-44, -10, pR) + interpolate(frame, [swingStart, END], [0, 9], clamp) + winHand("ry", 0.5),
    rotateZ: mix(-5, 0, pR),
    scale: WIN_SCALE,
  };
  const winOpacity = interpolate(frame, [swingStart, swingStart + 22], [0, 1], { ...clamp, easing: easeOut });
  // Rack focus: soft while deep and moving, sharp as it arrives.
  const winBlur = interpolate(travelEase(sp), [0, 0.62], [5, 0], clamp);

  /* ------------------------------------------------------------ footage sync */
  const clipF = frame - (threeDAt - POSE_FRAME);
  const cur = footageCursor(CLIP, clipF);
  const curOpacity = interpolate(clipF, [MOVE_FRAME - 4, MOVE_FRAME + 8], [0, 1], { ...clamp, easing: easeOut });

  /* ------------------------------------------------------------------ flash */
  // A hot core blooming out of the point the Problem scene collapsed into, a brief
  // lift of the whole frame, and one thin shock ring.
  const core = interpolate(frame, [0, 30], [0.85, 0], { ...clamp, easing: Easing.bezier(0.15, 0.55, 0.35, 1) });
  const coreR = interpolate(frame, [0, 30], [150, 1000], { ...clamp, easing: easeOut });
  const wash = interpolate(frame, [0, 16], [0.09, 0], { ...clamp, easing: easeOut });
  const ring = interpolate(frame, [0, 44], [0, 1], { ...clamp, easing: easeOut });

  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{
          opacity: env.opacity,
          scale: env.scale,
          filter: env.blur > 0.01 ? `blur(${env.blur}px)` : undefined,
        }}
      >
        {/* The browser window with the real home page, deep in the same world. */}
        {frame >= swingStart && (
          <World cam={cam} style={{ filter: winBlur > 0.01 ? `blur(${winBlur}px)` : undefined }}>
            <Browser3D {...winPose} path="/" opacity={winOpacity} glare={mix(2.4, 1, pR)}>
              <Footage name={CLIP} frame={clipF} />
              {cur && curOpacity > 0 && <Cursor x={cur.x} y={cur.y} down={cur.down} frame={clipF} opacity={curOpacity} />}
            </Browser3D>
          </World>
        )}

        {/* The logo lockup, at the world origin, with its halo a little behind it. */}
        {logoOpacity > 0.001 && (
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
                    scale: mix(0.42, 1, punch) * mix(1.4, 1, open),
                    rotate: `${mix(-38, 0, punch)}deg`,
                    filter: punch < 0.999 ? `blur(${(1 - punch) * 12}px)` : undefined,
                    opacity: interpolate(frame, [0, 3], [0, 1], clamp),
                    translate: "0px -6px",
                  }}
                >
                  <LogoMark size={MARK} hit={hit} />
                </div>
                <Word frame={frame} at={wordStart + 3} />
              </div>
            </AbsoluteFill>
          </World>
        )}
      </AbsoluteFill>

      {/* Impact flourish, over the transition (not faded in by the envelope). */}
      {frame < 48 && (
        <AbsoluteFill style={{ pointerEvents: "none" }}>
          <AbsoluteFill style={{ backgroundColor: `rgba(236,238,241,${wash})` }} />
          <AbsoluteFill
            style={{
              background: `radial-gradient(circle ${coreR}px at 50% 50%, rgba(255,255,255,${core}) 0%, rgba(236,238,241,${core * 0.45}) 22%, rgba(236,238,241,${core * 0.12}) 55%, rgba(236,238,241,0) 100%)`,
            }}
          />
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
              scale: mix(0.05, 1, ring),
              opacity: 0.42 * (1 - ring) ** 1.3,
            }}
          />
        </AbsoluteFill>
      )}

      <Sfx name="impact" at={0} volume={0.7} />
      <Sfx name="shimmer" at={wordStart} volume={0.22} />
      <Sfx name="whoosh" at={swingStart} volume={0.5} />
    </AbsoluteFill>
  );
};

/** "Paladex", letters rising out of a soft blur. */
const Word: React.FC<{ frame: number; at: number }> = ({ frame, at }) => {
  const letters = "Paladex".split("");
  return (
    <div style={{ ...display, fontSize: WORD, lineHeight: 1, letterSpacing: "-0.03em", whiteSpace: "nowrap", paddingLeft: GAP }}>
      {letters.map((ch, i) => {
        const t = interpolate(frame, [at + i * 2.4, at + i * 2.4 + 26], [0, 1], { ...clamp, easing: easeOut });
        return (
          <span
            key={i}
            style={{
              display: "inline-block",
              opacity: t,
              translate: `0px ${(1 - t) * 0.42 * WORD}px`,
              filter: t < 0.999 ? `blur(${(1 - t) * 10}px)` : undefined,
            }}
          >
            {ch}
          </span>
        );
      })}
    </div>
  );
};
