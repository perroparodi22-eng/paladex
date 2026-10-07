// Placeholder for the "brands" scene; replaced by the real scene.
import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Kinetic } from "../components/Kinetic";
import type { SceneProps } from "./types";

export const Brands: React.FC<SceneProps> = ({ timing }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <Kinetic text="brands" frame={frame} at={0} outAt={timing.duration - 10} align="center" />
    </AbsoluteFill>
  );
};
