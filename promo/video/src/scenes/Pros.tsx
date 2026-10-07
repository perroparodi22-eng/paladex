// Scene 7, pros: "See what the pros actually play."
//
// Real /pros page only: dpr 2 crops of the player entries (name label + racket card, cut
// below the "played by" line), the page's own title and caveat paragraph, and the real
// .glb of the landing pro's racket. Four shots, each cut on a word:
//
//   See / what      the men's tour: a fast lateral whip along a concave arc of real pro cards,
//                   blurred foreground cards and giant ghost player names on other depths
//                   streaming at other speeds.
//   pros            the women's tour, whipping back the other way, lower and larger; a punch-in
//                   and a card ping on the word.
//   actually        a macro of the "played by" line of the landing card (dpr 4 crop).
//   play            the macro pulls out into Agustín Tapia's whole card slamming in (impact),
//                   his real racket model breaks out of the poster and turns; the page's title
//                   and its caveat paragraph slide in beside it; neighbours drift behind.
// House enter/exit on the root.
import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { Space3D } from "../components/Browser3D";
import { RacketModel, RacketStage } from "../components/Racket3D";
import { Sfx } from "../components/Sfx";
import { still } from "../components/Footage";
import { clamp, drift, easeIn, easeInOut, easeOut, enterExit, mix } from "../lib/motion";
import { C, FONT, display } from "../theme";
import { wordAt } from "../timeline";
import cards from "./pros/cards.json";
import type { SceneProps } from "./types";

type CardDef = { key: string; who: string; tour: string; name: string };
const ALL = cards as CardDef[];
const byWho = (who: string) => ALL.find((c) => c.who === who)!;
const MEN = ["Arturo Coello", "Alejandro Galán", "Fede Chingotto", "Juan Lebrón", "Franco Stupaczuk", "Paquito Navarro", "Mike Yanguas", "Leo Augsburger", "Jon Sanz", "Martín Di Nenno"].map(byWho);
const WOMEN = ["Ari Sánchez", "Delfi Brea", "Alejandra Salazar", "Claudia Fernández"].map(byWho);
const TAPIA = byWho("Agustín Tapia");
const TAPIA_SLUG = "nox-at10-luxury-genius-12k-alum-xtrem-2026"; // the real model of Tapia's racket

const W = 1920;
const H = 1080;
const src = (key: string) => staticFile(still(key).file);
const BLUR_FAST = Easing.bezier(0.1, 0.9, 0.22, 1);

/* ---------------------------------------------------------------- pieces */

/** One real pro entry, centred on its own origin, as a plate in 3D. */
const ProCard: React.FC<{ def: CardDef; x: number; y?: number; z?: number; ry?: number; rz?: number; scale?: number; blur?: number; opacity?: number; dim?: number; glow?: number }> = ({
  def,
  x,
  y = 0,
  z = 0,
  ry = 0,
  rz = 0,
  scale = 1,
  blur = 0,
  opacity = 1,
  dim = 1,
  glow = 0,
}) => {
  const s = still(def.key);
  return (
    <div
      style={{
        position: "absolute",
        left: -s.width / 2,
        top: -s.height / 2,
        width: s.width,
        height: s.height,
        transform: `translate3d(${x}px, ${y}px, ${z}px) rotateY(${ry}deg) rotateZ(${rz}deg) scale(${scale})`,
        opacity,
        filter: `${blur > 0.2 ? `blur(${blur}px) ` : ""}brightness(${dim})`,
        borderRadius: 22,
        overflow: "hidden",
        boxShadow: `0 0 0 1px rgba(236,238,241,${0.07 + glow * 0.5}), 0 40px 90px rgba(0,0,0,0.65)`,
        WebkitMaskImage: "linear-gradient(to bottom, #000 90%, transparent)",
        maskImage: "linear-gradient(to bottom, #000 90%, transparent)",
      }}
    >
      <Img src={src(def.key)} style={{ width: "100%", height: "100%", display: "block" }} />
    </div>
  );
};

