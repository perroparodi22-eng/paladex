// Scene 6, "finder": "Not sure where to start? Answer a few quick questions, and see
// the rackets that fit how you really play."
//
// Camera language: a fly-through of a deck. The real "Find my racket" flow, as a
// stack of cards in depth (captured dpr-2 stills of the live site):
//   cover  = the home page's "Not sure where to start?" card (Start with your level),
//   q2..q8 = the quiz's question cards (Question 2 of 8 … 8 of 8).
// The camera orbits onto the deck while the voice asks the question; on "Answer"
// the cursor taps Intermediate → Balanced → Control (each answered card is tossed
// past the camera as the next one comes forward), the rest of the deck riffles past
// with the answers lit, and on "see" the cursor hits "See my matches": the last card
// pushes through the lens and the real results page (60 fps footage, the 3D racket
// turning on the site's own clock) comes forward out of the depth. On "fit" the
// match score lifts off the page; the camera then orbits toward "Why it fits".
import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { Browser3D, CHROME_H, Space3D, poseTransform, type Pose } from "../components/Browser3D";
import { Cursor, cursorAt, type CursorKey } from "../components/Cursor";
import { Footage, still } from "../components/Footage";
import { Sfx } from "../components/Sfx";
import { clamp, drift, easeInOut, easeOut, enterExit, mix } from "../lib/motion";
import { C } from "../theme";
import { wordAt } from "../timeline";
import type { SceneProps } from "./types";

// ---------------------------------------------------------------------------
// Voice anchors (scene-local frames come from the word timings).
const WORDS = { answer: "Answer", see: "see", fit: "fit", how: "how", play: "play" } as const;

// ---------------------------------------------------------------------------
// The deck. `target` is the option the cursor taps (a key of the still's marks).
type CardDef = {
  base: string;
  hover?: string;
  selected?: string;
  /** Corner radius of the card on the site, CSS px. */
  radius: number;
  /** Display scale at the front slot (cards are laid out at display size, so they rasterise 1:1). */
  scale: number;
  target?: string;
  /** Click point inside the target box (0–1), so the pointer lands on the label. */
  aim?: [number, number];
  /** Where the card goes once answered. */
  fly: { sx: number; sy: number; rx: number; ry: number; rz: number; z?: number; fade?: [number, number] };
};

const UP_LEFT = { sx: -1, sy: -0.55, rx: -10, ry: -26, rz: -7 };
const UP_RIGHT = { sx: 1, sy: -0.55, rx: -10, ry: 26, rz: 7 };
// Rapid-fire answers: each card flips up and away like a page, fading fast so it never smothers the next one.
const RIFFLE = { sx: -0.08, sy: -1.3, rx: -55, ry: -4, rz: -2, z: 260, fade: [0.18, 0.62] as [number, number] };

const CARDS: CardDef[] = [
  { base: "finder-cover", hover: "finder-cover-hover", radius: 32, scale: 1.08, target: "intermediate", aim: [0.42, 0.5], fly: UP_LEFT },
  {
    base: "finder-q2",
    hover: "finder-q2-hover",
    selected: "finder-q2-selected",
    radius: 36,
    scale: 1.18,
    target: "Balanced",
    aim: [0.32, 0.38],
    fly: UP_RIGHT,
  },
  { base: "finder-q3", hover: "finder-q3-hover", selected: "finder-q3-selected", radius: 36, scale: 1.18, target: "Control", aim: [0.3, 0.42], fly: UP_LEFT },
  { base: "finder-q4", selected: "finder-q4-selected", radius: 36, scale: 1.18, target: "Teardrop", aim: [0.32, 0.5], fly: RIFFLE },
  { base: "finder-q5", selected: "finder-q5-selected", radius: 36, scale: 1.18, target: "Medium", aim: [0.3, 0.42], fly: RIFFLE },
  { base: "finder-q6", selected: "finder-q6-selected", radius: 36, scale: 1.18, target: "No limit", aim: [0.3, 0.5], fly: RIFFLE },
  { base: "finder-q7", selected: "finder-q7-selected", radius: 36, scale: 1.18, target: "No", aim: [0.35, 0.45], fly: RIFFLE },
  // "See my matches": the last card pushes straight through the lens.
  {
    base: "finder-q8",
    hover: "finder-q8-hover",
    radius: 36,
    scale: 1.18,
    target: "see",
    aim: [0.4, 0.5],
    // Gone within ~6 frames of leaving, so it never double-exposes over the results coming in behind it.
    fly: { sx: 0, sy: -0.12, rx: -6, ry: 0, rz: 0, z: 2000, fade: [0.06, 0.3] },
  },
];

