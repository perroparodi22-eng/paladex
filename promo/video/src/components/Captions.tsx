// Subtitles driven by the voiceover's word timings (most social video plays muted).
// Pages by the script's phrases (with their punctuation); the word being spoken is bright, the rest dimmed.
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import type { Lang, Timeline, Word } from "../timeline";
import script from "../data/script.json";
import { C, FONT } from "../theme";
import { clamp, easeOut } from "../lib/motion";

const MAX_CHARS = 44;
const MAX_WORDS = 8;

type Cap = { words: Word[]; labels: string[] };

const chars = (ws: string[]) => ws.join(" ").length;
const short = (c: string[]) => c.length <= 2;

/** Split a phrase at a comma, else near its middle, until each piece fits one pill. */
const split = (w: string[]): string[][] => {
  if (w.length <= 1 || (chars(w) <= MAX_CHARS && w.length <= MAX_WORDS)) return [w];
  const mid = w.length / 2;
  const commas = w
    .map((x, i) => (/[,:;]$/.test(x) ? i + 1 : -1))
    .filter((i) => i > 1 && i < w.length - 1);
  const cut = commas.length ? commas.reduce((a, b) => (Math.abs(b - mid) < Math.abs(a - mid) ? b : a)) : Math.round(mid);
  return [...split(w.slice(0, cut)), ...split(w.slice(cut))];
};

/** Caption pills of one scene: whole script phrases, never a lone orphan word. */
const pillsFor = (sceneId: string, words: Word[], lang: Lang): Cap[] => {
  const langs = script.langs as unknown as Record<string, { lines: Record<string, { text: string }[]> }>;
  const lines = langs[lang]?.lines[sceneId] ?? [];
  const chunks = lines.flatMap((l) => split(l.text.trim().split(/\s+/)));
  const pills: string[][] = [];
  for (const c of chunks) {
    const prev = pills[pills.length - 1];
    if (prev && prev.length === 1) prev.push(...c);
    else if (prev && short(c) && short(prev) && prev.length + c.length <= 4) prev.push(...c);
    else if (prev && short(c) && !short(prev) && chars([...prev, ...c]) <= MAX_CHARS + 4) prev.push(...c);
    else pills.push([...c]);
  }
  let k = 0;
  return pills.map((labels) => {
    const ws = words.slice(k, k + labels.length);
    k += labels.length;
    return { words: ws, labels };
  });
};

export const Captions: React.FC<{ timeline: Timeline; bottom?: number; hideFor?: string[] }> = ({
  timeline,
  bottom = 70,
  hideFor = ["endcard"], // the end card's headline is the caption already
}) => {
  const frame = useCurrentFrame();
  const all = timeline.scenes
    .filter((s) => !hideFor.includes(s.id))
    .flatMap((s) => pillsFor(s.id, s.vo.words, timeline.lang as Lang))
    .filter((p) => p.words.length > 0);
  // Pill on screen: from its first word until just before the next pill (max 0.6 s after its last word).
  const range = (i: number) => {
    const p = all[i];
    const next = all[i + 1]?.words[0].start ?? Infinity;
    return [p.words[0].start - 4, Math.min(next - 4, p.words[p.words.length - 1].end + 36)] as const;
  };
  const idx = all.findIndex((_, i) => {
    const [a, b] = range(i);
    return frame >= a && frame < b;
  });
  if (idx < 0) return null;
  const p = all[idx];
  const [start, end] = range(idx);
  const inT = interpolate(frame, [start, start + 8], [0, 1], { ...clamp, easing: easeOut });
  const outT = interpolate(frame, [end - 8, end], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", pointerEvents: "none" }}>
      <div
        style={{
          marginBottom: bottom,
          padding: "14px 28px 16px",
          borderRadius: 999,
          background: "rgba(10,11,13,0.62)",
          backdropFilter: "blur(14px)",
          boxShadow: "0 0 0 1px rgba(255,255,255,0.07)",
          fontFamily: FONT,
          fontSize: 40,
          fontWeight: 560,
          letterSpacing: "-0.01em",
          opacity: inT * outT,
          translate: `0px ${(1 - inT) * 14}px`,
          whiteSpace: "nowrap",
        }}
      >
        {p.labels.map((label, i) => {
          const lit = frame >= p.words[i].start - 2;
          return (
            <span key={i} style={{ color: lit ? C.ink : "rgba(236,238,241,0.38)" }}>
              {label.replace(/\.\.\.$/, "…")}
              {i < p.labels.length - 1 ? " " : ""}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