/** A world that the camera flies through: children are positioned in world px. */
const World: React.FC<{ camX: number; camY?: number; camZ?: number; camRY?: number; camRZ?: number; children: React.ReactNode }> = ({ camX, camY = 0, camZ = 0, camRY = 0, camRZ = 0, children }) => (
  <Space3D perspective={1500} originX={50} originY={46}>
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "50%",
        width: 0,
        height: 0,
        transformStyle: "preserve-3d",
        transform: `translate3d(${-camX}px, ${-camY}px, ${camZ}px) rotateY(${camRY}deg) rotateZ(${camRZ}deg)`,
      }}
    >
      {children}
    </div>
  </Space3D>
);

/** Whip blur on a shot's first/last frames. */
const whip = (f: number, dur: number, inFrames = 5, outFrames = 5) =>
  interpolate(f, [0, inFrames], [1, 0], clamp) * 22 + interpolate(f, [dur - outFrames, dur], [0, 1], clamp) * 22;

/** Giant ghost names streaming on a far plane (real player names from the page). */
const GhostNames: React.FC<{ names: string[]; camX: number; y: number; z: number; opacity: number; size: number; pitch: number }> = ({ names, camX, y, z, opacity, size, pitch }) => (
  <>
    {names.map((n, i) => (
      <div
        key={n}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          whiteSpace: "nowrap",
          ...display,
          fontSize: size,
          color: C.ink,
          opacity,
          transform: `translate3d(${i * pitch}px, ${y}px, ${z}px)`,
          WebkitTextStroke: "0px",
        }}
      >
        {n}
      </div>
    ))}
  </>
);

/* ------------------------------------------------------------------ shots */

/** Shot 1: men's tour, lateral whip along a concave arc. f = shot-local frame. */
const ShotMen: React.FC<{ f: number; dur: number }> = ({ f, dur }) => {
  const PITCH = 500;
  const camX = 3000 * BLUR_FAST(clamp01(f / 50)) + f * 4 + 60;
  const arc = (x: number) => {
    const dx = x - camX;
    const k = Math.max(-1, Math.min(1, dx / 900));
    return { ry: -k * 30, z: -Math.abs(dx) * 0.22 };
  };
  return (
    <AbsoluteFill style={{ filter: `blur(${whip(f, dur, 5, 5)}px)` }}>
      {/* far: ghost names, slow */}
      <World camX={camX * 0.35} camY={-14 + drift("m1", f, 10, 0.3)} camRZ={drift("m1z", f, 0.8, 0.2)}>
        <GhostNames names={MEN.map((m) => m.who.toUpperCase())} camX={camX} y={-120} z={-900} opacity={0.07} size={300} pitch={1500} />
      </World>
      {/* the row */}
      <World camX={camX} camY={drift("m2", f, 12, 0.3)} camRZ={-1.4 + drift("m2z", f, 0.9, 0.2)} camRY={drift("m2y", f, 2, 0.2)}>
        <ProCardHeading kind="men" x={-40} />
        {MEN.map((c, i) => {
          const x = i * PITCH + 200;
          const a = arc(x);
          return <ProCard key={c.key} def={c} x={x} y={-20} z={a.z} ry={a.ry} scale={1.3} />;
        })}
      </World>
      {/* near: blurred cards passing fast (parallax) */}
      <World camX={camX * 1.9} camY={-40} camRZ={-2}>
        {[MEN[3], MEN[7], MEN[1], MEN[5]].map((c, i) => (
          <ProCard key={c.key} def={c} x={i * 1700 + 700} y={380} z={420} ry={-10} scale={1.35} blur={9} opacity={0.85} dim={0.8} />
        ))}
      </World>
    </AbsoluteFill>
  );
};

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

const ProCardHeading: React.FC<{ kind: "men" | "women"; x: number }> = ({ kind, x }) => {
  const s = still(`pros-${kind}`);
  return (
    <div style={{ position: "absolute", left: x - 300, top: -470, width: 460, height: s.height, overflow: "hidden", transform: "translate3d(0,0,-60px) scale(1.5)", transformOrigin: "0 0" }}>
      <Img src={src(`pros-${kind}`)} style={{ position: "absolute", left: 0, top: 0, width: s.width, height: s.height }} />
    </div>
  );
};

