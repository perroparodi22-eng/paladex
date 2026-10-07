// Scene 8, the end card: "Paladex. See it from every side, before you buy it."
// The hero racket arrives big, near the centre and edge-on in the studio light;
// one weighted camera move pulls back and trucks left so the racket settles on the
// right, turning into the key light, and makes room for the type. On "Paladex" the
// mark swings and hits its ball (one soft hit), the wordmark wipes in, then the
// type block cranes up as the headline rises word by word on the voice, the racket
// turns a little faster on "every side", and the CTA pill lands as the line ends.
// No exit: it keeps drifting to the very last frame.
import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { LogoMark, Wordmark } from "../components/Logo";
import { HERO_SLUG, RacketModel, RacketStage } from "../components/Racket3D";
import { Sfx } from "../components/Sfx";
import { clamp, drift, easeIn, easeInOut, easeOut, enterExit, mix, rise } from "../lib/motion";
import { C, FONT, display } from "../theme";
import { wordAt, type Lang, type SceneTiming } from "../timeline";
import type { SceneProps } from "./types";

// ---------------------------------------------------------------------------
// Copy. Edit the CTA here (the final domain is not decided: no URL on purpose).
// `headline` is one string per line; its words are matched to the voiceover.
// ---------------------------------------------------------------------------
const COPY: Record<Lang, { headline: string[]; cta: string; note: string }> = {
  en: {
    headline: ["See it from every side", "before you buy it."],
    cta: "Find your racket",
    note: "Free · No sign-up",
  },
};

// Layout (frame px). Text column on the left, racket on the right (the site's hero
// composition, and a bookend to the cold open), everything above the subtitle band.
const COL_X = 184;
const BLOCK_TOP = 200; // final top of the type block
const MARK = 92; // mark size at rest
const WORDMARK = 68;
const HEAD_SIZE = 92;
const HEAD_GAP = 54; // lockup → headline
const CTA_GAP = 64; // headline → pill
const PILL_H = 92;
const LOCKUP_BIG = 1.6; // lockup scale while it is alone on screen
const ALONE_Y = 468; // lockup centre while alone (≈ the racket's centre)
// Where the racket's centre sits on screen: arrives near the middle, settles right.
const RACKET_FROM = { x: 1150, y: 500 };
const RACKET_TO = { x: 1486, y: 478 };

const norm = (x: string) => x.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

/**
 * Scene-local frame each headline word should rise on: the matching voiceover word
 * (the line is spoken word for word after "Paladex"), else a steady stagger.
 */
const headlineTimes = (timing: SceneTiming, words: string[], fallbackStart: number): number[] => {
  const vo = timing.vo.words;
  let k = vo.findIndex((w) => norm(w.text) === "paladex") + 1;
  let prev = fallbackStart - 6;
  return words.map((w) => {
    const j = vo.findIndex((v, i) => i >= k && norm(v.text) === norm(w));
    if (j >= 0) {
      k = j + 1;
      prev = vo[j].start - timing.start;
    } else {
      prev += 6;
    }
    return prev;
  });
};

