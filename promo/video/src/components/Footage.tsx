// Real site footage captured frame-by-frame at 60 fps (capture/*.mjs), and full-page
// stills. Each scene owns a manifest fragment in src/data/capture/<scene>.json
// (written by capture/cdp.mjs writeManifest); they are merged here.
import React from "react";
import { Img, staticFile } from "remotion";
import brands from "../data/capture/brands.json";
import coldOpen from "../data/capture/cold-open.json";
import endcard from "../data/capture/endcard.json";
import finder from "../data/capture/finder.json";
import problem from "../data/capture/problem.json";
import reveal from "../data/capture/reveal.json";
import shared from "../data/capture/shared.json";
import specs from "../data/capture/specs.json";
import turn from "../data/capture/turn.json";

export type ClipInfo = {
  dir: string;
  frames: number;
  fps: number;
  width: number;
  height: number;
  dpr: number;
  /** Per-frame cursor [x, y, down(0|1)] in page CSS px, as scripted during capture. */
  cursor?: [number, number, number][];
  /** Notable moments (clicks etc.) by capture frame. */
  events?: { type: string; frame: number; x: number; y: number; label?: string }[];
};
export type StillInfo = { file: string; width: number; height: number; dpr: number; marks?: Record<string, { x: number; y: number; w: number; h: number }> };

type Manifest = { clips: Record<string, ClipInfo>; stills: Record<string, StillInfo> };
const parts = [shared, coldOpen, problem, reveal, turn, specs, finder, brands, endcard] as unknown as Manifest[];
const M: Manifest = { clips: Object.assign({}, ...parts.map((p) => p.clips)), stills: Object.assign({}, ...parts.map((p) => p.stills)) };

export const clip = (name: string): ClipInfo => {
  const c = M.clips[name];
  if (!c) throw new Error(`No captured clip "${name}" in src/data/capture/*.json`);
  return c;
};
export const still = (name: string): StillInfo => {
  const s = M.stills[name];
  if (!s) throw new Error(`No captured still "${name}" in src/data/capture/*.json`);
  return s;
};

/** Capture frame index for a local frame (holds the first/last frame outside the clip). */
export const clipIndex = (name: string, localFrame: number, rate = 1) => {
  const c = clip(name);
  return Math.max(0, Math.min(c.frames - 1, Math.floor(localFrame * rate)));
};

/**
 * Plays a captured clip. `frame` is the caller's local frame (0 = first clip
 * frame). Rendered at the page's CSS size so it fills <Browser3D>'s content box.
 */
export const Footage: React.FC<{ name: string; frame: number; rate?: number; style?: React.CSSProperties }> = ({ name, frame, rate = 1, style }) => {
  const c = clip(name);
  const i = clipIndex(name, frame, rate);
  return (
    <Img
      src={staticFile(`${c.dir}/f${String(i).padStart(5, "0")}.jpg`)}
      style={{ position: "absolute", left: 0, top: 0, width: c.width, height: c.height, display: "block", ...style }}
    />
  );
};

/** The cursor that was scripted during capture, for the same local frame. */
export const footageCursor = (name: string, frame: number, rate = 1) => {
  const c = clip(name);
  const t = c.cursor?.[clipIndex(name, frame, rate)];
  return t ? { x: t[0], y: t[1], down: t[2] === 1 } : null;
};

/**
 * A full-page still (captured at `dpr`), shown at CSS size and scrolled by
 * `scrollY` CSS px. Use inside <Browser3D> for smooth, frame-driven scrolling.
 */
export const PageStill: React.FC<{ name: string; scrollY?: number; style?: React.CSSProperties }> = ({ name, scrollY = 0, style }) => {
  const s = still(name);
  return (
    <Img
      src={staticFile(s.file)}
      style={{ position: "absolute", left: 0, top: 0, width: s.width, height: s.height, translate: `0px ${-scrollY}px`, display: "block", ...style }}
    />
  );
};