/** Centre of the front slot relative to the frame centre (kept clear of the subtitles). */
const SLOT_Y = -48;
const RESULTS = "finder-results";
const RESULTS_SCALE = 0.76;

const cardSize = (d: CardDef) => {
  const s = still(d.base);
  return { w: s.width * d.scale, h: s.height * d.scale };
};

/** Click point of a card's target in slot space (px from the slot centre). */
const aimOf = (d: CardDef) => {
  const s = still(d.base);
  const m = s.marks?.[d.target ?? ""];
  if (!m) return { x: 0, y: 0 };
  const [ax, ay] = d.aim ?? [0.5, 0.5];
  return { x: (m.x + m.w * ax - s.width / 2) * d.scale, y: (m.y + m.h * ay - s.height / 2) * d.scale };
};

// ---------------------------------------------------------------------------

export const Finder: React.FC<SceneProps> = ({ timing, timeline }) => {
  const frame = useCurrentFrame();
  const D = timing.duration;
  const OV = timeline.overlapFrames;
  const w = WORDS;

  // Beats (all derived from the voice).
  const A = wordAt(timing, w.answer, 100);
  const S = wordAt(timing, w.see, 213);
  const F = wordAt(timing, w.fit, 267);
  const H = wordAt(timing, w.how, 295);
  const W = wordAt(timing, w.play, H + 33) + 8; // after the last word: the camera cranes down to the matches
  const c1 = A + 6; // Intermediate (home card)
  const gap = Math.round(Math.max(20, Math.min(30, (S - c1 - 60) / 2)));
  const c2 = c1 + gap; // Balanced
  const c3 = c2 + gap; // Control
  // Questions 4–7 are answered in a rapid-fire riffle locked to the music's
  // 8th-note triplets (scenes start on the beat): every 10 frames a 7-frame flick,
  // then a 3-frame rest where the next card sits sharp and gets its tap.
  const TRIPLET = timeline.beatFrames / 3;
  const FLICK = 7;
  const rs0 = Math.min(Math.ceil((c3 + 3) / TRIPLET) * TRIPLET, S - 6 - 4 * TRIPLET - FLICK);
  const rs = [0, 1, 2, 3, 4].map((i) => rs0 + i * TRIPLET); // flick i sends card 2+i away
  const R0 = rs0;
  const R1 = rs[4] + FLICK; // question 8 settled
  const taps = [1, 2, 3, 4].map((i) => rs[i] - 2); // Teardrop, Medium, No limit, No (cards 3–6)
  const c4 = S; // See my matches

  // Deck position: 0 = cover in the slot … 7 = question 8 in the slot, 8 = all gone.
  const flick = Easing.bezier(0.55, 0, 0.2, 1);
  const deckP = (f: number) =>
    interpolate(f, [c1 + 4, c1 + 22], [0, 1], { ...clamp, easing: easeInOut }) +
    interpolate(f, [c2 + 4, c2 + 22], [0, 1], { ...clamp, easing: easeInOut }) +
    rs.reduce((acc, r) => acc + interpolate(f, [r, r + FLICK], [0, 1], { ...clamp, easing: flick }), 0) +
    interpolate(f, [c4 + 3, c4 + 21], [0, 1], { ...clamp, easing: Easing.bezier(0.55, 0, 1, 0.45) });
  const p = deckP(frame);
  const pPrev = deckP(frame - 1);

  // ---- Camera on the deck: orbit in from a three-quarter view, then square up.
  const est = interpolate(frame, [0, c1 + 6], [0, 1], { ...clamp, easing: Easing.bezier(0.36, 0.06, 0.24, 1) });
  const riffleT = interpolate(frame, [R0, R1], [0, 1], clamp);
  const surge = Math.sin(Math.PI * riffleT);
  const cam = {
    x: mix(-260, 0, est),
    y: mix(190, 0, est),
    z: mix(-1050, 0, est) + Math.min(frame, S) * 0.4 + surge * 90, // plus a slow, constant dolly-in
    rx: mix(-15, -2.5, est) + drift("fd-rx", frame, 0.9, 0.07),
    ry: mix(-38, 4.5, est) + drift("fd-ry", frame, 1.3, 0.06) - surge * 2,
    rz: mix(3, 0, est) + surge * 1.2 + drift("fd-rz", frame, 0.35, 0.05),
  };

  // ---- Cursor (slot space).
  const aims = CARDS.map(aimOf);
  const exit = { x: aims[7].x + 300, y: aims[7].y + 260 };
  // Rapid taps: settle a beat before, press, release (the card flicks away under it).
  const tapKeys = (t: number, a: { x: number; y: number }): CursorKey[] => [
    { f: t - 2, ...a },
    { f: t - 0.5, ...a, down: true },
    { f: t + 1.5, ...a },
  ];
  const keys: CursorKey[] = [
    { f: A - 40, x: 760, y: 420 },
    { f: c1 - 6, ...aims[0] },
    { f: c1 - 1, ...aims[0], down: true },
    { f: c1 + 3, ...aims[0] },
    { f: c1 + 8, ...aims[0] },
    { f: c2 - 6, ...aims[1] },
    { f: c2 - 1, ...aims[1], down: true },
    { f: c2 + 3, ...aims[1] },
    { f: c2 + 8, ...aims[1] },
    { f: c3 - 6, ...aims[2] },
    { f: c3 - 1, ...aims[2], down: true },
    { f: c3 + 3, ...aims[2] },
    ...taps.flatMap((t, i) => tapKeys(t, aims[3 + i])),
    { f: c4 - 7, ...aims[7] },
    { f: c4 - 1, ...aims[7], down: true },
    { f: c4 + 3, ...aims[7] },
    { f: c4 + 30, ...exit },
  ];
  const cur = cursorAt(keys, frame);
  const curOpacity = interpolate(frame, [A - 40, A - 26], [0, 1], { ...clamp, easing: easeOut }) * interpolate(frame, [c4 + 4, c4 + 14], [1, 0], clamp);
  const clicks = [c1, c2, c3, ...taps, c4];

  // Hover / selected states (the site's own), timed to the cursor.
  const hoverOf = (k: number) => {
    const c = [c1, c2, c3, -1, -1, -1, -1, c4][k];
    return c < 0 ? 0 : interpolate(frame, [c - 11, c - 4], [0, 1], { ...clamp, easing: easeOut });
  };
  const selectedOf = (k: number) => {
    if (k === 1) return interpolate(frame, [c2, c2 + 3], [0, 1], clamp);
    if (k === 2) return interpolate(frame, [c3, c3 + 3], [0, 1], clamp);
    if (k >= 3 && k <= 6) return interpolate(frame, [taps[k - 3], taps[k - 3] + 2], [0, 1], clamp);
    return 0;
  };

  // ---- Results: come forward out of the depth on "see", settle on "fit", then
  // a slow orbit toward "Why it fits" for "how you really play".
  const rStart = c4 + 2;
  const rIn = interpolate(frame, [rStart, F + 6], [0, 1], { ...clamp, easing: Easing.bezier(0.18, 0.72, 0.24, 1) });
  const rCam = interpolate(frame, [F, D + OV], [0, 1], { ...clamp, easing: Easing.bezier(0.42, 0, 0.36, 1) });
  const toReasons = interpolate(frame, [H - 20, D + OV], [0, 1], { ...clamp, easing: Easing.bezier(0.45, 0, 0.3, 1) });
  const crane = interpolate(frame, [W - 16, D + OV], [0, 1], { ...clamp, easing: Easing.bezier(0.45, 0, 0.3, 1) });
  const rPose: Pose = {
    x: mix(220, 70, rIn) - 150 * toReasons + 110 * crane,
    y: mix(-150, SLOT_Y + 2, rIn) + 10 * rCam - 140 * crane,
    z: mix(-1900, -S * 0.4, rIn) + 90 * rCam + 300 * crane,
    rotateX: mix(16, 3, rIn) + drift("fr-rx", frame, 0.6, 0.07) - 1 * rCam + 7 * crane,
    rotateY: mix(30, 7, rIn) - 13 * toReasons + 5 * crane + drift("fr-ry", frame, 0.8, 0.06),
    rotateZ: mix(-5, 0, rIn),
    scale: RESULTS_SCALE,
  };
  const rOpacity = interpolate(rIn, [0, 0.22], [0, 1], clamp);
  // Lifts: the match score on "fit", the "Why it fits" reasons on "how you really play".
  // Each lift settles back into the page as the next one rises (a relay of highlights).
  const badgeLift =
    interpolate(frame, [F - 4, F + 22], [0, 1], { ...clamp, easing: easeOut }) - interpolate(frame, [H - 4, H + 30], [0, 1], { ...clamp, easing: easeInOut });
  const reasonsLift =
    interpolate(frame, [H - 6, H + 26], [0, 1], { ...clamp, easing: easeOut }) - interpolate(frame, [W - 6, W + 34], [0, 1], { ...clamp, easing: easeInOut });

  const env = enterExit(frame, D, OV);

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: `blur(${env.blur}px)` }}>
      <Space3D perspective={2200} originY={46}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            transformStyle: "preserve-3d",
            transform: `translate3d(${cam.x}px, ${cam.y}px, ${cam.z}px) rotateX(${cam.rx}deg) rotateY(${cam.ry}deg) rotateZ(${cam.rz}deg)`,
          }}
        >
          {/* Results page: the end of the deck. */}
          {rOpacity > 0.001 && (
            <>
              <Browser3D {...rPose} path="/finder" opacity={rOpacity} glare={0.8}>
                <Footage name={RESULTS} frame={frame - rStart} />
              </Browser3D>
              <LiftLayer pose={rPose} opacity={rOpacity}>
                {/* dy cancels the perspective drift of the lift (the badge sits above the vanishing point), so it
                    rises toward the lens over its own slot instead of sliding up over the "White studio" chip. */}
                <CropLift name="finder-badge" t={badgeLift} z={120} grow={0.16} dy={16} radius={999} />
                {/* Lifted straight off the plate (no drop, slim margin) so it never covers the "Strengths" row below;
                    cropped to the text column so the floating card stays inside the plate. */}
                <CropLift name="finder-reasons" t={reasonsLift} z={80} grow={0.03} radius={14} pad={6} padColor="rgb(20,21,25)" shadow={0.45} cropW={356} />
                <MatchWave frame={frame} at={W} />
              </LiftLayer>
            </>
          )}

          {/* The deck, back to front. */}
          {CARDS.map((def, k) => k)
            .reverse()
            .map((k) => (
              <DeckCard key={k} id={k} def={CARDS[k]} d={k - p} dPrev={k - pPrev} hover={hoverOf(k)} selected={selectedOf(k)} camYaw={cam.ry} />
            ))}

          {/* Cursor, glued to the front slot. */}
          <div style={{ position: "absolute", left: "50%", top: "50%", width: 0, height: 0, transform: `translate3d(0px, ${SLOT_Y}px, 3px)` }}>
            {curOpacity > 0.001 && <Cursor x={cur.x} y={cur.y} down={cur.down} clicks={clicks} frame={frame} scale={1.3} opacity={curOpacity} />}
          </div>
        </div>
      </Space3D>

      <Sfx name="whoosh-soft" at={2} volume={0.3} />
      <Sfx name="click" at={c1} volume={0.55} />
      <Sfx name="whoosh-soft" at={c1 + 5} volume={0.35} />
      <Sfx name="click" at={c2} volume={0.55} />
      <Sfx name="whoosh-soft" at={c2 + 5} volume={0.35} />
      <Sfx name="click" at={c3} volume={0.55} />
      <Sfx name="swipe" at={R0 - 2} volume={0.36} />
      {taps.map((t) => (
        <Sfx key={t} name="click" at={t} volume={0.3} />
      ))}
      <Sfx name="click" at={c4} volume={0.6} />
      <Sfx name="whoosh" at={c4 + 3} volume={0.5} />
      <Sfx name="pop" at={F} volume={0.3} />
      <Sfx name="whoosh-soft" at={W - 14} volume={0.22} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------