export const EndCard: React.FC<SceneProps> = ({ timing, timeline, lang }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const copy = COPY[lang];
  const ov = timeline.overlapFrames;
  const env = enterExit(frame, timing.duration, ov, { exit: false });
  const span = timing.duration + ov; // frames this layer is mounted (no exit: it drifts to the end)

  // --- Beats (all derived from the voice, so EN and IT both land) -----------
  const brandAt = wordAt(timing, "Paladex", 42);
  const brandEnd = wordAt(timing, "Paladex", brandAt + 38, 0, "end");
  const words = copy.headline.flatMap((l) => l.split(" "));
  const times = headlineTimes(timing, words, brandEnd + 22);
  const lineAt = times[0];
  const ctaAt = times[times.length - 1] + 4;
  // The type block cranes up to make room for the line, settling as it starts.
  const craneFrom = brandAt + 10;
  const craneTo = Math.max(brandAt + 44, lineAt + 14);

  // --- Camera: one weighted pull-back + truck that settles as the line starts,
  // then a slow continuous pull-back to the last frame. The racket's centre is
  // held at a chosen screen point (the camera looks straight down -Z).
  const move = interpolate(frame, [0, brandAt + 36], [0, 1], { ...clamp, easing: Easing.bezier(0.2, 0.1, 0.15, 1) });
  const d = mix(1.03, 1.25, move) + 0.0003 * frame + drift("ec-cz", frame, 0.005, 0.07);
  const halfH = Math.tan((15 * Math.PI) / 180); // fov 30
  const halfW = halfH * (width / height);
  const rx = mix(RACKET_FROM.x, RACKET_TO.x, move) - 8 * rise(frame, lineAt, span - lineAt, easeInOut);
  const ry = mix(RACKET_FROM.y, RACKET_TO.y, move);
  const sx = (rx - width / 2) / (width / 2);
  const sy = (height / 2 - ry) / (height / 2);
  const camX = -sx * halfW * d + drift("ec-cx", frame, 0.004, 0.06);
  const camY = -sy * halfH * d + drift("ec-cy", frame, 0.004, 0.05);

  // --- Racket: a slow turntable that picks up a little on "every side" -------
  // The model faces the camera at spin ≈ -0.15 and is edge-on near ±1.5 from there:
  // it arrives nearly edge-on (the frame catching the rim light), turns through the
  // face as the line starts, and rests on the right three-quarter in the key light.
  const everyAt = wordAt(timing, "every", lineAt + 30);
  const sideEnd = wordAt(timing, "side", everyAt + 30, 0, "end");
  const spin =
    -1.38 +
    1.06 * (frame / span) +
    0.84 * interpolate(frame, [everyAt - 60, sideEnd + 50], [0, 1], { ...clamp, easing: Easing.bezier(0.45, 0, 0.55, 1) }) +
    drift("ec-spin", frame, 0.02, 0.05);
  const lean = 0.1 + drift("ec-lean", frame, 0.012, 0.05);
  const pitch = 0.05 + drift("ec-pitch", frame, 0.015, 0.06);
  const bob = drift("ec-bob", frame, 0.004, 0.08);

  // --- Type block -----------------------------------------------------------
  const crane = interpolate(frame, [craneFrom, craneTo], [0, 1], { ...clamp, easing: easeInOut });
  const lockupScale = interpolate(crane, [0, 1], [LOCKUP_BIG, 1], { output: "perceptual-scale" });
  // While alone, the lockup sits level with the racket's centre.
  const restY = BLOCK_TOP + MARK / 2;
  const blockY = mix(ALONE_Y - restY, 0, crane) - 0.03 * frame + drift("ec-ty", frame, 3, 0.07);
  const blockX = drift("ec-tx", frame, 3, 0.06);

  // Mark: the face swings clockwise into the ball (accelerating), hits it up and
  // to the right on "Paladex", follows through a touch and settles.
  const markIn = rise(frame, brandAt - 16, 22);
  const swing =
    interpolate(frame, [brandAt - 16, brandAt], [-34, 0], { ...clamp, easing: easeIn }) +
    7 * Math.sin(Math.PI * interpolate(frame, [brandAt, brandAt + 40], [0, 1], { ...clamp, easing: easeInOut }));
  const hit = interpolate(frame, [brandAt, brandAt + 16], [0, 1], { ...clamp, easing: easeOut });
  // Wordmark wipes in behind the ball.
  const wipe = interpolate(frame, [brandAt + 2, brandAt + 22], [0, 1], { ...clamp, easing: easeOut });

  // CTA lands as the line ends.
  const cta = rise(frame, ctaAt, 20);
  const note = rise(frame, ctaAt + 8, 20);
  const arrow = interpolate(frame, [ctaAt + 14, ctaAt + 44], [0, 1], { ...clamp, easing: easeOut });

  // Final hit: the whole lockup punches once as the CTA lands (the line has finished).
  const finalAt = ctaAt + 26;
  const pulse = interpolate(frame, [finalAt, finalAt + 4, finalAt + 30], [0, 1, 0], { ...clamp, easing: easeOut });

  // Soft light pool behind the racket so the black frame separates from the ground.
  const pool = 0.1 * rise(frame, 0, 40) * (1 + drift("ec-pool", frame, 0.12, 0.08));
  const headTop = BLOCK_TOP + MARK + HEAD_GAP;
  const ctaTop = headTop + HEAD_SIZE * display.lineHeight * copy.headline.length + CTA_GAP;

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: env.blur > 0.01 ? `blur(${env.blur}px)` : undefined }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse 20% 44% at ${(rx / width) * 100}% ${(ry / height) * 100}%, rgba(236,238,241,${pool}) 0%, rgba(236,238,241,${pool * 0.3}) 45%, rgba(7,8,9,0) 75%)`,
        }}
      />

      <RacketStage width={width} height={height} cameraPosition={[camX, camY, d]} cameraTarget={[camX, camY, 0]} exposure={1.02 + 0.2 * pulse}>
        <group rotation={[0, 0, lean]} position={[0, bob, 0]}>
          <RacketModel slug={HERO_SLUG} rotation={[pitch, spin, 0]} />
        </group>
      </RacketStage>

      {/* Type block: drifts back with the camera (a hair, so the hold never freezes) */}
      <AbsoluteFill style={{ translate: `${blockX}px ${blockY}px`, scale: 1.016 - 0.016 * (frame / span), transformOrigin: `${COL_X}px 50%` }}>
        {/* Lockup: mark + wordmark, scaled about its left edge */}
        <div
          style={{
            position: "absolute",
            left: COL_X,
            top: BLOCK_TOP,
            height: MARK,
            display: "flex",
            alignItems: "center",
            gap: 0.26 * MARK,
            scale: lockupScale * (1 + 0.07 * pulse),
            transformOrigin: "0% 50%",
          }}
        >
          <div
            style={{
              opacity: markIn,
              filter: markIn < 0.999 ? `blur(${(1 - markIn) * 10}px)` : undefined,
              rotate: `${swing}deg`,
              transformOrigin: "47% 94%",
            }}
          >
            <LogoMark size={MARK} hit={hit} />
          </div>
          <div
            style={{
              translate: `${(1 - wipe) * -18}px 0px`,
              opacity: Math.min(1, wipe * 1.6),
              maskImage: `linear-gradient(90deg, #000 ${wipe * 130 - 30}%, transparent ${wipe * 130}%)`,
              WebkitMaskImage: `linear-gradient(90deg, #000 ${wipe * 130 - 30}%, transparent ${wipe * 130}%)`,
              paddingRight: 8,
            }}
          >
            <Wordmark size={WORDMARK} />
          </div>
        </div>

        {/* Headline, word by word on the voice */}
        <div style={{ position: "absolute", left: COL_X, top: headTop, ...display, fontSize: HEAD_SIZE, whiteSpace: "nowrap" }}>
          {copy.headline.map((line, li) => {
            const offset = copy.headline.slice(0, li).reduce((n, l) => n + l.split(" ").length, 0);
            return (
              <div key={li}>
                {line.split(" ").map((w, wi) => {
                  const at = times[offset + wi] - 4;
                  const t = interpolate(frame, [at, at + 16], [0, 1], { ...clamp, easing: easeOut });
                  return (
                    <span key={wi} style={{ display: "inline-block", whiteSpace: "pre" }}>
                      <span
                        style={{
                          display: "inline-block",
                          opacity: t,
                          translate: `0px ${(1 - t) * 0.5 * HEAD_SIZE}px`,
                          filter: t < 0.999 ? `blur(${(1 - t) * 14}px)` : undefined,
                        }}
                      >
                        {w}
                      </span>
                      {wi < line.split(" ").length - 1 ? " " : ""}
                    </span>
                  );
                })}
              </div>
            );
          })}
        </div>

        {/* CTA: the site's primary pill (.btn-primary + arrowRight), scaled for the frame */}
        <div style={{ position: "absolute", left: COL_X, top: ctaTop }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 16,
              height: PILL_H,
              padding: "0 40px 0 46px",
              borderRadius: 999,
              background: C.court,
              color: C.onCourt,
              fontFamily: FONT,
              fontWeight: 560,
              fontVariationSettings: '"wdth" 104',
              fontSize: 34,
              letterSpacing: "-0.005em",
              whiteSpace: "nowrap",
              opacity: cta,
              translate: `0px ${(1 - cta) * 34}px`,
              scale: mix(0.94, 1, cta),
              transformOrigin: "0% 50%",
              filter: cta < 0.999 ? `blur(${(1 - cta) * 10}px)` : undefined,
              boxShadow: `0 18px 50px rgba(0,0,0,${0.45 * cta}), 0 0 0 1px rgba(255,255,255,0.4) inset`,
            }}
          >
            {copy.cta}
            <svg
              width={34}
              height={34}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.7}
              strokeLinecap="square"
              strokeLinejoin="miter"
              style={{ display: "block", translate: `${(1 - arrow) * -8 + drift("ec-arrow", frame, 1.2, 0.12)}px 0px`, opacity: 0.25 + 0.75 * arrow }}
            >
              <path d="M4 12h15M13 6l6 6-6 6" />
            </svg>
          </div>
          <div
            style={{
              marginTop: 24,
              marginLeft: 6,
              fontFamily: FONT,
              fontWeight: 480,
              fontSize: 27,
              letterSpacing: "0.005em",
              color: C.ink2,
              opacity: note,
              translate: `0px ${(1 - note) * 16}px`,
              filter: note < 0.999 ? `blur(${(1 - note) * 6}px)` : undefined,
            }}
          >
            {copy.note}
          </div>
        </div>
      </AbsoluteFill>

      {/* Sound: one soft hit on the logo, a breath for the crane, a tick for the CTA. */}
      <Sfx name="impact" at={brandAt} volume={0.6} />
      <Sfx name="pop" at={brandAt} volume={0.4} />
      <Sfx name="whoosh-soft" at={craneFrom} volume={0.18} />
      <Sfx name="tick" at={ctaAt + 2} volume={0.35} />
      <Sfx name="swipe" at={times[0] - 4} volume={0.4} />
      <Sfx name="impact" at={finalAt} volume={0.85} />
      <Sfx name="pop" at={finalAt} volume={0.5} />
      <Sfx name="shimmer" at={finalAt + 2} volume={0.3} />
    </AbsoluteFill>
  );
};
