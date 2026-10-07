// Scene 1, cold open: "Two hundred euros. Maybe more. For one padel racket."
//
// A rhythmic montage of real, finished racket models (one WebGL stage; each shot is
// a pure function in cold-open/shots.ts and a cut is the next shot taking over).
// Beats (scene-local frames, all derived from the voice):
//   0        macro: the camera slides across a racket face as a strip light glints
//   flash1   whip: a racket swings through frame (motion blur), others cross behind
//   flash2   macro: a frame edge turns toward the lens
//   Two      SLAM: "€200" hits huge over a row of rackets the camera snaps along
//   euros    cut: a ring of rackets wheels past a low camera (price punches)
//   mid1     cut: macro up a racket face
//   Maybe    the price rolls up to €250; a whole wall of rackets, camera trucks
//   more     €300; a line of rackets flips over one after another
//   mid2     the camera flies forward down a corridor of rackets
//   For      the price whips away; the hero spins in from deep in the dark…
//   racket   …and lands centre (impact, glint) and keeps pushing in and turning
//   Would    …the question lands: the hero starts to lose focus and light
//   buy it   a blindfold band wipes across the racket
//   blind    the band closes in over the blurred hero with a "?"; then the house exit.
import React, { useMemo } from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { RacketModel } from "../components/Racket3D";
import { Sfx } from "../components/Sfx";
import { clamp, drift, enterExit, mix } from "../lib/motion";
import { ColdStage, type LightRig } from "./cold-open/ColdStage";
import { Price } from "./cold-open/Price";
import { buildShots, cuts, ramp, shotAt } from "./cold-open/shots";
import { C, display } from "../theme";
import type { SceneProps } from "./types";

const hit = Easing.bezier(0.1, 0.85, 0.2, 1);

/** 1 at frame `at`, decaying to 0 over `len` frames (and 0 before). */
const pulse = (f: number, at: number, len: number) => (f < at ? 0 : interpolate(f, [at, at + len], [1, 0], { ...clamp, easing: Easing.bezier(0.2, 0.6, 0.4, 1) }));

