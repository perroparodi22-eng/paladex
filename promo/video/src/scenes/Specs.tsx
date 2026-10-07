// Scene 5, "specs": "Every spec is translated into what it actually means for your game."
//
// The hero racket's real page, tilted back in 3D, scrolls into its Specification
// section (the 3D viewer stays sticky on the left, as on the site). On "translated"
// real rows (dpr-3 crops) lift off the page one after another; on "means for your
// game" the Surface row ("Grips the ball for more spin…") floats up to face the
// camera, large and crisp. The rows sink back, the cursor presses "Show on model"
// on the Sweet spot row and the page's own viewer (captured footage) glides to the
// front view with its ball-lime sweet-spot overlay while the camera pushes in.
//
// Layers rebuilt from real captures (capture/shots/specs.mjs): page strip with the
// sticky header/viewer hidden, the header, the viewer clip, row crops, a hover crop.
import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { Browser3D, CHROME_H, Space3D } from "../components/Browser3D";
import { Cursor, cursorAt } from "../components/Cursor";
import { Footage, clip, still } from "../components/Footage";
import { Sfx } from "../components/Sfx";
import { clamp, drift, easeInOut, enterExit } from "../lib/motion";
import { wordAt } from "../timeline";
import { mixSlab, monotone, poseAt, slabTransform, type FullPose, type PoseKey, type SlabState } from "./specs/rig";
import type { SceneProps } from "./types";

// Words each beat syncs to (scene-local frames come from the voice timing).
const WORDS = { spec: "spec", lift: "translated", hero: "means", end: "game" };

const PAGE_W = 1920;
const PAGE_H = 1080;
const WIN_CY = (PAGE_H + CHROME_H) / 2; // window centre, in window px from its top
const K = 2.6; // slabs are authored K× larger, scaled down (sharp when close)

const lift = Easing.bezier(0.33, 0, 0.12, 1); // soft take-off, long settle
const sink = Easing.bezier(0.55, 0, 0.25, 1);

type Rect = { x: number; y: number; w: number; h: number };