/** Where a card sits at relative depth `d` (0 = front slot, >0 waiting behind, <0 answered and leaving). */
const deckPose = (def: CardDef, d: number) => {
  if (d >= 0) {
    // Waiting in the stack: deeper, up and to the right, a touch fanned.
    return {
      pose: { x: d * 70, y: SLOT_Y - d * 46, z: -d * 250, rotateY: -d * 1.4, rotateZ: d * 0.55 } as Pose,
      opacity: interpolate(d, [4.4, 7.4], [1, 0], clamp),
      dim: interpolate(d, [0, 1, 3], [0, 0.42, 0.78], clamp),
      // Depth of field: cards behind the slot fall softly out of focus.
      dof: interpolate(d, [0, 1, 3], [0, 2.2, 5], clamp),
    };
  }
  // Answered: tossed past the camera.
  const t = Math.min(1.25, -d);
  const e = Math.pow(t, 1.25);
  const f = def.fly;
  return {
    pose: { x: f.sx * e * 760, y: SLOT_Y + f.sy * e * 520, z: e * (f.z ?? 640), rotateX: f.rx * e, rotateY: f.ry * e, rotateZ: f.rz * e } as Pose,
    opacity: interpolate(t, f.fade ?? [0.3, 0.85], [1, 0], clamp),
    dim: 0,
    dof: 0,
  };
};

