// Shared motion helpers. Everything is a pure function of the frame (Remotion rule:
// no CSS transitions, no self-running animations).
import { noise2D } from "@remotion/noise";
import { Easing, interpolate } from "remotion";

export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
export const easeOut = Easing.bezier(0.16, 1, 0.3, 1); // the site's --ease-out-expo
export const easeInOut = Easing.bezier(0.76, 0, 0.24, 1); // --ease-in-out-quart
export const easeIn = Easing.bezier(0.7, 0, 0.84, 0);

/** 0→1 over [start, start+dur] with the site's expo ease-out. */
export const rise = (frame: number, start: number, dur: number, easing = easeOut) =>
  interpolate(frame, [start, start + dur], [0, 1], { ...clamp, easing });

/**
 * Organic, never-still drift (simplex noise). Returns values in roughly [-amp, amp].
 * `speed` is in cycles per second at 60 fps. Use different seeds per axis/layer.
 */
export const drift = (seed: string, frame: number, amp = 1, speed = 0.12) => noise2D(seed, frame * (speed / 60), 0.37) * amp;

/** Linear mix helper. */
export const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/**
 * The house transition, so every cut reads as one continuous forward dolly:
 * a scene ARRIVES from slightly behind (scale 0.94 → 1, blur 10 → 0, fade in) over
 * its first `overlap` frames, and LEAVES past the camera (scale 1 → 1.07, blur → 8,
 * fade out) over its last `overlap` frames (duration … duration + overlap), while
 * the next scene arrives on top. Apply to the scene's root layer:
 *   const env = enterExit(frame, timing.duration, timeline.overlapFrames);
 *   <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: `blur(${env.blur}px)` }}>
 * Scenes may add their own flourishes on top, but keep this base so cuts match.
 */
export const enterExit = (frame: number, duration: number, overlap: number, { enter = true, exit = true } = {}) => {
  const i = enter ? interpolate(frame, [0, overlap], [0, 1], { ...clamp, easing: easeOut }) : 1;
  const o = exit ? interpolate(frame, [duration - 6, duration + overlap], [0, 1], { ...clamp, easing: easeIn }) : 0;
  return {
    opacity: i * (1 - o),
    scale: mix(0.94, 1, i) * mix(1, 1.07, o),
    blur: (1 - i) * 10 + o * 8,
    /** 0 → 1 entry progress, and 0 → 1 exit progress. */
    inP: i,
    outP: o,
  };
};
