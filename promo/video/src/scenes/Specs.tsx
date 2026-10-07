// Scene 5, "specs" (v2.1): "Every spec, translated into what it means for your game.
// No jargon. Just how it feels on court."
//
// The hero racket's real page, tilted back in 3D, shows its Specification list (the 3D
// viewer stays sticky on the left, as on the site). Rows with no published value
// (Balance, Thickness, Hardness) are cut out of the page strip and the list closes up,
// so only real values and real explanations are ever in frame.
//   "translated"  Shape and Weight lift off the page; on "means" the Surface row flies
//                 up to face the camera ("Grips the ball for more spin…").
//   "No jargon"   the Shape row comes to centre: the term ("Teardrop") dims on "jargon"
//                 and its plain-language explanation lights up line by line.
//   "Just how it feels on court"  a band of light walks down the explanation lines.
//   then the row sinks back, the cursor presses "Show on model" on the Sweet spot row and
//   the page's own viewer (captured footage) glides to the front view with its sweet-spot
//   overlay while the camera pushes in.
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
const WORDS = { spec: "spec", lift: "translated", hero: "means", end: "game", no: "No", jargon: "jargon", just: "Just" };
const SNAP = 1.5; // the page viewer glides this much faster than captured

const PAGE_W = 1920;
const PAGE_H = 1080;
const WIN_CY = (PAGE_H + CHROME_H) / 2; // window centre, in window px from its top
const K = 2.6; // slabs are authored K× larger, scaled down (sharp when close)

const lift = Easing.bezier(0.33, 0, 0.12, 1); // soft take-off, long settle
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const sink = Easing.bezier(0.55, 0, 0.25, 1);

type Rect = { x: number; y: number; w: number; h: number };

// Page strip pieces (document y). The rows between them hold no published value
// (Balance + Thickness, then Hardness) and are cut out; the list closes up.
const CUT1 = { from: 3723, to: 3852 };
const CUT2 = { from: 4130, to: 4180 };
const mapY = (y: number) => (y < CUT1.from ? y : y < CUT2.from ? y - (CUT1.to - CUT1.from) : y - (CUT1.to - CUT1.from) - (CUT2.to - CUT2.from));

