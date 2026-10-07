// Scene 1, cold open: "You're about to spend two hundred euros on a padel racket…"
//
// Beats (scene-local frames, all derived from the voice):
//   0          pure black. Nothing under this scene, so it builds up from nothing.
//   ~4 → You're   a soft back light blooms behind the racket and the rim lights crawl
//                 down both sides of the frame: we first read it as a silhouette.
//   spend      the key light lifts the face out of the dark while the studio opens
//              around it; slow push-in and a slight orbit the whole time.
//   two        a big, quiet "€200" rises beside it (the camera has already
//              reframed to the right to make room).
//   racket     a strip light glides across the face (one reflection sweep).
//   end − 22   the price clears left, the racket winds up and whips round (accelerating
//              spin + push-in + horizontal motion blur), dissolving as the Problem scene
//              arrives on top (house exit from enterExit, no enter: we start from black).
// No captures: pure WebGL + type.
import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Grain } from "../components/Backdrop";
import { HERO_SLUG, RacketModel } from "../components/Racket3D";
import { Sfx } from "../components/Sfx";
import { clamp, drift, easeInOut, enterExit, mix } from "../lib/motion";
import { C, display } from "../theme";
import { wordAt } from "../timeline";
import { ColdStage, type LightRig, type Vec3 } from "./cold-open/ColdStage";
import type { SceneProps } from "./types";

const FOV = 30;
const TAN = Math.tan(((FOV / 2) * Math.PI) / 180);
/** Screen px per world unit at distance d (1080 px tall frame). */
const ppu = (d: number) => 540 / (d * TAN);
/** Height of the head centre above the model's bounding-box centre (m). */
const HEAD_Y = 0.104;

const cssEase = Easing.bezier(0.25, 0.1, 0.25, 1);
const softIn = Easing.bezier(0.45, 0, 0.2, 1);
const glyphRise = Easing.bezier(0.16, 1, 0.3, 1);

/** The price glyphs: a small raised euro sign (ink-3), then the digits (ink). */
const PRICE_GLYPHS = ["€", "2", "0", "0"];