export const ColdOpen: React.FC<SceneProps> = ({ timing, timeline }) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const dur = timing.duration;
  const ov = timeline.overlapFrames;
  const T = useMemo(() => cuts(timing), [timing]);
  const shots = useMemo(() => buildShots(T, ov), [T, ov]);

  const shot = shotAt(shots, frame);
  const lt = frame - shot.from;
  const S = shot.at(lt, shot.to - shot.from, frame);

  // House exit (no enter: the film starts here).
  const env = enterExit(frame, dur, ov, { enter: false });

  // ---------- Cut accents: every cut lands with a small punch-in and a whip smear ----------
  const cutFrames = shots.map((s) => s.from).filter((f) => f > 0);
  let punch = 0;
  let smear = 0;
  for (const c of cutFrames) {
    punch = Math.max(punch, pulse(frame, c, 9));
    const d = frame - c;
    if (d >= -2 && d <= 2) smear = Math.max(smear, 1 - Math.abs(d) / 3);
  }
  const blurDir = S.blur[0] >= S.blur[1] ? "x" : "y";
  const bx = S.blur[0] + (blurDir === "x" ? smear * 26 : 0);
  const by = S.blur[1] + (blurDir === "y" ? smear * 26 : 0);

  // ---------- Light rig: the site's studio, rims pushed so black frames read on black ----------
  const az = Math.atan2(S.cam.position[0] - S.cam.target[0], S.cam.position[2] - S.cam.target[2]);
  const land = pulse(frame, T.racket, 26);
  const rig: LightRig = {
    rim: 1.6 + 0.8 * land,
    rimEnv: 1.25,
    back: 0.7,
    camAz: az,
    rimTravel: 1,
    key: 1,
    fill: 0.9,
    sweepX: S.sweepX,
    sweep: S.sweep,
    exposure: 1.08 + 0.25 * land,
  };

  // ---------- "Would you buy it blind?" ----------
  const wouldF = T.would;
  const buyF = T.buy;
  const blindF = T.blind;
  const fade = ramp(frame, buyF - 6, blindF + 6, Easing.bezier(0.4, 0, 0.3, 1));
  const band = ramp(frame, buyF - 2, T.it + 6, Easing.bezier(0.2, 0.8, 0.2, 1));
  const bandClose = ramp(frame, blindF - 2, blindF + 12, Easing.bezier(0.1, 0.8, 0.2, 1));
  const qMark = ramp(frame, blindF - 1, blindF + 14, Easing.bezier(0.1, 0.9, 0.2, 1));
  const blindBlur = 7 * fade;

  // ---------- Price ----------
  const slam = ramp(frame, T.two, T.two + 8, hit);
  const priceIn = interpolate(frame, [T.two - 1, T.two + 2], [0, 1], clamp);
  const priceOut = ramp(frame, T.forW - 2, T.forW + 9, Easing.bezier(0.6, 0, 0.9, 0.5));
  const bump = 0.05 * pulse(frame, T.hundred, 10) + 0.06 * pulse(frame, T.euros, 12) + 0.07 * pulse(frame, T.maybe, 12) + 0.08 * pulse(frame, T.more, 12);
  const priceScale = mix(1.9, 1, slam) * (1 + bump) * mix(1, 1.07, ramp(frame, T.two, T.forW, Easing.linear));
  const shake = 10 * pulse(frame, T.two, 12);
  const showPrice = frame >= T.two - 1 && priceOut < 1;

  // Flashes: the slam, the flicks, the landing.
  const flash = 0.55 * pulse(frame, T.two, 14) + 0.16 * pulse(frame, T.maybe, 8) + 0.2 * pulse(frame, T.more, 8) + 0.38 * pulse(frame, T.racket, 18);
  const streak = Math.max(pulse(frame, T.two, 20), 0.8 * pulse(frame, T.racket, 24));

  // The light pool behind the rackets lifts the black, moving with the shot.
  const poolA = 0.12 * S.pool.a * (1 + 0.6 * land);

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: env.blur > 0.05 ? `blur(${env.blur.toFixed(2)}px)` : undefined }}>
      <svg width={0} height={0} style={{ position: "absolute" }} aria-hidden>
        <defs>
          <filter id="co-mb" x="-10%" y="-10%" width="120%" height="120%">
            <feGaussianBlur stdDeviation={`${bx.toFixed(2)} ${by.toFixed(2)}`} />
          </filter>
          <filter id="co-pmb" x="-10%" y="-40%" width="120%" height="180%">
            <feGaussianBlur stdDeviation={`0 ${(priceOut * 40).toFixed(2)}`} />
          </filter>
        </defs>
      </svg>

      {/* Light pool behind the rackets. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse 52% 62% at ${S.pool.x}% ${S.pool.y}%, rgba(214,221,233,${poolA}) 0%, rgba(214,221,233,${poolA * 0.4}) 40%, rgba(7,8,9,0) 75%)`,
        }}
      />

      {/* The montage: one WebGL stage, the active shot's rackets. */}
      <AbsoluteFill
        style={{
          scale: 1 + 0.045 * punch,
          filter: [bx + by > 0.4 ? "url(#co-mb)" : "", fade > 0.01 ? `blur(${blindBlur.toFixed(2)}px) brightness(${mix(1, 0.8, fade).toFixed(3)})` : ""].filter(Boolean).join(" ") || undefined,
        }}
      >
        <ColdStage width={width} height={height} camera={S.cam} rig={rig} fog={S.fog}>
          {S.items.map((it) => (
            <RacketModel key={`${shot.id}-${it.key}`} slug={it.slug} position={it.pos} rotation={it.rot} scale={it.scale ?? 1} />
          ))}
        </ColdStage>
      </AbsoluteFill>

      {/* Anamorphic streak on the big hits. */}
      {streak > 0.002 && (
        <AbsoluteFill style={{ pointerEvents: "none" }}>
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: frame >= T.racket ? height * 0.43 : height * 0.5,
              height: 3,
              background: "linear-gradient(90deg, rgba(236,238,241,0) 0%, rgba(236,238,241,0.7) 50%, rgba(236,238,241,0) 100%)",
              opacity: streak,
              scale: `${mix(1.3, 0.4, streak)} 1`,
              filter: "blur(1px)",
              boxShadow: "0 0 30px 6px rgba(236,238,241,0.25)",
            }}
          />
        </AbsoluteFill>
      )}

      {/* A soft dark scrim under the price so it reads over the rackets. */}
      {showPrice && (
        <AbsoluteFill
          style={{ background: "radial-gradient(ellipse 34% 26% at 50% 47%, rgba(5,6,7,0.62) 0%, rgba(5,6,7,0.3) 55%, rgba(5,6,7,0) 100%)", opacity: priceIn * (1 - priceOut), pointerEvents: "none" }}
        />
      )}

      {/* The price. */}
      {showPrice && (
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", pointerEvents: "none" }}>
          <div
            style={{
              opacity: priceIn * (1 - priceOut),
              scale: priceScale,
              translate: `${drift("co-px", frame, 6, 0.3) * (shake / 10) + drift("co-pdx", frame, 8, 0.06)}px ${-30 - priceOut * 700 + drift("co-py", frame, 6, 0.33) * (shake / 10)}px`,
              filter: priceOut > 0.001 ? "url(#co-pmb)" : slam < 1 ? `blur(${((1 - slam) * 16).toFixed(2)}px)` : undefined,
            }}
          >
            {/* The shadow is a drop-shadow filter on the whole number: a text-shadow would be clipped by each odometer column. */}
            <div style={{ filter: "drop-shadow(0 30px 50px rgba(0,0,0,0.6)) drop-shadow(0 0 3px rgba(0,0,0,0.35))" }}>
            <Price
              frame={frame}
              size={430}
              hundreds={[[T.more, "3"]]}
              tens={[
                [T.maybe, "5"],
                [T.more, "0"],
              ]}
            />
            </div>
          </div>
        </AbsoluteFill>
      )}

      {/* The blindfold: a dark band wipes across the racket on "buy it", then closes in on "blind". */}
      {band > 0.001 && (
        <AbsoluteFill style={{ pointerEvents: "none", alignItems: "center", justifyContent: "center" }}>
          <div
            style={{
              width: width * 1.25,
              height: height * mix(0.15, 0.22, bandClose),
              rotate: `${-3.5 + drift("co-bd", frame, 0.5, 0.08)}deg`,
              translate: `${mix(-width * 1.3, 0, band) + drift("co-bx", frame, 14, 0.07)}px ${-height * 0.04 + drift("co-by", frame, 8, 0.09)}px`,
              background: "linear-gradient(180deg, rgba(4,5,6,0) 0%, rgba(4,5,6,0.88) 14%, rgba(5,6,7,0.92) 50%, rgba(4,5,6,0.88) 86%, rgba(4,5,6,0) 100%)",
              boxShadow: "0 0 60px 20px rgba(4,5,6,0.4)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <div
              style={{
                ...display,
                fontSize: height * 0.26,
                lineHeight: 1,
                color: C.ink,
                opacity: qMark,
                scale: mix(1.5, 1, qMark),
                filter: `blur(${((1 - qMark) * 18).toFixed(1)}px)`,
                translate: `0px ${drift("co-qy", frame, 6, 0.1)}px`,
                textShadow: "0 0 60px rgba(236,238,241,0.35)",
              }}
            >
              ?
            </div>
          </div>
        </AbsoluteFill>
      )}

      {/* Flash on the hits. */}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 70% 70% at 50% 46%, rgba(236,238,241,0.5), rgba(236,238,241,0.06) 70%)", opacity: flash, pointerEvents: "none" }} />

      {/* Sound: a cut, a hit or a landing on every beat of the montage. */}
      <Sfx name="whoosh" at={0} volume={0.55} />
      <Sfx name="swipe" at={T.flash1 - 2} volume={0.6} />
      <Sfx name="whoosh-soft" at={T.flash2 - 1} volume={0.45} />
      <Sfx name="impact" at={T.two} volume={0.9} />
      <Sfx name="whoosh" at={T.two - 3} volume={0.5} />
      <Sfx name="tick" at={T.hundred} volume={0.4} />
      <Sfx name="swipe" at={T.euros - 2} volume={0.55} />
      <Sfx name="whoosh-soft" at={T.mid1 - 2} volume={0.45} />
      <Sfx name="pop" at={T.maybe} volume={0.6} />
      <Sfx name="tick" at={T.maybe + 2} volume={0.5} />
      <Sfx name="swipe" at={T.maybe - 2} volume={0.5} />
      <Sfx name="pop" at={T.more} volume={0.7} />
      <Sfx name="tick" at={T.more + 2} volume={0.55} />
      <Sfx name="whoosh" at={T.mid2 - 4} volume={0.6} />
      <Sfx name="swipe" at={T.forW - 3} volume={0.65} />
      <Sfx name="riser" at={T.racket - 2 * fps} volume={0.3} />
      <Sfx name="impact" at={T.racket} volume={0.8} />
      <Sfx name="shimmer" at={T.racket + 2} volume={0.5} />
      <Sfx name="swipe" at={T.buy - 2} volume={0.55} />
      <Sfx name="impact" at={T.blind} volume={0.7} />
      <Sfx name="whoosh" at={dur - 10} volume={0.5} />
    </AbsoluteFill>
  );
};
