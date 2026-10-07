// Subtitles driven by the voiceover's word timings (most social video plays muted).
// Shows the current phrase; the word being spoken is bright, the rest dimmed.
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import type { Timeline, Word } from "../timeline";
import { C, FONT } from "../theme";
import { clamp, easeOut } from "../lib/motion";

const MAX_WORDS = 7;

/** Split a line into phrases at punctuation or every MAX_WORDS words. */
const phrases = (words: Word[]): Word[][] => {
  const out: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    cur.push(w);
    if (/[.,?!…:;]$/.test(w.text) || cur.length >= MAX_WORDS) {
      out.push(cur);
      cur = [];
    }
  }
  if (cur.length) out.push(cur);
  return out;
};

export const Captions: React.FC<{ timeline: Timeline; bottom?: number; hideFor?: string[] }> = ({ timeline, bottom = 70, hideFor = [] }) => {
  const frame = useCurrentFrame();
  const all = timeline.scenes.filter((s) => !hideFor.includes(s.id)).flatMap((s) => phrases(s.vo.words));
  // Phrase on screen: from its first word until just before the next phrase (max 0.6 s after its last word).
  const idx = all.findIndex((p, i) => {
    const start = p[0].start - 4;
    const next = all[i + 1]?.[0].start ?? Infinity;
    const end = Math.min(next - 4, p[p.length - 1].end + 36);
    return frame >= start && frame < end;
  });
  if (idx < 0) return null;
  const p = all[idx];
  const start = p[0].start - 4;
  const end = Math.min((all[idx + 1]?.[0].start ?? Infinity) - 4, p[p.length - 1].end + 36);
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
        {p.map((w, i) => {
          const lit = frame >= w.start - 2;
          return (
            <span key={i} style={{ color: lit ? C.ink : "rgba(236,238,241,0.38)" }}>
              {w.text.replace(/\.\.\.$/, "…")}
              {i < p.length - 1 ? " " : ""}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