export const ColdOpen: React.FC<SceneProps> = ({ timing, timeline }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const dur = timing.duration;
  const ov = timeline.overlapFrames;

  // ---------- Voice sync (scene-local frames, English fallbacks) ----------
  const youAt = wordAt(timing, "You're", 36);
  const spendAt = wordAt(timing, "spend", 58);
  const priceAt = wordAt(timing, "two", 85);
  const racketAt = wordAt(timing, "racket", 176);

  // ---------- Exit timing ----------
  // The whip starts 20 frames before the cut and is still accelerating when the
  // racket dissolves under the next scene.
  const whipFrom = dur - 20;
  const spinEnd = dur + 16;
  // House exit only (scale up, blur, fade over the overlap); no enter: we build from black.
  const env = enterExit(frame, dur, ov, { enter: false });

  // ---------- Camera: slow push-in, slight orbit, a reframe that makes room for the price ----------
  const push = interpolate(frame, [0, dur + 10], [0, 1], { ...clamp, easing: cssEase });
  const whipPush = interpolate(frame, [whipFrom - 4, dur + ov], [0, 1], { ...clamp, easing: Easing.bezier(0.55, 0, 0.75, 0.55) });
  const d = mix(2.1, 1.12, push) - 0.4 * whipPush;
  const orbit = interpolate(frame, [0, dur + 10], [0, 1], { ...clamp, easing: Easing.bezier(0.3, 0.1, 0.35, 1) });
  const az = mix(0.34, -0.1, orbit) + drift("co-az", frame, 0.012, 0.09);
  const el = mix(-0.075, 0.02, orbit) + drift("co-el", frame, 0.008, 0.08);
  const reframe = interpolate(frame, [spendAt - 8, priceAt + 22], [0, 1], { ...clamp, easing: easeInOut });
  const recenter = interpolate(frame, [whipFrom - 8, dur + 8], [0, 1], { ...clamp, easing: easeInOut });
  const offX = 0.19 * reframe * (1 - recenter);
  const lookY = mix(0.0, 0.03, push);
  const right: Vec3 = [Math.cos(az), 0, -Math.sin(az)];
  const camPos: Vec3 = [
    Math.sin(az) * Math.cos(el) * d - right[0] * offX,
    Math.sin(el) * d + lookY,
    Math.cos(az) * Math.cos(el) * d - right[2] * offX,
  ];
  const camTarget: Vec3 = [-right[0] * offX, lookY, -right[2] * offX];
  const roll = mix(-0.03, 0.005, orbit) + drift("co-roll", frame, 0.004, 0.07) - 0.03 * whipPush;

  // ---------- Light reveal ----------
  // Rim lights come up first (boosted, so the frame's outline glows while the face is dark),
  // then settle to the site's rig as the key light lifts the face.
  const rimUp = interpolate(frame, [4, youAt + 22], [0, 1], { ...clamp, easing: Easing.bezier(0.35, 0, 0.25, 1) });
  const keyFrom = spendAt - 12;
  const keyTo = priceAt + 14;
  const rimSettle = interpolate(frame, [keyFrom, keyTo + 70], [0, 1], { ...clamp, easing: easeInOut });
  const key = interpolate(frame, [keyFrom, keyTo], [0, 1], { ...clamp, easing: softIn });
  const fill = interpolate(frame, [keyFrom + 12, priceAt + 44], [0, 1], { ...clamp, easing: easeInOut });
  const sweepT = interpolate(frame, [racketAt - 18, racketAt + 46], [0, 1], { ...clamp, easing: easeInOut });
  const rig: LightRig = {
    rim: rimUp * mix(3, 1, rimSettle),
    rimEnv: rimUp * mix(0.8, 1, key),
    back: rimUp * mix(4, 0.7, rimSettle),
    camAz: az,
    rimTravel: interpolate(frame, [4, youAt + 40], [0, 1], { ...clamp, easing: Easing.bezier(0.3, 0, 0.3, 1) }),
    key,
    fill,
    sweepX: mix(-2.6, 2.6, sweepT),
    sweep: Math.sin(Math.PI * sweepT) * 2.8,
    exposure: 1.05,
  };

  // ---------- Racket: slow turn into the light, then the whip ----------
  // Angle of the face relative to the camera (0 = facing it).
  const slowTurn = (f: number) => -0.62 + 0.25 * interpolate(f, [0, 165], [0, 1], { ...clamp, easing: Easing.bezier(0.4, 0, 0.2, 1) }) + 0.0035 * f;
  // A small counter-turn (anticipation) before the whip.
  const windUp = (f: number) => interpolate(f, [whipFrom - 22, whipFrom + 3], [0, 1], { ...clamp, easing: easeInOut });
  // Accelerating spin (power curve): gentle at first, ~0.25 rad/frame at the cut, faster as it dissolves.
  const spin = (f: number) => {
    const t = interpolate(f, [whipFrom, spinEnd], [0, 1], clamp);
    return Math.PI * 2.5 * Math.pow(t, 2.2);
  };
  const relAt = (f: number) => slowTurn(f) - 0.12 * windUp(f) + spin(f);
  const rel = relAt(frame);
  const yaw = az + rel;
  const tilt = mix(0.16, 0.1, orbit) + drift("co-tilt", frame, 0.015, 0.1);
  // Face tipped slightly down in the dark (so only the rims catch light), then it lifts into the key light.
  const lift = interpolate(frame, [keyFrom - 10, keyTo + 10], [0, 1], { ...clamp, easing: easeInOut });
  const pitch = mix(0.1, -0.06, lift) + drift("co-pitch", frame, 0.012, 0.08);

  // Horizontal motion blur from the spin only (px), gated so the slow turn stays perfectly sharp.
  const omega = Math.abs(relAt(frame + 0.5) - relAt(frame - 0.5)) - 0.0035;
  const edgeSpeed = Math.max(0, omega) * 0.13 * ppu(d); // px/frame at the edge of the head
  const racketBlurX = Math.min(30, Math.max(0, edgeSpeed * 0.32 - 0.6));
  // The racket dissolves through the overlap so the next scene builds on a clean stage.
  const racketFade = 1 - interpolate(frame, [dur - 2, dur + 12], [0, 1], { ...clamp, easing: easeInOut });

  // ---------- Darkness: the studio opens up with the key light ----------
  const P = ppu(d);
  const headX = width / 2 + offX * P;
  const headY = height / 2 - (HEAD_Y - lookY) * P;
  const veil = 1 - interpolate(key, [0, 1], [0, 0.97]);
  const iris = mix(260, 2400, Math.pow(key, 1.3));
  // Back light: a soft pool on the "wall" behind the racket, so the dark head reads as a
  // silhouette (and light shows through its holes) before the key light arrives.
  const halo = interpolate(frame, [2, youAt + 24, keyTo + 10], [0, 1, 0.35], { ...clamp, easing: Easing.bezier(0.4, 0, 0.3, 1) });
  const haloR = 0.3 * P;

  // ---------- Price ----------
  const priceSize = 300;
  const priceOut = interpolate(frame, [whipFrom - 10, whipFrom + 12], [0, 1], { ...clamp, easing: Easing.bezier(0.6, 0, 0.9, 0.5) });
  const priceDrift = interpolate(frame, [priceAt, dur], [0, 1], { ...clamp, easing: cssEase });

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: env.blur > 0.05 ? `blur(${env.blur}px)` : undefined }}>
      <svg width={0} height={0} style={{ position: "absolute" }} aria-hidden>
        <defs>
          <filter id="co-racket-mb" x="-25%" y="-5%" width="150%" height="110%">
            <feGaussianBlur stdDeviation={`${racketBlurX} 0`} />
          </filter>
          <filter id="co-price-mb" x="-30%" y="-10%" width="160%" height="120%">
            <feGaussianBlur stdDeviation={`${priceOut * 24} 0`} />
          </filter>
        </defs>
      </svg>

      {/* Darkness over the studio backdrop, opening around the racket as the key light comes up. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at ${headX}px ${headY}px, rgba(1,1,2,${veil * mix(1, 0.3, Math.min(1, key * 2))}) 0px, rgba(1,1,2,${veil}) ${iris}px)`,
        }}
      />
      {/* Back light behind the head. */}
      <AbsoluteFill
        style={{
          opacity: halo * racketFade,
          background: `radial-gradient(ellipse ${haloR * 1.25}px ${haloR * 1.35}px at ${headX}px ${headY}px, rgba(214,221,233,0.17) 0%, rgba(214,221,233,0.085) 42%, rgba(214,221,233,0.025) 75%, rgba(214,221,233,0) 100%)`,
        }}
      />

      {/* The price, beside the racket. */}
      <AbsoluteFill style={{ perspective: 1800, perspectiveOrigin: "30% 45%" }}>
        <div
          style={{
            position: "absolute",
            left: 210,
            top: 300,
            display: "flex",
            alignItems: "flex-start",
            ...display,
            fontSize: priceSize,
            lineHeight: 1,
            color: C.ink,
            transformOrigin: "0% 50%",
            translate: `${mix(24, -18, priceDrift) - priceOut * 260}px 0px`,
            rotate: `0 1 0 ${mix(9, 3, priceDrift)}deg`,
            scale: mix(0.985, 1.03, priceDrift),
            filter: priceOut > 0.001 ? "url(#co-price-mb)" : undefined,
            opacity: 1 - priceOut,
          }}
        >
          {PRICE_GLYPHS.map((g, i) => {
            const t = interpolate(frame, [priceAt - 4 + i * 3, priceAt + 30 + i * 3], [0, 1], { ...clamp, easing: glyphRise });
            const isSign = g === "€";
            return (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  fontSize: isSign ? priceSize * 0.42 : priceSize,
                  marginTop: isSign ? priceSize * 0.11 : 0,
                  marginRight: isSign ? priceSize * 0.05 : 0,
                  color: isSign ? C.ink3 : C.ink,
                  opacity: t,
                  translate: `0px ${(1 - t) * priceSize * 0.32}px`,
                  filter: t < 0.999 ? `blur(${(1 - t) * 18}px)` : undefined,
                }}
              >
                {g}
              </span>
            );
          })}
        </div>
      </AbsoluteFill>

      {/* The hero racket in the studio. */}
      <AbsoluteFill style={{ opacity: racketFade, filter: racketBlurX > 0.3 ? "url(#co-racket-mb)" : undefined }}>
        <ColdStage width={width} height={height} camera={{ position: camPos, target: camTarget, fov: FOV, roll }} rig={rig}>
          <group rotation={[pitch, 0, tilt]}>
            <RacketModel slug={HERO_SLUG} rotation={[0, yaw, 0]} />
          </group>
        </ColdStage>
      </AbsoluteFill>

      {/* While the studio is dark, grain over the racket too, so its unlit body sits in the same black. */}
      <Grain opacity={0.07 * veil} />

      <Sfx name="shimmer" at={keyFrom + 6} volume={0.35} />
      <Sfx name="whoosh-soft" at={priceAt - 8} volume={0.3} />
      <Sfx name="whoosh" at={dur - 21} volume={0.6} />
    </AbsoluteFill>
  );
};