const PERSPECTIVE = 2200;

/** One card of the deck. Blur = depth of field + directional motion blur from its own screen velocity. */
const DeckCard: React.FC<{ id: number; def: CardDef; d: number; dPrev: number; hover: number; selected: number; camYaw: number }> = ({
  id,
  def,
  d,
  dPrev,
  hover,
  selected,
  camYaw,
}) => {
  const { w, h } = cardSize(def);
  const now = deckPose(def, d);
  if (now.opacity <= 0.001) return null;
  const { pose, opacity, dim, dof } = now;
  // Screen-space velocity (px/frame) of the card centre and of its apparent size.
  const prev = deckPose(def, dPrev).pose;
  const s1 = PERSPECTIVE / (PERSPECTIVE - Math.min(PERSPECTIVE - 200, pose.z ?? 0));
  const s0 = PERSPECTIVE / (PERSPECTIVE - Math.min(PERSPECTIVE - 200, prev.z ?? 0));
  const vx = ((pose.x ?? 0) - (prev.x ?? 0)) * s1;
  const vy = ((pose.y ?? 0) - (prev.y ?? 0)) * s1;
  const grow = Math.abs(s1 - s0) * Math.max(w, h) * 0.5;
  // A ~180° shutter: smear about half the per-frame travel. Blur is applied in card space, before the 3D scale.
  const k = 0.2 / s1;
  const bx = Math.min(16, Math.hypot(dof, Math.abs(vx) * k + grow * k));
  const by = Math.min(16, Math.hypot(dof, Math.abs(vy) * k + grow * k));
  const filterId = `fdk-blur-${id}`;
  const blurred = bx > 0.12 || by > 0.12;

  const s = still(def.base);
  const img = (name: string | undefined, o: number) =>
    name && o > 0.001 ? (
      <Img src={staticFile(still(name).file)} style={{ position: "absolute", left: 0, top: 0, width: w, height: h, opacity: o, display: "block" }} />
    ) : null;
  // Glass glare that slides as the card turns.
  const g = 50 - (camYaw + (pose.rotateY ?? 0)) * 2.4 + (pose.rotateX ?? 0) * 0.8;
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "50%",
        width: w,
        height: h,
        marginLeft: -w / 2,
        marginTop: -h / 2,
        transformStyle: "preserve-3d",
        transform: poseTransform(pose),
        opacity,
      }}
    >
      {blurred && (
        <svg width={0} height={0} style={{ position: "absolute" }} aria-hidden>
          <filter id={filterId} x="-25%" y="-35%" width="150%" height="170%" colorInterpolationFilters="sRGB">
            <feGaussianBlur stdDeviation={`${bx.toFixed(2)} ${by.toFixed(2)}`} />
          </filter>
        </svg>
      )}
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: def.radius * def.scale,
          background: "#050607",
          transform: "translateZ(-12px)",
          boxShadow: "0 60px 130px rgba(0,0,0,0.72), 0 24px 48px rgba(0,0,0,0.5)",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: def.radius * def.scale,
          overflow: "hidden",
          background: C.ground,
          boxShadow: "0 0 0 1.5px rgba(255,255,255,0.09), inset 0 1px 0 rgba(255,255,255,0.06)",
          filter: blurred ? `url(#${filterId})` : undefined,
        }}
      >
        <Img src={staticFile(s.file)} style={{ position: "absolute", left: 0, top: 0, width: w, height: h, display: "block" }} />
        {img(def.hover, hover)}
        {img(def.selected, selected)}
        <AbsoluteFill
          style={{
            background: `linear-gradient(115deg, rgba(255,255,255,0) ${g - 24}%, rgba(255,255,255,0.055) ${g}%, rgba(255,255,255,0) ${g + 20}%)`,
            mixBlendMode: "screen",
          }}
        />
        {dim > 0.002 && <AbsoluteFill style={{ backgroundColor: C.studio, opacity: dim }} />}
      </div>
    </div>
  );
};

