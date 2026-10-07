// Isolated preview of ONE scene (backdrop + scene + subtitles), so each scene can be
// bundled and rendered on its own. Frame 0 = the scene's own frame 0.
import { Audio } from "@remotion/media";
import React from "react";
import { AbsoluteFill, Composition, Sequence, staticFile } from "remotion";
import { Backdrop } from "../components/Backdrop";
import { Captions } from "../components/Captions";
import { loadFonts } from "../fonts";
import type { SceneProps } from "../scenes/types";
import { scene, TIMELINES, type Lang, type SceneId } from "../timeline";

loadFonts();

type DevProps = { lang: Lang; subtitles: boolean };

export const makeDevRoot = (id: SceneId, C: React.FC<SceneProps>) => {
  const Dev: React.FC<DevProps> = ({ lang, subtitles }) => {
    const t = TIMELINES[lang];
    const s = scene(t, id);
    return (
      <AbsoluteFill style={{ backgroundColor: "#070809" }}>
        <Backdrop />
        <C timing={s} timeline={t} lang={lang} />
        {/* Subtitles and voice need absolute frames: shift by the scene start. */}
        <Sequence from={-s.start} layout="none">
          {subtitles && <Captions timeline={t} />}
          <Audio src={staticFile(s.vo.file)} from={s.vo.at} />
        </Sequence>
      </AbsoluteFill>
    );
  };
  const Root: React.FC = () => (
    <>
      <Composition
        id="Dev"
        component={Dev}
        width={1920}
        height={1080}
        fps={60}
        durationInFrames={scene(TIMELINES.en, id).duration + TIMELINES.en.overlapFrames}
        defaultProps={{ lang: "en", subtitles: true } satisfies DevProps}
        calculateMetadata={({ props }) => ({ durationInFrames: scene(TIMELINES[props.lang], id).duration + TIMELINES[props.lang].overlapFrames })}
      />
    </>
  );
  return Root;
};