/** Shot 2: women's tour, back the other way, lower and larger; a punch + ping on "pros". */
const ShotWomen: React.FC<{ f: number; dur: number; ping: number }> = ({ f, dur, ping }) => {
  const PITCH = 560;
  const total = (WOMEN.length - 1) * PITCH + 200;
  const camX = total - 2300 * BLUR_FAST(clamp01(f / 46)) - f * 3;
  const punch = interpolate(f, [ping - 3, ping + 9], [0, 1], { ...clamp, easing: easeOut });
  const pingP = interpolate(f, [ping, ping + 18], [0, 1], { ...clamp, easing: easeOut });
  const pingOut = interpolate(f, [ping + 14, ping + 34], [0, 1], { ...clamp, easing: easeInOut });
  // The card nearest the middle at the ping gets the highlight.
  const hi = Math.round((camX - 200) / PITCH);
  return (
    <AbsoluteFill style={{ filter: `blur(${whip(f, dur, 5, 5)}px)`, scale: String(1 + punch * 0.07) }}>
      <World camX={camX * 0.4} camY={30} camRZ={2}>
        <GhostNames names={WOMEN.map((m) => m.who.toUpperCase()).reverse()} camX={camX} y={-160} z={-1000} opacity={0.07} size={300} pitch={1500} />
      </World>
      <World camX={camX} camY={drift("w1", f, 14, 0.3) - 10} camRZ={2.2 + drift("w1z", f, 0.8, 0.2)} camRY={-6 + drift("w1y", f, 2, 0.2)}>
        <ProCardHeading kind="women" x={WOMEN.length * PITCH - 160} />
        {WOMEN.map((c, i) => {
          const x = i * PITCH + 200;
          const dx = x - camX;
          const k = Math.max(-1, Math.min(1, dx / 900));
          const isHi = i === hi;
          return <ProCard key={c.key} def={c} x={x} y={-50} z={-Math.abs(dx) * 0.2 + (isHi ? pingP * 70 * (1 - pingOut) : 0)} ry={-k * 26} scale={1.45} glow={isHi ? pingP * (1 - pingOut) : 0} />;
        })}
      </World>
      <World camX={camX * 2.1} camY={60} camRZ={3}>
        {[WOMEN[3], WOMEN[1]].map((c, i) => (
          <ProCard key={c.key} def={c} x={i * 2200 + 500} y={-420} z={520} ry={8} scale={1.5} blur={11} opacity={0.8} dim={0.7} />
        ))}
      </World>
    </AbsoluteFill>
  );
};

/** Shot 3: macro of the "played by" line (dpr 4 crop). `p` = whole-shot progress. */
const ShotMacro: React.FC<{ f: number; dur: number }> = ({ f, dur }) => {
  const s = still("pros-tapia-info");
  const scale = mix(2.2, 2.85, easeOut(clamp01(f / (dur * 0.8))));
  const pan = mix(60, -90, clamp01(f / dur));
  return (
    <AbsoluteFill style={{ filter: `blur(${whip(f, dur, 4, 6)}px)` }}>
      <World camX={mix(300, 700, clamp01(f / dur))} camY={0} camRZ={-1.5}>
        {[MEN[2], MEN[3], MEN[4], MEN[5], MEN[6]].map((c, i) => (
          <ProCard key={c.key} def={c} x={i * 520} y={(i % 2) * 40 - 20} z={-700} ry={-12} scale={1.3} blur={8} opacity={0.9} dim={0.55} />
        ))}
      </World>
      <Space3D perspective={1500}>
        <div style={{ position: "absolute", left: "50%", top: "50%", transformStyle: "preserve-3d", transform: `translate3d(${pan}px, -40px, 0px) rotateY(${mix(14, -6, clamp01(f / dur))}deg) rotateZ(${mix(-2.2, 0.6, clamp01(f / dur))}deg) scale(${scale})` }}>
          <div style={{ position: "absolute", left: -s.width / 2, top: -s.height / 2, width: s.width, height: s.height, borderRadius: 18, overflow: "hidden", boxShadow: "0 0 0 1px rgba(236,238,241,0.1), 0 50px 120px rgba(0,0,0,0.7)" }}>
            <Img src={src("pros-tapia-info")} style={{ width: "100%", height: "100%", display: "block" }} />
          </div>
        </div>
      </Space3D>
    </AbsoluteFill>
  );
};

