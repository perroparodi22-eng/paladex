// The price as an odometer: each digit is a column that rolls up to its next value
// (with vertical motion blur), so "€200" can flick to "€250" and "€300" on the words.
import React from "react";
import { Easing, interpolate } from "remotion";
import { clamp } from "../../lib/motion";
import { C, display } from "../../theme";

const ROLL = Easing.bezier(0.2, 0.9, 0.25, 1);

/** One digit: `steps` are [frame, digit] changes in order, starting from `first`. */
const Digit: React.FC<{ frame: number; first: string; steps: readonly (readonly [number, string])[]; size: number; dur: number }> = ({ frame, first, steps, size, dur }) => {
  // Find the current transition (the last one that has started).
  let prev = first;
  let next = first;
  let t = 1;
  for (const [at, d] of steps) {
    if (frame < at) break;
    prev = next;
    next = d;
    t = interpolate(frame, [at, at + dur], [0, 1], { ...clamp, easing: ROLL });
  }
  const moving = t < 1 && prev !== next;
  const v = moving ? Math.abs(interpolate(t, [0, 0.5, 1], [0, 1, 0])) : 0;
  const cell: React.CSSProperties = { position: "absolute", left: 0, top: 0, width: "100%", textAlign: "center" };
  return (
    <span style={{ position: "relative", display: "inline-block", height: size, overflow: "hidden", verticalAlign: "top" }}>
      {/* Sizer keeps the column as wide as the widest of its digits. */}
      <span style={{ visibility: "hidden" }}>{next}</span>
      {moving && <span style={{ ...cell, translate: `0px ${-t * size * 1.02}px`, filter: `blur(0px ${v * 10}px)`, opacity: 1 - t }}>{prev}</span>}
      <span style={{ ...cell, translate: `0px ${(1 - t) * size * 1.02}px`, filter: moving ? `blur(${v * 3}px)` : undefined }}>{next}</span>
    </span>
  );
};

export const Price: React.FC<{
  frame: number;
  size: number;
  /** Hundreds and tens digit changes. */
  hundreds: readonly (readonly [number, string])[];
  tens: readonly (readonly [number, string])[];
  firstHundreds?: string;
  firstTens?: string;
  style?: React.CSSProperties;
}> = ({ frame, size, hundreds, tens, firstHundreds = "2", firstTens = "0", style }) => (
  <div style={{ ...display, display: "flex", alignItems: "flex-start", fontSize: size, lineHeight: 1, color: C.ink, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", ...style }}>
    <span style={{ fontSize: size * 0.44, marginTop: size * 0.1, marginRight: size * 0.04, color: C.ink2 }}>€</span>
    <Digit frame={frame} first={firstHundreds} steps={hundreds} size={size} dur={10} />
    <Digit frame={frame} first={firstTens} steps={tens} size={size} dur={10} />
    <span>0</span>
  </div>
);
