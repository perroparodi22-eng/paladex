import React from "react";
import { Composition } from "remotion";
import { Launch, type LaunchProps } from "./Launch";
import { Smoke } from "./Smoke";
import { TIMELINES } from "./timeline";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="PaladexLaunch"
        component={Launch}
        width={1920}
        height={1080}
        fps={60}
        durationInFrames={TIMELINES.en.durationInFrames}
        defaultProps={{ lang: "en", subtitles: true, music: true } satisfies LaunchProps}
      />
      <Composition id="Smoke" component={Smoke} width={1920} height={1080} fps={60} durationInFrames={90} />
    </>
  );
};