/** Shot 4: Tapia's card lands; the racket breaks out; title + caveat arrive. f = shot-local frame. */
const LAND_X = -520;
const LAND_Y = -30;
const CARD_SCALE = 1.5;
const ShotLand: React.FC<{ f: number; dur: number }> = ({ f, dur }) => {
  const slam = interpolate(f, [0, 20], [0, 1], { ...clamp, easing: Easing.bezier(0.2, 0.9, 0.2, 1) });
  const settle = interpolate(f, [12, 80], [0, 1], { ...clamp, easing: easeOut });
  const cardZ = (1 - slam) * 1100;
  const cardRY = (1 - slam) * -38 + mix(0, 6, settle) + drift("l1", f, 1.4, 0.25);
  const cardX = LAND_X - settle * 30;
  const dim = mix(1, 0.62, rise2(f, 14, 24));
  const sx = (n: number) => n; // keep px
  return (
    <AbsoluteFill style={{ filter: `blur(${interpolate(f, [0, 6], [20, 0], clamp)}px)` }}>
      {/* depth: the other pros drifting behind, soft */}
      <World camX={mix(900, 1500, f / dur)} camY={drift("l2", f, 12, 0.2)} camRZ={-1.5}>
        {[MEN[0], MEN[1], MEN[2], MEN[3], MEN[4]].map((c, i) => (
          <ProCard key={c.key} def={c} x={i * 520 + 400} y={20 + (i % 2) * 40} z={-520 - (i % 2) * 120} ry={-14} scale={1.3} blur={6} opacity={0.9 * rise2(f, 4, 26)} dim={0.75} />
        ))}
      </World>
      <World camX={0} camY={0}>
        <ProCard def={TAPIA} x={sx(cardX)} y={LAND_Y} z={cardZ} ry={cardRY} scale={CARD_SCALE} dim={dim} glow={rise2(f, 0, 16) * (1 - rise2(f, 16, 40))} />
      </World>
    </AbsoluteFill>
  );
};

const rise2 = (f: number, a: number, d: number) => interpolate(f, [a, a + d], [0, 1], { ...clamp, easing: easeOut });

