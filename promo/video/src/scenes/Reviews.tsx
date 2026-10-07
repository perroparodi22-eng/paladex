// Scene 6, "reviews": "What the reviewers say, summed up, with the sources."
//
// The hero racket's real page (same page as the Specs scene, so it arrives fast),
// tilted in 3D and scrolled to its "What reviewers say" section. Real crops of the
// section lift out one after another, each facing the camera large and crisp:
//   "What"      the section title
//   "reviewers" the reviewers' summary paragraph
//   "say"       what testers like / watch out for
//   "summed up" Paladex's read (the site's own one-line summary, labelled as opinion)
//   "sources"   the Sources links (Padel Kiwi, Padelgids) land; the cursor hovers each
// Everything is a real capture (capture/shots/reviews.mjs); nothing is invented.
import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { Browser3D, CHROME_H, Space3D } from "../components/Browser3D";
import { Cursor, cursorAt } from "../components/Cursor";
import { Footage, still } from "../components/Footage";
import { Sfx } from "../components/Sfx";
import { clamp, drift, easeIn, easeInOut, enterExit } from "../lib/motion";
import { wordAt } from "../timeline";
import { mixSlab, monotone, poseAt, slabTransform, type FullPose, type PoseKey, type SlabState } from "./specs/rig";
import type { SceneProps } from "./types";

const PAGE_W = 1920;
const PAGE_H = 1080;
const WIN_CY = (PAGE_H + CHROME_H) / 2;
const K = 2.6; // slabs are authored K× larger and scaled down (sharp when close)

const cw = (p: { key: string; w: number }) => (p.key === "sources" ? p.w * 0.47 : p.w);
const lift = Easing.bezier(0.2, 0, 0.1, 1); // quick take-off, soft settle
const sink = Easing.bezier(0.6, 0, 0.3, 1);

type Rect = { x: number; y: number; w: number; h: number };
type Piece = {
  key: string;
  still: string;
  take: number; // take-off frame (at its slot)
  land: number; // settled facing the camera
  back: number; // starts sinking back
  home: number; // back in its slot
  scale: number;
  rotY: number;
  rotX: number;
  y: number;
};

