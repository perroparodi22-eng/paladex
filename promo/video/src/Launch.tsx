// The Paladex launch ad: eight scenes on the 120 BPM beat grid, voiceover per
// scene, a music bed ducked under the voice, sound effects and subtitles.
import { Audio } from "@remotion/media";
import React from "react";
import { AbsoluteFill, Sequence, interpolate, staticFile, useVideoConfig } from "remotion";
import { Backdrop } from "./components/Backdrop";
import { isAudioOnly } from "./components/Racket3D";
import { Captions } from "./components/Captions";
import { scene, TIMELINES, type Lang, type SceneId, type Timeline } from "./timeline";
import { Brands } from "./scenes/Brands";
import { ColdOpen } from "./scenes/ColdOpen";
import { EndCard } from "./scenes/EndCard";
import { Finder } from "./scenes/Finder";
import { Problem } from "./scenes/Problem";
import { Reveal } from "./scenes/Reveal";
import { Specs } from "./scenes/Specs";
import { Turn } from "./scenes/Turn";
import { loadFonts } from "./fonts";

loadFonts();

export type LaunchProps = {
  lang: Lang;
  subtitles: boolean;
  music: boolean;
};

/** Music volume: full between lines, ducked under the voice. */
const musicVolume = (t: Timeline, f: number) => {
  const BASE = 0.62;
  const DUCK = 0.3;
  let v = BASE;
  for (const s of t.scenes) {
    const a = s.vo.at;
    const b = s.vo.speechEnd;
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
  return (
    <AbsoluteFill style={{ backgroundColor: "#070809" }}>
      {/* Soundtrack-only renders (scripts/render-audio.mjs) hide the picture so the
          browser paints nothing; the scenes still mount, so their SFX still play. */}
      <AbsoluteFill style={isAudioOnly() ? { display: "none" } : undefined}>
        <Backdrop />
        <Sequence name="1 Cold open" from={s("cold-open").start} durationInFrames={s("cold-open").duration + ov} premountFor={fps}>
          <ColdOpen timing={s("cold-open")} timeline={t} lang={lang} />
        </Sequence>
        <Sequence name="2 Problem" from={s("problem").start} durationInFrames={s("problem").duration + ov} premountFor={fps}>
          <Problem timing={s("problem")} timeline={t} lang={lang} />
        </Sequence>
        <Sequence name="3 Reveal" from={s("reveal").start} durationInFrames={s("reveal").duration + ov} premountFor={fps}>
          <Reveal timing={s("reveal")} timeline={t} lang={lang} />
        </Sequence>
        <Sequence name="4 Turn" from={s("turn").start} durationInFrames={s("turn").duration + ov} premountFor={fps}>
          <Turn timing={s("turn")} timeline={t} lang={lang} />
        </Sequence>
        <Sequence name="5 Specs" from={s("specs").start} durationInFrames={s("specs").duration + ov} premountFor={fps}>
          <Specs timing={s("specs")} timeline={t} lang={lang} />
        </Sequence>
        <Sequence name="6 Finder" from={s("finder").start} durationInFrames={s("finder").duration + ov} premountFor={fps}>
          <Finder timing={s("finder")} timeline={t} lang={lang} />
        </Sequence>
        <Sequence name="7 Brands" from={s("brands").start} durationInFrames={s("brands").duration + ov} premountFor={fps}>
          <Brands timing={s("brands")} timeline={t} lang={lang} />
        </Sequence>
        <Sequence name="8 End card" from={s("endcard").start} durationInFrames={s("endcard").duration} premountFor={fps}>
          <EndCard timing={s("endcard")} timeline={t} lang={lang} />
        </Sequence>

        {subtitles && <Captions timeline={t} />}
      </AbsoluteFill>

      {t.scenes.map((sc) => (
        <Audio key={sc.id} name={`Voice: ${sc.id}`} src={staticFile(sc.vo.file)} from={sc.vo.at} premountFor={fps} volume={1} />
      ))}
      {music && <Audio name="Music" src={staticFile(`audio/music.${lang}.wav`)} premountFor={fps} volume={(f) => musicVolume(t, f)} />}
    </AbsoluteFill>
  );
};
