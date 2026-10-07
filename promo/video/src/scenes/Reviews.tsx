// Placeholder for the "reviews" scene; replaced by the real scene.
import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Kinetic } from "../components/Kinetic";
import { enterExit } from "../lib/motion";
import type { SceneProps } from "./types";

export const Reviews: React.FC<SceneProps> = ({ timing, timeline }) => {
  const frame = useCurrentFrame();
  const env = enterExit(frame, timing.duration, timeline.overlapFrames);
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: env.opacity }}>
      <Kinetic text="reviews" frame={frame} at={0} align="center" />
    </AbsoluteFill>
  );
};