export const Reviews: React.FC<SceneProps> = ({ timing, timeline }) => {
  const frame = useCurrentFrame();
  const D = timing.duration;
  const OV = timeline.overlapFrames;
  const env = enterExit(frame, D, OV);

  const page = still("reviews-page");
  const M = page.marks as Record<string, Rect>;
  const S0 = M.scroll.y;
  const viewer = M.viewer;

  // --- Beats (voice) ----------------------------------------------------------
  // Three long beats, one card at a time (each readable 1+ s), every card in its own 3D context so
  // two planes can never slice through each other:
  //   "What the reviewers say, summed up"  the summary paragraph (a highlight sweeps it on "summed up")
  //   "The good, the bad"                   the two lists: green column on "good", red one on "bad"
  //   "with the sources to back it"         the Sources card; the cursor opens each link
  const wWhat = wordAt(timing, "What", 14);
  const wSummed = Math.max(wordAt(timing, "summed", 72), wWhat + 40);
  const wGood = Math.max(wordAt(timing, "good", 122), wSummed + 40);
  const wBad = Math.max(wordAt(timing, "bad", 148), wGood + 20);
  const wWith = Math.max(wordAt(timing, "with", 166), wBad + 14);
  const wSources = Math.max(wordAt(timing, "sources", 186, 0, "end"), wWith + 14);
  const wBack = Math.max(wordAt(timing, "back", 214), wSources + 20);

  const pieces: Piece[] = [
    { key: "summary", still: "reviews-crop-summary", take: wWhat - 6, land: wWhat + 14, back: wGood - 22, home: wGood - 4, scale: 2.6, rotY: 6, rotX: 2, y: -40 },
    { key: "lists", still: "reviews-crop-lists", take: wGood - 20, land: wGood + 2, back: wWith - 12, home: wWith + 6, scale: 2.55, rotY: -6, rotX: 3, y: -30 },
    { key: "sources", still: "reviews-crop-sources", take: wWith - 8, land: wWith + 14, back: D + 200, home: D + 220, scale: 3.9, rotY: -4, rotX: 2, y: 20 },
  ];
  const crops = pieces.map((p) => {
    const s = still(p.still);
    return { ...p, file: s.file, crop: s.marks!.crop, w: s.marks!.crop.w, h: s.marks!.crop.h };
  });

  // --- Page scroll -------------------------------------------------------------
  const S2 = M.scroll.h;
  const scroll = monotone([-10, wWhat + 20, wGood, wWith + 20, D + 60], [S0 + 10, S0 + 60, S0 + 130, S2 - 4, S2], frame);

  // --- Page camera -----------------------------------------------------------
  const keys: PoseKey[] = [
    { f: -20, x: 40, y: 140, z: -420, rotateX: 30, rotateY: -32, rotateZ: 4, scale: 1 },
    { f: wWhat + 10, x: -330, y: 40, z: -90, rotateX: 18, rotateY: -20, rotateZ: 1.5, scale: 1 },
    { f: wSummed, x: -380, y: 90, z: -140, rotateX: 22, rotateY: -15, rotateZ: 0.4, scale: 1 },
    { f: wGood + 20, x: -300, y: 110, z: -190, rotateX: 26, rotateY: -12, rotateZ: -0.4, scale: 1 },
    { f: wWith + 20, x: -120, y: 60, z: -110, rotateX: 18, rotateY: -6, rotateZ: -0.6, scale: 1 },
    { f: D + 18, x: 200, y: 20, z: -80, rotateX: 8, rotateY: 8, rotateZ: -1, scale: 1 },
    { f: D + 120, x: 420, y: 0, z: 200, rotateX: 4, rotateY: 12, rotateZ: -1.2, scale: 1 },
  ];
  const base = poseAt(keys, frame);
  const cam: FullPose = {
    ...base,
    x: base.x + drift("rv-x", frame, 8, 0.1),
    y: base.y + drift("rv-y", frame, 6, 0.09),
    rotateX: base.rotateX + drift("rv-rx", frame, 0.5, 0.08),
    rotateY: base.rotateY + drift("rv-ry", frame, 0.6, 0.07),
  };

  // --- Slabs -------------------------------------------------------------------
  const slotState = (crop: Rect): SlabState => ({
    P: cam,
    cx: crop.x + crop.w / 2 - PAGE_W / 2,
    cy: crop.y - scroll + crop.h / 2 + CHROME_H - WIN_CY,
    lz: 0.5,
    lrx: 0,
    lry: 0,
    ls: 1,
  });
  const anyUp = (f: number) => crops.reduce((m, p) => Math.max(m, interpolate(f, [p.take, p.land], [0, 1], { ...clamp, easing: lift }) * (1 - interpolate(f, [p.back, p.home], [0, 1], { ...clamp, easing: sink }))), 0);
  const hold = anyUp(frame);

  const slabs = crops.map((p, i) => {
    const up = interpolate(frame, [p.take, p.land], [0, 1], { ...clamp, easing: lift });
    const down = interpolate(frame, [p.back, p.home], [0, 1], { ...clamp, easing: sink });
    const t = up * (1 - down);
    const dir = i % 2 === 0 ? -1 : 1;
    const yOff = 0;
    const push = p.key === "sources" ? interpolate(frame, [wSources - 6, D + 40], [1, 1.1], { ...clamp, easing: lift }) : 1;
    const hero: SlabState = {
      P: {
        x: drift(`rv-hx${i}`, frame, 12, 0.1) + dir * interpolate(frame, [p.land, p.back], [-14, 14], clamp),
        y: p.y + yOff + drift(`rv-hy${i}`, frame, 7, 0.1),
        z: interpolate(frame, [p.land, p.back], [0, 70], clamp),
        rotateX: p.rotX + drift(`rv-hrx${i}`, frame, 0.8, 0.08),
        rotateY: interpolate(frame, [p.take, p.back], [p.rotY * 2.4, p.rotY * -0.4], clamp) + drift(`rv-hry${i}`, frame, 1, 0.08),
        rotateZ: drift(`rv-hrz${i}`, frame, 0.35, 0.08),
        scale: interpolate(frame, [p.take, p.back], [p.scale * 0.9, p.scale * 1.06], clamp) * push,
      },
      cx: 0,
      cy: 0,
      lz: 0,
      lrx: 0,
      lry: 0,
      ls: 1,
    };
    const slot = slotState(p.crop);
    const st = mixSlab(slot, hero, t);
    // rise off the page along an arc before flying to the camera
    st.lz += Math.sin(Math.PI * t) * (down > 0 ? 110 : 200);
    const on = interpolate(frame, [p.take - 6, p.take, p.home, p.home + 6], [0, 1, 1, 0], clamp);
    return { ...p, state: st, t, on, glint: interpolate(t, [0, 1], [-40, 140]) };
  });

  // --- Sources interaction (cursor + hover crops inside the sources slab) ----------
  const src = crops[2];
  const lk = [M.link0, M.link1];
  const hoverAt = [wSources, wBack];
  const hoverOp = hoverAt.map((h, i) => {
    const next = hoverAt[i + 1];
    return interpolate(frame, [h - 3, h, ...(next ? [next - 3, next] : [h + 400, h + 401])], [0, 1, ...(next ? [1, 0] : [1, 1])], clamp);
  });
  const pt = (i: number) => ({ x: lk[i].x - src.crop.x + lk[i].w / 2, y: lk[i].y - src.crop.y + lk[i].h / 2 });
  const cur = cursorAt(
    [
      { f: wWith + 4, x: src.w * 0.5, y: src.h + 60 },
      { f: hoverAt[0] - 2, x: pt(0).x + 8, y: pt(0).y + 16 },
      { f: hoverAt[0] + 8, x: pt(0).x + 8, y: pt(0).y + 16 },
      { f: hoverAt[1] - 2, x: pt(1).x + 8, y: pt(1).y + 16 },
      { f: D + 60, x: pt(1).x + 14, y: pt(1).y + 16 },
    ],
    frame,
  );
  const curOp = interpolate(frame, [wWith + 4, wWith + 14], [0, 1], clamp);

  // --- Page treatment ---------------------------------------------------------
  const veil = interpolate(hold, [0, 1], [0, 0.1]);
  const pageBlur = hold * 1.2;
  const poolOp = hold;

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: env.blur > 0.01 ? `blur(${env.blur}px)` : undefined }}>
      <Space3D style={{ filter: pageBlur > 0.01 ? `blur(${pageBlur}px)` : undefined }}>
        <Browser3D {...cam} path="/rackets/nox-at10-luxury-genius-18k-alum" glare={0.9}>
          <Img src={staticFile(page.file)} style={{ position: "absolute", left: 0, top: 0, width: page.width, height: page.height, translate: `0px ${S0 - scroll}px` }} />
          {slabs.map((s) => (
            <div
              key={`slot-${s.key}`}
              style={{
                position: "absolute",
                left: s.crop.x,
                top: s.crop.y - scroll,
                width: s.crop.w,
                height: s.crop.h,
                borderRadius: 10,
                background: `rgba(3,4,5,${0.9 * s.on * s.on})`,
                boxShadow: `inset 0 14px 30px rgba(0,0,0,${0.7 * s.t})`,
              }}
            />
          ))}
          {/* Keep the sample "Platform scores" block below the section out of frame. */}
          <div style={{ position: "absolute", left: 0, top: M.sources.y + M.sources.h + 12 - scroll, width: 1920, height: 1400, background: "linear-gradient(180deg, rgba(8,9,11,0) 0, rgba(8,9,11,1) 16px)" }} />
          <Footage name="reviews-viewer" frame={frame} style={{ left: viewer.x, top: viewer.y, width: viewer.w, height: viewer.h }} />
          <Img src={staticFile(still("reviews-header").file)} style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 64 }} />
          <AbsoluteFill style={{ background: "#050607", opacity: veil }} />
        </Browser3D>
      </Space3D>

      <AbsoluteFill
        style={{
          background: "radial-gradient(ellipse 46% 32% at 50% 42%, rgba(236,238,241,0.085) 0%, rgba(236,238,241,0.03) 45%, rgba(7,8,9,0) 75%)",
          opacity: poolOp,
        }}
      />

      {slabs.map((s) => {
          if (s.on <= 0.001) return null;
          const isSrc = s.key === "sources";
          return (
            <Space3D key={s.key} style={{ translate: `${interpolate(frame, [D - 14, D + 18], [0, 420], { ...clamp, easing: easeIn })}px 0px`, rotate: `${interpolate(frame, [D - 14, D + 18], [0, -2], { ...clamp, easing: easeIn })}deg` }}>
            <div
              style={{
                position: "absolute",
                left: "50%",
                top: "50%",
                width: cw(s) * K,
                height: s.h * K,
                transformOrigin: "0 0",
                transform: slabTransform(s.state, cw(s), s.h, K),
                opacity: s.on,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  borderRadius: 12 * K,
                  overflow: "hidden",
                  boxShadow: `0 ${34 * K * s.t}px ${80 * K * s.t}px rgba(0,0,0,${0.75 * s.t}), 0 0 0 ${1.2 * K}px rgba(255,255,255,${0.1 * s.t}), inset 0 ${1.2 * K}px 0 rgba(255,255,255,${0.12 * s.t})`,
                  background: "#0a0b0d",
                }}
              >
                <Img src={staticFile(s.file)} style={{ position: "absolute", left: 0, top: 0, width: s.w * K, height: s.h * K, maxWidth: "none" }} />
                {s.key === "summary" && (
                  <div style={{ position: "absolute", left: 0, right: 0, top: `${interpolate(frame, [wSummed - 4, wSummed + 34], [-20, 110], clamp)}%`, height: "22%", background: "linear-gradient(180deg, rgba(236,238,241,0), rgba(236,238,241,0.13) 50%, rgba(236,238,241,0))", opacity: interpolate(frame, [wSummed - 4, wSummed + 4, wSummed + 28, wSummed + 36], [0, 1, 1, 0], clamp) }} />
                )}
                {s.key === "lists" && (
                  <>
                    <div style={{ position: "absolute", left: 0, top: 0, width: "50%", height: "100%", background: "#0a0b0d", opacity: interpolate(frame, [wGood + 28, wBad - 4], [0, 0.62], clamp) * interpolate(frame, [wBad + 24, wBad + 40], [1, 0], clamp) }} />
                    <div style={{ position: "absolute", right: 0, top: 0, width: "50%", height: "100%", background: "#0a0b0d", opacity: interpolate(frame, [wGood - 20, wGood - 6], [0, 0.62], clamp) * interpolate(frame, [wGood + 22, wGood + 34], [1, 0], clamp) }} />
                  </>
                )}
                {isSrc && (
                  <div style={{ position: "absolute", left: 0, top: 0, width: s.w, height: s.h, transformOrigin: "0 0", scale: `${K}` }}>
                    {lk.map((l, i) => (
                      <div
                        key={i}
                        style={{
                          position: "absolute",
                          left: l.x - src.crop.x,
                          top: l.y - src.crop.y,
                          width: l.w,
                          height: l.h,
                          borderRadius: 18,
                          border: "1.5px solid rgba(236,238,241,0.6)",
                          boxSizing: "border-box",
                          background: "rgba(236,238,241,0.07)",
                          opacity: hoverOp[i],
                        }}
                      />
                    ))}
                    <Cursor x={cur.x} y={cur.y} frame={frame} opacity={curOp} scale={1.1} />
                  </div>
                )}
                <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, rgba(255,255,255,${0.05 * s.t}) 0%, rgba(255,255,255,0) 50%)`, mixBlendMode: "screen" }} />
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    background: `linear-gradient(105deg, rgba(255,255,255,0) ${s.glint - 24}%, rgba(255,255,255,${0.07 * s.t}) ${s.glint}%, rgba(255,255,255,0) ${s.glint + 18}%)`,
                    mixBlendMode: "screen",
                  }}
                />
              </div>
            </div>
            </Space3D>
          );
        })}

      <Sfx name="whoosh-soft" at={0} volume={0.35} />
      {crops.map((p, i) => (
        <React.Fragment key={p.key}>
          <Sfx name={i % 2 === 0 ? "swipe" : "whoosh-soft"} at={p.take + 4} volume={0.4} />
          <Sfx name="tick" at={p.land} volume={0.45} />
        </React.Fragment>
      ))}
      <Sfx name="tick" at={wGood} volume={0.4} />
      <Sfx name="tick" at={wBad} volume={0.4} />
      <Sfx name="pop" at={hoverAt[0]} volume={0.5} />
      <Sfx name="pop" at={hoverAt[1]} volume={0.45} />
      <Sfx name="click" at={wBack} volume={0.5} />
    </AbsoluteFill>
  );
};