/** A transparent twin of a Browser3D's page area (same pose), whose children can leave the page plane. */
const LiftLayer: React.FC<{ pose: Pose; opacity: number; children: React.ReactNode }> = ({ pose, opacity, children }) => {
  const w = 1920;
  const h = 1080 + CHROME_H;
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "50%",
        width: w,
        height: h,
        marginLeft: -w / 2,
        marginTop: -h / 2,
        transformStyle: "preserve-3d",
        transform: poseTransform(pose),
        opacity,
        pointerEvents: "none",
      }}
    >
      <div style={{ position: "absolute", left: 0, top: CHROME_H, width: 1920, height: 1080, transformStyle: "preserve-3d" }}>{children}</div>
    </div>
  );
};

/** The six real match cards (dpr-2 crop of the results row) rising one after another. */
const MatchWave: React.FC<{ frame: number; at: number }> = ({ frame, at }) => {
  const s = still("finder-matches");
  const box = s.marks!.frame;
  const cardW = (box.w - 5 * 8) / 6; // grid-cols-6, gap-2
  const m = 3; // keep the selected card's ring
  return (
    <>
      {[0, 1, 2, 3, 4, 5].map((i) => {
        const t = interpolate(frame, [at + i * 5, at + i * 5 + 30], [0, 1], { ...clamp, easing: easeOut });
        if (t <= 0.001) return null;
        const left = i * (cardW + 8) - m;
        return (
          <React.Fragment key={i}>
            <Recess x={box.x + i * (cardW + 8)} y={box.y} w={cardW} h={box.h} radius={24} t={t} />
            <div
              style={{
                position: "absolute",
                left: box.x + left,
                top: box.y - m,
                width: cardW + m * 2,
                height: box.h + m * 2,
                padding: m,
                boxSizing: "border-box",
                borderRadius: 24 + m,
                overflow: "hidden",
                transformOrigin: "50% 50%",
                transform: `translateZ(${t * 40}px) scale(${1 + t * 0.03})`,
                boxShadow: `0 ${t * 22}px ${t * 44}px rgba(0,0,0,${0.55 * t})`,
                opacity: interpolate(t, [0, 0.12], [0, 1], clamp),
              }}
            >
              <div style={{ position: "relative", width: cardW, height: box.h, overflow: "hidden", borderRadius: 24 }}>
                <Img src={staticFile(s.file)} style={{ position: "absolute", left: -i * (cardW + 8), top: 0, width: box.w, height: box.h, display: "block" }} />
              </div>
            </div>
          </React.Fragment>
        );
      })}
    </>
  );
};