export const Specs: React.FC<SceneProps> = ({ timing, timeline }) => {
  const frame = useCurrentFrame();
  const D = timing.duration;
  const OV = timeline.overlapFrames;
  const env = enterExit(frame, D, OV);

  // --- Captures -------------------------------------------------------------
  const page = still("specs-page");
  const M = page.marks as Record<string, Rect>;
  const S0 = M.scroll.y; // document y of the strip's top
  const viewer = M.viewer; // sticky card, viewport coords
  const vclip = clip("specs-viewer");
  const clipClick = vclip.events?.find((e) => e.type === "click")?.frame ?? 40;
  const hover = still("specs-sweet-hover");
  const rows = (["shape", "weight", "surface"] as const).map((k) => {
    const s = still(`specs-row-${k}`);
    return { key: k, file: s.file, crop: s.marks!.crop };
  });

  // --- Beats (synced to the voice) -------------------------------------------
  const A = wordAt(timing, WORDS.spec, 37);
  const B = wordAt(timing, WORDS.lift, 81);
  const C = wordAt(timing, WORDS.hero, 172);
  const G = wordAt(timing, WORDS.end, 200, 0, "end");
  const heroFrom = C - 40; // the Surface row starts its flight…
  const heroTo = C + 6; // …and settles facing the camera on "means"
  const rowAt = [B, Math.max(B + 8, B + (heroFrom - B) * 0.45)];
  const sinkAt = Math.max(G + 6, C + 56); // rows return after the line
  const clickAt = sinkAt + 44; // "Show on model" on the Sweet spot row

  // --- Page scroll (document y at the top of the viewport) --------------------
  // Never past S2 (marks.scroll.h): the strip ends exactly one viewport below it.
  const S2 = M.scroll.h;
  const scroll = monotone([-12, A, B - 4, C, sinkAt, clickAt - 6, D + 60], [S0, 2870, 3270, 3290, 3300, S2 - 6, S2], frame);

  // --- Camera on the page (Browser3D pose) -----------------------------------
  const keys: PoseKey[] = [
    { f: -20, x: -60, y: 160, z: -520, rotateX: 32, rotateY: -30, rotateZ: 3, scale: 1 },
    { f: A + 24, x: -350, y: 40, z: -230, rotateX: 18, rotateY: -18, rotateZ: 1.2, scale: 1 },
    { f: B + 36, x: -380, y: 110, z: -380, rotateX: 26, rotateY: -16, rotateZ: 0.6, scale: 1 },
    { f: C + 10, x: -360, y: 120, z: -560, rotateX: 28, rotateY: -13, rotateZ: 0, scale: 1 },
    { f: sinkAt + 36, x: 30, y: -110, z: -200, rotateX: 10, rotateY: 8, rotateZ: -0.5, scale: 0.9 },
    { f: clickAt + 24, x: 130, y: -100, z: -110, rotateX: 8, rotateY: 10, rotateZ: -0.6, scale: 0.92 },
    { f: D + 18, x: 420, y: -40, z: 240, rotateX: 5, rotateY: 15, rotateZ: -1, scale: 1 },
    { f: D + 120, x: 520, y: -40, z: 420, rotateX: 4, rotateY: 16, rotateZ: -1.2, scale: 1 },
  ];
  const base = poseAt(keys, frame);
  const cam: FullPose = {
    ...base,
    x: base.x + drift("sp-x", frame, 8, 0.1),
    y: base.y + drift("sp-y", frame, 6, 0.09),
    rotateX: base.rotateX + drift("sp-rx", frame, 0.5, 0.08),
    rotateY: base.rotateY + drift("sp-ry", frame, 0.6, 0.07),
  };

  // --- Lifts -----------------------------------------------------------------
  // In-place rise for Shape and Weight; Surface flies to the hero pose.
  const riseP = (i: number) =>
    interpolate(frame, [rowAt[i], rowAt[i] + 44], [0, 1], { ...clamp, easing: lift }) *
    (1 - interpolate(frame, [sinkAt + 4 + i * 6, sinkAt + 38 + i * 6], [0, 1], { ...clamp, easing: sink }));
  const heroP =
    interpolate(frame, [heroFrom, heroTo], [0, 1], { ...clamp, easing: lift }) *
    (1 - interpolate(frame, [sinkAt, sinkAt + 40], [0, 1], { ...clamp, easing: easeInOut }));
  const heroOut = frame > sinkAt; // returning (affects the arc only)
  // How far the other rows step back while the hero is up.
  const heroHold = interpolate(frame, [heroFrom, heroTo], [0, 1], { ...clamp, easing: lift }) * (1 - interpolate(frame, [sinkAt - 6, sinkAt + 24], [0, 1], { ...clamp, easing: easeInOut }));

  const slotState = (crop: Rect): SlabState => ({
    P: cam,
    cx: crop.x + crop.w / 2 - PAGE_W / 2,
    cy: crop.y - scroll + crop.h / 2 + CHROME_H - WIN_CY,
    lz: 0.5,
    lrx: 0,
    lry: 0,
    ls: 1,
  });
  // Where Shape / Weight float while lifted (still in the page's plane).
  const spread = [
    { dx: -10, dy: 40 },
    { dx: 20, dy: 185 },
  ];
  const heroPose: FullPose = {
    x: drift("sp-hx", frame, 10, 0.1),
    y: -120 + drift("sp-hy", frame, 6, 0.1),
    z: interpolate(frame, [heroTo, sinkAt], [0, 50], clamp),
    rotateX: 3 + drift("sp-hrx", frame, 0.8, 0.08),
    rotateY: interpolate(frame, [heroFrom, sinkAt], [-9, 3], clamp),
    rotateZ: drift("sp-hrz", frame, 0.3, 0.08),
    scale: interpolate(frame, [heroFrom + 20, sinkAt], [2.5, 2.85], clamp),
  };

  // A slab only appears or disappears while it sits exactly on its own row: it
  // fades in over the 6 frames BEFORE its take-off (still at p = 0, pixel-aligned
  // with the row) and fades out just AFTER it has landed. Its slot is recessed for
  // the same span, so the slab is fully opaque and its row fully covered by the
  // time it moves: a row never shows twice and nothing pops (the crops have no
  // page texture behind them).
  const presence = (takeOff: number, landed: number) => interpolate(frame, [takeOff - 6, takeOff, landed, landed + 6], [0, 1, 1, 0], clamp);

  const slabs = rows.map((r, i) => {
    const slot = slotState(r.crop);
    if (r.key !== "surface") {
      const p = riseP(i);
      const up: SlabState = {
        ...slot,
        cx: slot.cx + spread[i].dx,
        cy: slot.cy + spread[i].dy,
        lz: 260 - heroHold * 60,
        lrx: -0.8 * cam.rotateX,
        lry: -0.5 * cam.rotateY,
        ls: 1.38,
      };
      const on = presence(rowAt[i], sinkAt + 38 + i * 6);
      return { ...r, state: mixSlab(slot, up, p), p, on, focus: 1 - heroHold * 0.55, blur: heroHold * 3 };
    }
    const hero: SlabState = { P: heroPose, cx: 0, cy: 0, lz: 0, lrx: 0, lry: 0, ls: 1 };
    const st = mixSlab(slot, hero, heroP);
    // Arc: rise off the page before flying to the camera (and settle back into the slot).
    st.lz += Math.sin(Math.PI * heroP) * (heroOut ? 120 : 220);
    return { ...r, state: st, p: heroP, on: presence(heroFrom, sinkAt + 40), focus: 1, blur: 0 };
  });

  // --- Page treatment ---------------------------------------------------------
  const veil =
    (interpolate(frame, [B, B + 40], [0, 0.3], clamp) + interpolate(frame, [heroFrom, heroTo], [0, 0.2], clamp)) *
    (1 - interpolate(frame, [sinkAt, sinkAt + 34], [0, 1], { ...clamp, easing: easeInOut }));
  const pageBlur = heroHold * 2.2;

  // Viewer footage: the captured click lands on our click frame.
  // Before the click the viewer holds its idle hero pose (capture frames 0–39 are
  // identical); the first 6 are skipped as a warm-up in case a re-capture differs.
  const viewerFrame = Math.max(7, frame - clickAt + clipClick);

  // Cursor (page px, glued to the page).
  const btn = M.sweetBtn;
  const bx = btn.x + btn.w / 2 + 4;
  const by = btn.y - scroll + btn.h / 2 + 3;
  const cur = cursorAt(
    [
      { f: sinkAt + 6, x: 1770, y: 1010 },
      { f: clickAt - 3, x: bx, y: by },
      { f: clickAt, x: bx, y: by, down: true },
      { f: clickAt + 6, x: bx, y: by },
      { f: D + 40, x: bx + 70, y: by + 46 },
    ],
    frame,
  );
  const curOpacity = interpolate(frame, [sinkAt + 6, sinkAt + 18], [0, 1], clamp);
  const hoverOn = interpolate(frame, [clickAt - 9, clickAt - 5], [0, 1], clamp);

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: env.blur > 0.01 ? `blur(${env.blur}px)` : undefined }}>
      <Space3D style={{ filter: pageBlur > 0.01 ? `blur(${pageBlur}px)` : undefined }}>
        <Browser3D {...cam} path="/rackets/nox-at10-luxury-genius-18k-alum" glare={0.9}>
          {/* Page strip (document y S0 …), scrolled. */}
          <Img
            src={staticFile(page.file)}
            style={{ position: "absolute", left: 0, top: 0, width: page.width, height: page.height, translate: `0px ${S0 - scroll}px` }}
          />
          {/* Slots left behind by the lifted rows. */}
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
                background: `rgba(3,4,5,${0.88 * s.on * s.on})`,
                boxShadow: `inset 0 0 0 1px rgba(255,255,255,${0.05 * s.p}), inset 0 14px 30px rgba(0,0,0,${0.7 * s.p})`,
              }}
            />
          ))}
          {/* Hover state of the Sweet spot "Show on model" button. */}
          <Img
            src={staticFile(hover.file)}
            style={{ position: "absolute", left: hover.marks!.crop.x, top: hover.marks!.crop.y - scroll, width: hover.width, height: hover.height, opacity: hoverOn }}
          />
          {/* Sticky 3D viewer (captured footage). */}
          <Footage name="specs-viewer" frame={viewerFrame} style={{ left: viewer.x, top: viewer.y, width: viewer.w, height: viewer.h }} />
          {/* Sticky site header. */}
          <Img src={staticFile(still("specs-header").file)} style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 64 }} />
          <AbsoluteFill style={{ background: "#050607", opacity: veil }} />
          <Cursor x={cur.x} y={cur.y} down={cur.down} clicks={[clickAt]} frame={frame} opacity={curOpacity} />
        </Browser3D>
      </Space3D>

      {/* A soft pool of light behind the hero row, separating it from the dimmed page. */}
      <AbsoluteFill
        style={{
          background: "radial-gradient(ellipse 42% 30% at 50% 40%, rgba(236,238,241,0.075) 0%, rgba(236,238,241,0.025) 45%, rgba(7,8,9,0) 75%)",
          opacity: heroHold,
        }}
      />
      {/* Rows lifted out of the page (same perspective as the page's space). */}
      <Space3D>
        {slabs.map((s) => {
          if (s.on <= 0.001) return null;
          const w = s.crop.w;
          const h = s.crop.h;
          const glint = interpolate(s.p, [0, 1], [-40, 140]);
          return (
            <div
              key={s.key}
              style={{
                position: "absolute",
                left: "50%",
                top: "50%",
                width: w * K,
                height: h * K,
                transformOrigin: "0 0",
                transform: slabTransform(s.state, w, h, K),
                // Opaque from the start (at p = 0 it covers its own row exactly);
                // rows behind the hero fall back by dimming and defocusing, not fading.
                filter: s.blur > 0.05 || s.focus < 0.999 ? `brightness(${s.focus}) blur(${s.blur * K}px)` : undefined,
                opacity: s.on,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  borderRadius: 12 * K,
                  overflow: "hidden",
                  boxShadow: `0 ${34 * K * s.p}px ${80 * K * s.p}px rgba(0,0,0,${0.75 * s.p}), 0 0 0 ${1.2 * K}px rgba(255,255,255,${0.1 * s.p}), inset 0 ${1.2 * K}px 0 rgba(255,255,255,${0.12 * s.p})`,
                  background: "#0a0b0d",
                }}
              >
                <Img src={staticFile(s.file)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />
                {/* Key light from above: the slab's top catches a little more light. */}
                <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, rgba(255,255,255,${0.05 * s.p}) 0%, rgba(255,255,255,0) 50%)`, mixBlendMode: "screen" }} />
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    background: `linear-gradient(105deg, rgba(255,255,255,0) ${glint - 24}%, rgba(255,255,255,${0.07 * s.p}) ${glint}%, rgba(255,255,255,0) ${glint + 18}%)`,
                    mixBlendMode: "screen",
                  }}
                />
              </div>
            </div>
          );
        })}
      </Space3D>

      <Sfx name="whoosh-soft" at={0} volume={0.3} />
      <Sfx name="tick" at={rowAt[0] + 4} volume={0.3} />
      <Sfx name="tick" at={rowAt[1] + 4} volume={0.26} />
      <Sfx name="swipe" at={heroFrom + 6} volume={0.4} />
      <Sfx name="whoosh-soft" at={sinkAt + 2} volume={0.25} />
      <Sfx name="click" at={clickAt} volume={0.55} />
      <Sfx name="shimmer" at={clickAt + 8} volume={0.3} />
    </AbsoluteFill>
  );
};
