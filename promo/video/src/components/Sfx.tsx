// Sound effects (synthesised by audio/make_music.py into public/audio/sfx/).
import { Audio } from "@remotion/media";
import React from "react";
import { Internals, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { TIMELINES } from "../timeline";

export type SfxName = "click" | "whoosh" | "whoosh-soft" | "impact" | "riser" | "tick" | "pop" | "swipe" | "shimmer";

/** Gain of every effect between lines, and under the voice (keeps the VO clearly on top of the bed). */
const GAIN = 0.8;
const GAIN_UNDER_VOICE = 0.32;

/** Effect gain at absolute frame `f`: eases down while a voice line is speaking. */
const duck = (f: number) => {
  let g = GAIN;
  for (const s of TIMELINES.en.scenes) {
    const a = s.vo.at;
    const b = s.vo.speechEnd;
    const d = interpolate(f, [a - 6, a + 4, b, b + 10], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    g = Math.min(g, GAIN - (GAIN - GAIN_UNDER_VOICE) * d);
  }
  return g;
};

/** Plays `name` starting at local frame `at`. */
export const Sfx: React.FC<{ name: SfxName; at: number; volume?: number }> = ({ name, at, volume = 0.7 }) => {
  const { fps } = useVideoConfig();
  const local = useCurrentFrame();
  const abs = Internals.useTimelinePosition();
  const from = Math.round(at);
  const origin = abs - local + from; // absolute frame at which the effect starts
  return <Audio src={staticFile(`audio/sfx/${name}.wav`)} from={from} premountFor={fps} volume={(f) => volume * duck(origin + f)} />;
};