/** The page's own title and caveat (verbatim text), set in the video's type. */
const PageHead: React.FC<{ f: number; x: number; y: number }> = ({ f, x, y }) => {
  const t1 = rise2(f, 0, 26);
  const t2 = rise2(f, 7, 26);
  const row = (t: number, children: React.ReactNode, top: number) => (
    <div style={{ position: "absolute", left: 0, top, opacity: t, translate: `${(1 - t) * 120}px 0px`, filter: `blur(${(1 - t) * 12}px)` }}>{children}</div>
  );
  return (
    <div style={{ position: "absolute", left: x, top: y, width: 700, height: 420, transform: `perspective(1400px) rotateY(${mix(-14, -5, t1)}deg) translateX(${f * -0.12}px)`, transformOrigin: "0 50%" }}>
      <div style={{ position: "absolute", left: -60, top: -50, width: 820, height: 480, borderRadius: 40, background: "radial-gradient(ellipse at 40% 50%, rgba(7,8,9,0.88) 0%, rgba(7,8,9,0.7) 55%, rgba(7,8,9,0) 100%)", opacity: t1 }} />
      {row(t1, <div style={{ ...display, fontSize: 84, width: 700 }}>Pro players' rackets</div>, 0)}
      {row(
        t2,
        <div style={{ fontFamily: FONT, fontSize: 28, lineHeight: 1.4, color: C.ink2, width: 680 }}>
          What the top of the tour plays, in 3D. Players are matched to rackets from public lists as of early 2026; sponsors and editions change during the season, and some pros play a personalised version of the model shown.
        </div>,
        190,
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ scene */

export const Pros: React.FC<SceneProps> = ({ timing, timeline }) => {
  const frame = useCurrentFrame();
  const env = enterExit(frame, timing.duration, timeline.overlapFrames);

  const wSee = wordAt(timing, "See", 17);
  const wWhat = wordAt(timing, "what", 32);
  const wPros = wordAt(timing, "pros", 66);
  const wActually = wordAt(timing, "actually", 85);
  const wPlay = wordAt(timing, "play", 115);

  // Cuts: men (0) → women (just after "what" has landed) → macro on "actually" → landing on "play".
  const c1 = Math.round(wWhat + (wPros - wWhat) * 0.45);
  const c2 = Math.max(c1 + 24, wActually - 2);
  const c3 = Math.max(c2 + 24, wPlay - 3);
  const end = timing.duration + timeline.overlapFrames;

  const inShot = (a: number, b: number) => frame >= a && frame < b;
  const lf = frame - c3; // landing-local

  // Landing choreography.
  const flash = lf >= 0 ? interpolate(lf, [14, 17, 34], [0, 0.34, 0], clamp) : 0;
  const ring = interpolate(lf, [15, 50], [0, 1], { ...clamp, easing: easeOut });
  const popAt = c3 + 26;
  const modelP = interpolate(frame, [popAt, popAt + 30], [0, 1], { ...clamp, easing: easeOut });
  const modelOp = interpolate(frame, [popAt, popAt + 7], [0, 1], clamp);
  const spin = (frame - popAt) * 0.026 + (1 - modelP) * -4.2;
  const modelScale = mix(0.7, 1.22, modelP) * (1 + drift("ms", frame, 0.012, 0.3));
  const modelX = -230 / 1440;
  const showModel = frame >= popAt;

  return (
    <AbsoluteFill style={{ opacity: env.opacity, scale: env.scale, filter: `blur(${env.blur}px)` }}>
      {inShot(0, c1 + 4) && <ShotMen f={frame} dur={c1 + 4} />}
      {inShot(c1, c2 + 4) && <ShotWomen f={frame - c1} dur={c2 + 4 - c1} ping={wPros - c1} />}
      {inShot(c2, c3 + 4) && <ShotMacro f={frame - c2} dur={c3 + 4 - c2} />}
      {frame >= c3 && <ShotLand f={lf} dur={end - c3} />}

      {frame >= c3 && showModel && (
        <AbsoluteFill style={{ opacity: modelOp, filter: `blur(${(1 - modelP) * 6}px)` }}>
          <RacketStage width={W} height={H} floorY={null}>
            <RacketModel slug={TAPIA_SLUG} position={[modelX, (540 - (540 + LAND_Y)) / 1440 + 0.03, 0.12]} rotation={[0.1, spin, -0.12]} scale={modelScale} />
          </RacketStage>
        </AbsoluteFill>
      )}

      {frame >= c3 + 44 && <PageHead f={frame - (c3 + 44)} x={1130} y={300} />}

      {/* landing impact: a soft flash and one thin ring */}
      {lf >= 14 && (
        <>
          <AbsoluteFill style={{ background: `radial-gradient(ellipse at ${50 + LAND_X / 19.2}% 46%, rgba(236,238,241,${flash}), transparent 62%)` }} />
          <div
            style={{
              position: "absolute",
              left: W / 2 + LAND_X,
              top: H / 2 + LAND_Y,
              width: 900 * ring,
              height: 900 * ring,
              marginLeft: -450 * ring,
              marginTop: -450 * ring,
              borderRadius: "50%",
              border: `2px solid rgba(236,238,241,${0.5 * (1 - ring)})`,
            }}
          />
        </>
      )}

      {/* sound: a hit on every cut and landing */}
      <Sfx name="whoosh" at={0} volume={0.5} />
      <Sfx name="swipe" at={wSee} volume={0.45} />
      <Sfx name="tick" at={wWhat} volume={0.4} />
      <Sfx name="whoosh" at={c1 - 2} volume={0.6} />
      <Sfx name="pop" at={wPros} volume={0.55} />
      <Sfx name="whoosh" at={c2 - 2} volume={0.65} />
      <Sfx name="impact" at={c3 + 14} volume={0.9} />
      <Sfx name="pop" at={popAt} volume={0.6} />
      <Sfx name="shimmer" at={popAt + 6} volume={0.45} />
      <Sfx name="swipe" at={c3 + 44} volume={0.4} />
      <Sfx name="whoosh-soft" at={timing.duration - 8} volume={0.4} />
    </AbsoluteFill>
  );
};
