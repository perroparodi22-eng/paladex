// Sound effects (synthesised by audio/make_music.py into public/audio/sfx/).
import { Audio } from "@remotion/media";
import React from "react";
import { staticFile, useVideoConfig } from "remotion";

export type SfxName = "click" | "whoosh" | "whoosh-soft" | "impact" | "riser" | "tick" | "pop" | "swipe" | "shimmer";

/** Plays `name` starting at local frame `at`. */
export const Sfx: React.FC<{ name: SfxName; at: number; volume?: number }> = ({ name, at, volume = 0.7 }) => {
  const { fps } = useVideoConfig();
  return <Audio src={staticFile(`audio/sfx/${name}.wav`)} from={Math.round(at)} premountFor={fps} volume={volume} />;
};