/**
 * A dpr-2 crop of the real results page, placed exactly over the same spot of the
 * footage (`marks.frame`), rising off the page plane by `t` (0–1).
 */
const CropLift: React.FC<{
  name: string;
  t: number;
  z: number;
  grow: number;
  radius: number;
  pad?: number;
  padColor?: string;
  origin?: string;
  dy?: number;
  /** Strength of the cast shadow (0–1). */
  shadow?: number;
  /** Show only the left `cropW` CSS px of the crop (e.g. just the text column). */
  cropW?: number;
}> = ({ name, t, z, grow, dy = 0, radius, pad = 0, padColor, origin = "50% 50%", shadow = 1, cropW }) => {
  if (t <= 0.001) return null;
  const s = still(name);
  const box = s.marks!.frame;
  const w = Math.min(cropW ?? box.w, box.w);
  return (
    <>
      <Recess x={box.x} y={box.y} w={w} h={box.h} radius={radius} t={t} />
      <div
        style={{
          position: "absolute",
          left: box.x - pad,
          top: box.y - pad,
          width: w + pad * 2,
          height: box.h + pad * 2,
          padding: pad,
          boxSizing: "border-box",
          background: padColor,
          transformOrigin: origin,
          transform: `translate3d(0px, ${t * dy}px, ${t * z}px) scale(${1 + t * grow})`,
          borderRadius: radius,
          overflow: "hidden",
          boxShadow: `0 ${t * 26 * shadow}px ${t * 56 * shadow}px rgba(0,0,0,${0.6 * t * Math.min(1, shadow * 1.4)}), 0 0 0 ${pad ? 1 : 0}px rgba(255,255,255,${0.08 * t})`,
          opacity: interpolate(t, [0, 0.15], [0, 1], clamp),
        }}
      >
        <div style={{ width: w, height: box.h, overflow: "hidden" }}>
          <Img src={staticFile(s.file)} style={{ width: box.w, height: box.h, display: "block" }} />
        </div>
      </div>
    </>
  );
};

/** The lifted element's slot on the page, falling into its shadow (so the original never reads as a duplicate). */
const Recess: React.FC<{ x: number; y: number; w: number; h: number; radius: number; t: number }> = ({ x, y, w, h, radius, t }) => (
  <div
    style={{
      position: "absolute",
      left: x - 2,
      top: y - 2,
      width: w + 4,
      height: h + 4,
      borderRadius: radius,
      background: `rgba(6,7,8,${0.82 * Math.min(1, t * 1.6)})`,
      boxShadow: `inset 0 2px 10px rgba(0,0,0,${0.6 * t})`,
    }}
  />
);
