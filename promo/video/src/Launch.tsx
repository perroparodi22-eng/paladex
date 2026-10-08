// The Paladex launch ad: the timeline's scenes on the 120 BPM beat grid, voiceover per
// scene, a music bed ducked under the voice, sound effects and subtitles.
import { Audio } from "@remotion/media";
import React from "react";
import { AbsoluteFill, Sequence, getInputProps, interpolate, staticFile, useVideoConfig } from "remotion";
import { Backdrop } from "./components/Backdrop";
import { isAudioOnly } from "./components/Racket3D";
import { Captions } from "./components/Captions";
import { scene, TIMELINES, type Lang, type SceneId, type Timeline } from "./timeline";
import { Brands } from "./scenes/Brands";
import { ColdOpen } from "./scenes/ColdOpen";
import { EndCard } from "./scenes/EndCard";
import { Finder } from "./scenes/Finder";
import { Problem } from "./scenes/Problem";
import { Pros } from "./scenes/Pros";
import { Reveal } from "./scenes/Reveal";
import { Reviews } from "./scenes/Reviews";
import { Specs } from "./scenes/Specs";
import { Turn } from "./scenes/Turn";
import type { SceneProps } from "./scenes/types";
import { loadFonts } from "./fonts";

loadFonts();

/** Scenes in story order (timing comes from the timeline by id). */
const SCENES: [SceneId, React.FC<SceneProps>][] = [
  ["cold-open", ColdOpen],
  ["problem", Problem],
  ["reveal", Reveal],
  ["turn", Turn],
  ["specs", Specs],
  ["reviews", Reviews],
  ["pros", Pros],
  ["finder", Finder],
  ["brands", Brands],
  ["endcard", EndCard],
];

export type LaunchProps = {
  lang: Lang;
  subtitles: boolean;
  music: boolean;
};

/** Frames to shift the narrator against the picture (+ = later); music and SFX stay on the visual hits.
 *  Set per render with the `voOffset` input prop (scripts/render-audio.mjs reads VO_OFFSET). */
const voOffset = () => Number((getInputProps() as { voOffset?: number }).voOffset ?? 0);

/** Music volume: full between lines, ducked under the voice. */
const musicVolume = (t: Timeline, f: number) => {
  const BASE = 0.62;
  const DUCK = 0.24;
  let v = BASE;
  for (const s of t.scenes) {
    const a = s.vo.at + voOffset();
    const b = s.vo.speechEnd + voOffset();
    const d = interpolate(f, [a - 10, a, b, b + 14], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    v = Math.min(v, BASE - (BASE - DUCK) * d);
  }
  return v;
};

export const Launch: React.FC<LaunchProps> = ({ lang, subtitles, music }) => {
  const { fps } = useVideoConfig();
  const t = TIMELINES[lang];
  const ov = t.overlapFrames;
  const s = (id: SceneId) => scene(t, id);
  // A cut can leave scenes out (the short v3 drops reviews and pros): play only those in the timeline.
  const playing = SCENES.filter(([id]) => t.scenes.some((x) => x.id === id));
  return (
    <AbsoluteFill style={{ backgroundColor: "#070809" }}>
      {/* Soundtrack-only renders (scripts/render-audio.mjs) hide the picture so the
          browser paints nothing; the scenes still mount, so their SFX still play. */}
      <AbsoluteFill style={isAudioOnly() ? { display: "none" } : undefined}>
        <Backdrop />
        {playing.map(([id, Scene], i) => {
          const sc = s(id);
          const last = i === playing.length - 1;
          return (
            <Sequence key={id} name={`${i + 1} ${id}`} from={sc.start} durationInFrames={sc.duration + (last ? 0 : ov)} premountFor={fps}>
              <Scene timing={sc} timeline={t} lang={lang} />
            </Sequence>
          );
        })}

        {subtitles && <Captions timeline={t} />}
      </AbsoluteFill>

      {t.scenes.map((sc) => (
        <Audio key={sc.id} name={`Voice: ${sc.id}`} src={staticFile(sc.vo.file)} from={sc.vo.at + voOffset()} premountFor={fps} volume={1} />
      ))}
      {music && <Audio name="Music" src={staticFile(`audio/music.${lang}.wav`)} premountFor={fps} volume={(f) => musicVolume(t, f)} />}
    </AbsoluteFill>
  );
};
