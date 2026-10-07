// Headline type that rises word by word out of a soft blur (and can leave the same
// way). Uses the site's display face.
import React from "react";
import { interpolate } from "remotion";
import { display } from "../theme";
import { clamp, easeIn, easeOut } from "../lib/motion";

export const Kinetic: React.FC<{
  text: string;
  frame: number;
  /** Local frame the first word starts rising. */
  at: number;
  /** Local frame the words start leaving (optional). */
  outAt?: number;
  size?: number;
  stagger?: number;
  dur?: number;
  align?: "left" | "center" | "right";
  color?: string;
  /** Words (exact, case-insensitive) to paint in an accent colour. */
  accent?: { words: string[]; color: string };
  style?: React.CSSProperties;
  maxWidth?: number;
}> = ({ text, frame, at, outAt, size = 96, stagger = 4, dur = 26, align = "left", color, accent, style, maxWidth }) => {
  const words = text.split(" ");
  return (
    <div style={{ ...display, fontSize: size, textAlign: align, color: color ?? display.color, maxWidth, ...style }}>
      {words.map((w, i) => {
        const t = interpolate(frame, [at + i * stagger, at + i * stagger + dur], [0, 1], { ...clamp, easing: easeOut });
        const o = outAt === undefined ? 0 : interpolate(frame, [outAt + i * 2, outAt + i * 2 + 16], [0, 1], { ...clamp, easing: easeIn });
        const isAccent = accent?.words.some((a) => a.toLowerCase() === w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, ""));
        return (
          <span key={i} style={{ display: "inline-block", whiteSpace: "pre" }}>
            <span
              style={{
                display: "inline-block",
                opacity: t * (1 - o),
                translate: `0px ${(1 - t) * 0.55 * size - o * 0.3 * size}px`,
                filter: `blur(${(1 - t) * 14 + o * 10}px)`,
                color: isAccent ? accent!.color : undefined,
              }}
            >
              {w}
            </span>
            {i < words.length - 1 ? " " : ""}
          </span>
        );
      })}
    </div>
  );
};
