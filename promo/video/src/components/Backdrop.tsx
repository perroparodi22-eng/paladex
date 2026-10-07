// The black studio: off-black ground, one soft spotlight that slowly breathes and
// drifts, a floor glow, film grain and a vignette. Never fully static.
import React from "react";
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from "remotion";
import { C } from "../theme";
import { drift } from "../lib/motion";

export const Backdrop: React.FC<{
  /** Spotlight centre in % of the frame. */
  spotX?: number;
  spotY?: number;
  /** 0–1 spotlight strength. */
  intensity?: number;
  /** Seed so neighbouring scenes don't drift in lockstep. */
  seed?: string;
  grain?: boolean;
}> = ({ spotX = 50, spotY = 42, intensity = 1, seed = "bg", grain = true }) => {
  const frame = useCurrentFrame();
  const x = spotX + drift(`${seed}-x`, frame, 4, 0.05);
  const y = spotY + drift(`${seed}-y`, frame, 3, 0.04);
  const breathe = 1 + drift(`${seed}-b`, frame, 0.06, 0.08);
  const a = 0.13 * intensity * breathe;
  return (
    <AbsoluteFill style={{ backgroundColor: C.studio, overflow: "hidden" }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse 46% 52% at ${x}% ${y}%, rgba(236,238,241,${a}) 0%, rgba(236,238,241,${a * 0.35}) 38%, rgba(7,8,9,0) 72%)`,
        }}
      />
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse 60% 18% at 50% 96%, rgba(236,238,241,${0.05 * intensity}) 0%, rgba(7,8,9,0) 70%)`,
        }}
      />
      {grain && <Grain />}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 85% 75% at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.55) 100%)" }} />
    </AbsoluteFill>
  );
};

/** Animated film grain: a tiled noise texture jumping to a new offset every 2 frames. */
export const Grain: React.FC<{ opacity?: number }> = ({ opacity = 0.07 }) => {
  const frame = useCurrentFrame();
  const step = Math.floor(frame / 2);
  const ox = (step * 197) % 512;
  const oy = (step * 331) % 512;
  return (
    <AbsoluteFill style={{ opacity, mixBlendMode: "screen", pointerEvents: "none", overflow: "hidden" }}>
      <Img
        src={staticFile("fx/grain.png")}
        style={{ position: "absolute", left: -ox, top: -oy, width: 2560 + 512, height: 1536 + 512, objectFit: "none", objectPosition: "0 0", imageRendering: "pixelated" }}
      />
    </AbsoluteFill>
  );
};
