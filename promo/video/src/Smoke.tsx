// Toolchain smoke test: the real racket model in WebGL + captured site footage in a
// 3D browser window + cursor. Not part of the ad.
import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { Backdrop } from "./components/Backdrop";
import { Browser3D, Space3D } from "./components/Browser3D";
import { Cursor } from "./components/Cursor";
import { Footage, footageCursor } from "./components/Footage";
import { HERO_SLUG, RacketModel, RacketStage } from "./components/Racket3D";
import { Kinetic } from "./components/Kinetic";
import { loadFonts } from "./fonts";

loadFonts();

export const Smoke: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const cur = footageCursor("test-drag", frame);
  return (
    <AbsoluteFill>
      <Backdrop />
      <Space3D>
        <Browser3D x={-260} y={20} rotateY={18 - frame * 0.08} rotateX={6} scale={0.62} path="/rackets/nox-at10-luxury-genius-18k-alum">
          <Footage name="test-drag" frame={frame} />
          {cur && <Cursor x={cur.x} y={cur.y} down={cur.down} grab={cur.down} frame={frame} />}
        </Browser3D>
      </Space3D>
      <RacketStage width={width} height={height} cameraPosition={[0, 0, 1.6]}>
        <RacketModel slug={HERO_SLUG} position={[0.42, 0, 0]} rotation={[0.1, frame * 0.03, -0.12]} />
      </RacketStage>
      <AbsoluteFill style={{ padding: 90 }}>
        <Kinetic text="Every padel racket, in 3D." frame={frame} at={0} size={80} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