// Text lines of the Shape row crop (crop px): the term, then its seven explanation lines.
const SHAPE_TERM: [number, number] = [18, 47];
const SHAPE_LINES: [number, number][] = [
  [51, 69],
  [73, 92],
  [94, 113],
  [115, 134],
  [136, 155],
  [157, 176],
  [178, 197],
];
const RGBA = (a: number) => `rgba(11,11,12,${a})`;


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
    const c = s.marks!.crop;
    return { key: k, file: s.file, crop: { ...c, y: mapY(c.y) } };
  });

  // --- Beats (synced to the voice) -------------------------------------------
  const A = wordAt(timing, WORDS.spec, 39);
  const B = wordAt(timing, WORDS.lift, 57);
  const C = wordAt(timing, WORDS.hero, 123);
  const G = wordAt(timing, WORDS.end, 164, 0, "end");
  const N = wordAt(timing, WORDS.no, 182);
  const J = wordAt(timing, WORDS.jargon, 199);
  const JT = wordAt(timing, WORDS.just, 243);
  const heroFrom = C - 50; // the Surface row starts its flight…
  const heroTo = C + 4; // …and settles facing the camera on "means"
  const rowAt = [B, B + 9];
  const sinkAt = G - 4; // Surface and Weight return as "game" ends; Shape takes the stage
  const hlStep = 8; // one explanation line lights up every 8 frames, from "Just"
  const retStart = JT + 7 * hlStep + 2; // Shape returns to its row
  const retEnd = retStart + 30;
  const clickAt = retEnd - 4; // "Show on model" on the Sweet spot row

  // --- Page scroll (document y at the top of the viewport) --------------------
  // The clean list is one viewport tall: the scroll only drifts. Never past the strip's end.
  const maxScroll = S0 + page.height - (CUT1.to - CUT1.from) - (CUT2.to - CUT2.from) - PAGE_H;
  const scroll = monotone([-12, B, sinkAt, D + 60], [3040, 3085, 3112, maxScroll], frame);

  // --- Camera on the page (Browser3D pose) -----------------------------------
  const keys: PoseKey[] = [
    { f: -18, x: -60, y: 160, z: -520, rotateX: 32, rotateY: -30, rotateZ: 3, scale: 1 },
    { f: A + 8, x: -350, y: 40, z: -230, rotateX: 18, rotateY: -18, rotateZ: 1.2, scale: 1 },
    { f: B + 24, x: -380, y: 110, z: -380, rotateX: 26, rotateY: -16, rotateZ: 0.6, scale: 1 },
    { f: B + 52, x: -300, y: 70, z: -260, rotateX: 20, rotateY: -6, rotateZ: -0.8, scale: 1 },
    { f: C + 6, x: -360, y: 120, z: -560, rotateX: 28, rotateY: -13, rotateZ: 0, scale: 1 },
    { f: N + 10, x: -230, y: 60, z: -470, rotateX: 22, rotateY: -8, rotateZ: 0.4, scale: 1 },
    { f: JT + 20, x: -120, y: 20, z: -380, rotateX: 16, rotateY: 0, rotateZ: -0.3, scale: 1 },
    { f: retEnd - 6, x: 30, y: -110, z: -200, rotateX: 10, rotateY: 8, rotateZ: -0.5, scale: 0.9 },
    { f: clickAt + 18, x: 130, y: -100, z: -110, rotateX: 8, rotateY: 10, rotateZ: -0.6, scale: 0.92 },
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
  // In-place rise for Shape and Weight; Surface flies to the hero pose; Shape later
  // glides on to centre stage (focusP) for "No jargon".
  const retP = interpolate(frame, [retStart, retEnd], [0, 1], { ...clamp, easing: easeInOut });
  const riseP = (i: number) =>
    interpolate(frame, [rowAt[i], rowAt[i] + 30], [0, 1], { ...clamp, easing: lift }) *
    (1 - (i === 0 ? retP : interpolate(frame, [sinkAt + 2 + i * 4, sinkAt + 28 + i * 4], [0, 1], { ...clamp, easing: sink })));
  const heroP =
    interpolate(frame, [heroFrom, heroTo], [0, 1], { ...clamp, easing: lift }) *
    (1 - interpolate(frame, [sinkAt, sinkAt + 30], [0, 1], { ...clamp, easing: easeInOut }));
  const heroOut = frame > sinkAt; // returning (affects the arc only)
  // How far the other rows step back while the hero is up.
  const heroHold = interpolate(frame, [heroFrom, heroTo], [0, 1], { ...clamp, easing: lift }) * (1 - interpolate(frame, [sinkAt - 6, sinkAt + 24], [0, 1], { ...clamp, easing: easeInOut }));
  // Shape on centre stage.
  const focusIn = interpolate(frame, [sinkAt - 6, N + 22], [0, 1], { ...clamp, easing: lift });
  const focusHold = focusIn * (1 - retP);

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
  // Shape's centre-stage pose: facing the camera, a slow yaw and push while the lines light up.
  const focusPose: FullPose = {
    x: drift("sp-fx", frame, 10, 0.1),
    y: -30 + drift("sp-fy", frame, 6, 0.1),
    z: interpolate(frame, [N, retStart], [-20, 90], clamp),
    rotateX: 2 + drift("sp-frx", frame, 0.8, 0.08),
    rotateY: interpolate(frame, [N, retStart], [-7, 5], clamp),
    rotateZ: drift("sp-frz", frame, 0.3, 0.08),
    scale: interpolate(frame, [N, retStart], [2.15, 2.4], clamp),
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
      if (r.key === "shape") {
        const focus: SlabState = { P: focusPose, cx: 0, cy: 0, lz: 0, lrx: 0, lry: 0, ls: 1 };
        const st = mixSlab(mixSlab(mixSlab(slot, up, interpolate(frame, [rowAt[0], rowAt[0] + 30], [0, 1], { ...clamp, easing: lift })), focus, focusIn), slot, retP);
        // (the in-plane rise above is used as is: p only drives the shadow)
        return { ...r, state: st, p: Math.max(p, focusHold), on: presence(rowAt[0], retEnd), focus: 1 - heroHold * 0.55, blur: heroHold * 3 };
      }
      const on = presence(rowAt[i], sinkAt + 28 + i * 4);
      return { ...r, state: mixSlab(slot, up, p), p, on, focus: 1 - heroHold * 0.55, blur: heroHold * 3 };
    }
    const hero: SlabState = { P: heroPose, cx: 0, cy: 0, lz: 0, lrx: 0, lry: 0, ls: 1 };
    const st = mixSlab(slot, hero, heroP);
    // Arc: rise off the page before flying to the camera (and settle back into the slot).
    st.lz += Math.sin(Math.PI * heroP) * (heroOut ? 120 : 220);
    return { ...r, state: st, p: heroP, on: presence(heroFrom, sinkAt + 30), focus: 1, blur: 0 };
  });

  // --- Shape row: the term dims, the explanation lights up line by line ----------
  // glide to centre: all explanation lines dimmed, the term bright; on "jargon" the term
  // dims and each line lights up in turn; from "Just" a band of light walks down the lines.
  const glideDim = interpolate(frame, [sinkAt, N + 12], [0, 1], clamp);
  const termDim = 0.55 * interpolate(frame, [J, J + 16], [0, 1], clamp);
  const lineDim = SHAPE_LINES.map((_, i) => {
    const reveal = interpolate(frame, [J + 4 + i * 6, J + 18 + i * 6], [0, 1], clamp);
    const dim = 0.62 * glideDim * (1 - reveal);
    const t = JT + i * hlStep;
    const near = clamp01(1 - Math.abs(frame - t - 2) / 13);
    const hl = 0.4 * interpolate(frame, [JT - 8, JT + 2], [0, 1], clamp) * (1 - near * near * (3 - 2 * near));
    return Math.max(dim, hl) * (1 - retP);
  });

  // --- Page treatment ---------------------------------------------------------
  const veil =
    (interpolate(frame, [B, B + 40], [0, 0.18], clamp) + interpolate(frame, [heroFrom, heroTo], [0, 0.2], clamp) * (1 - interpolate(frame, [sinkAt, sinkAt + 30], [0, 1], { ...clamp, easing: easeInOut }))) *
    (1 - interpolate(frame, [retStart, retEnd + 4], [0, 1], { ...clamp, easing: easeInOut }));
  const pageBlur = heroHold * 2.2 + focusHold * 0.9;

  // Viewer footage: the captured click lands on our click frame.
  // Before the click the viewer holds its idle hero pose (capture frames 0–39 are
  // identical); the first 6 are skipped as a warm-up in case a re-capture differs.
  const viewerFrame = Math.max(7, clipClick + (frame - clickAt) * (frame > clickAt ? SNAP : 1));

  // Cursor (page px, glued to the page).
  const btn = { ...M.sweetBtn, y: mapY(M.sweetBtn.y) };
  const bx = btn.x + btn.w / 2 + 4;
  const by = btn.y - scroll + btn.h / 2 + 3;
  const cur = cursorAt(
    [
      { f: retStart + 2, x: 1770, y: 1010 },
      { f: clickAt - 3, x: bx, y: by },
      { f: clickAt, x: bx, y: by, down: true },
      { f: clickAt + 6, x: bx, y: by },
      { f: D + 40, x: bx + 70, y: by + 46 },
    ],
    frame,
  );
  const curOpacity = interpolate(frame, [retStart + 2, retStart + 10], [0, 1], clamp);
  const hoverOn = interpolate(frame, [clickAt - 9, clickAt - 5], [0, 1], clamp);

  // Page strip pieces, closed up.
  const segs: [number, number][] = [
    [S0, CUT1.from],
    [CUT1.to, CUT2.from],
    [CUT2.to, S0 + page.height],
  ];

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: env.blur > 0.01 ? `blur(${env.blur}px)` : undefined }}>
      <Space3D style={{ filter: pageBlur > 0.01 ? `blur(${pageBlur}px)` : undefined }}>
        <Browser3D {...cam} path="/rackets/nox-at10-luxury-genius-18k-alum" glare={0.9}>
          {/* Page strip, scrolled, without the rows that have no published value. */}
          {segs.map(([a, b]) => (
            <div key={a} style={{ position: "absolute", left: 0, top: mapY(a) - scroll, width: PAGE_W, height: b - a, overflow: "hidden" }}>
              <Img src={staticFile(page.file)} style={{ position: "absolute", left: 0, top: 0, width: page.width, height: page.height, translate: `0px ${S0 - a}px` }} />
            </div>
          ))}
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
            style={{ position: "absolute", left: hover.marks!.crop.x, top: mapY(hover.marks!.crop.y) - scroll, width: hover.width, height: hover.height, opacity: hoverOn }}
          />
          {/* Sticky 3D viewer (captured footage). */}
          <Footage name="specs-viewer" frame={viewerFrame} style={{ left: viewer.x, top: viewer.y, width: viewer.w, height: viewer.h }} />
          {/* Sticky site header. */}
          <Img src={staticFile(still("specs-header").file)} style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 64 }} />
          <AbsoluteFill style={{ background: "#050607", opacity: veil }} />
          <Cursor x={cur.x} y={cur.y} down={cur.down} clicks={[clickAt]} frame={frame} opacity={curOpacity} />
        </Browser3D>
      </Space3D>

      {/* A soft pool of light behind the lifted row, separating it from the dimmed page. */}
      <AbsoluteFill
        style={{
          background: "radial-gradient(ellipse 42% 30% at 50% 40%, rgba(236,238,241,0.075) 0%, rgba(236,238,241,0.025) 45%, rgba(7,8,9,0) 75%)",
          opacity: Math.max(heroHold, focusHold),
        }}
      />
      {/* Rows lifted out of the page (same perspective as the page's space). */}
      <Space3D>
        {slabs.map((s) => {
          if (s.on <= 0.001) return null;
          const w = s.crop.w;
          const h = s.crop.h;
          const glint = interpolate(s.p, [0, 1], [-40, 140]);
          const isShape = s.key === "shape";
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
                {isShape && (
                  <>
                    <div style={{ position: "absolute", left: 0, right: 0, top: SHAPE_TERM[0] * K, height: (SHAPE_TERM[1] - SHAPE_TERM[0]) * K, background: RGBA(termDim * (1 - retP)) }} />
                    {SHAPE_LINES.map(([y0, y1], i) => (
                      <div key={i} style={{ position: "absolute", left: 0, right: 0, top: y0 * K, height: (y1 - y0) * K, background: RGBA(lineDim[i]) }} />
                    ))}
                  </>
                )}
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

      <Sfx name="whoosh" at={0} volume={0.5} />
      <Sfx name="swipe" at={A + 4} volume={0.35} />
      <Sfx name="tick" at={rowAt[0] + 3} volume={0.4} />
      <Sfx name="tick" at={rowAt[1] + 3} volume={0.36} />
      <Sfx name="whoosh-soft" at={heroFrom - 2} volume={0.45} />
      <Sfx name="impact" at={heroTo} volume={0.6} />
      <Sfx name="shimmer" at={heroTo + 8} volume={0.3} />
      <Sfx name="swipe" at={sinkAt + 2} volume={0.4} />
      <Sfx name="whoosh-soft" at={N - 2} volume={0.35} />
      <Sfx name="pop" at={J} volume={0.45} />
      {SHAPE_LINES.map((_, i) => (
        <Sfx key={i} name="tick" at={JT + i * hlStep} volume={0.22} />
      ))}
      <Sfx name="swipe" at={retStart + 2} volume={0.35} />
      <Sfx name="click" at={clickAt} volume={0.6} />
      <Sfx name="pop" at={clickAt + 6} volume={0.4} />
      <Sfx name="whoosh-soft" at={clickAt + 14} volume={0.3} />
    </AbsoluteFill>
  );
};
