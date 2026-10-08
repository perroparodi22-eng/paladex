// A crisp mouse pointer (arrow, or a grabbing hand while dragging) with a click
// ripple. Coordinates are page px inside <Browser3D> children, so the cursor moves
// with the 3D window.
import React from "react";
import { interpolate } from "remotion";
import { clamp, easeInOut, easeOut } from "../lib/motion";

export type CursorKey = { f: number; x: number; y: number; down?: boolean };

/**
 * Position along eased keyframes (frames relative to the caller's timeline), with
 * a slight arc between points so moves feel hand-made. Holds at the ends.
 */
export const cursorAt = (keys: CursorKey[], frame: number): { x: number; y: number; down: boolean } => {
  if (frame <= keys[0].f) return { x: keys[0].x, y: keys[0].y, down: !!keys[0].down };
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (frame <= b.f) {
      const t = interpolate(frame, [a.f, b.f], [0, 1], { ...clamp, easing: easeInOut });
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const arc = Math.sin(t * Math.PI) * Math.min(60, Math.hypot(dx, dy) * 0.08);
      const len = Math.hypot(dx, dy) || 1;
      return { x: a.x + dx * t + (-dy / len) * arc, y: a.y + dy * t + (dx / len) * arc, down: !!a.down };
    }
  }
  const z = keys[keys.length - 1];
  return { x: z.x, y: z.y, down: !!z.down };
};

export const Cursor: React.FC<{
  x: number;
  y: number;
  /** Pressed (shows the grab hand while true if `grab`). */
  down?: boolean;
  grab?: boolean;
  /** Frames (same timeline as `frame`) at which a click happens, for ripples. */
  clicks?: number[];
  frame: number;
  scale?: number;
  opacity?: number;
}> = ({ x, y, down = false, grab = false, clicks = [], frame, scale = 1.35, opacity = 1 }) => {
  const press = down ? 0.88 : 1;
  return (
    <>
      {clicks.map((c) => {
        const t = frame - c;
        if (t < 0 || t > 30) return null;
        const p = interpolate(t, [0, 30], [0, 1], { ...clamp, easing: easeOut });
        return (
          <div
            key={c}
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              width: 96,
              height: 96,
              borderRadius: 48,
              border: "3px solid rgba(236,238,241,0.9)",
              translate: `${x - 48}px ${y - 48}px`,
              scale: 0.2 + p * 0.9,
              opacity: 1 - p,
            }}
          />
        );
      })}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          translate: `${x}px ${y}px`,
          scale: scale * press,
          transformOrigin: "0 0",
          opacity,
          filter: "drop-shadow(0 6px 10px rgba(0,0,0,0.55))",
        }}
      >
        {grab ? <HandIcon closed={down} /> : <ArrowIcon />}
      </div>
    </>
  );
};

const ArrowIcon = () => (
  <svg width="30" height="40" viewBox="0 0 30 40" style={{ display: "block" }}>
    <path d="M2 2 L2 31 L9.5 24.5 L14.5 36.5 L20 34 L15 22.5 L25 22.5 Z" fill="#ffffff" stroke="#0a0b0d" strokeWidth="2.2" strokeLinejoin="round" />
  </svg>
);

const HandIcon: React.FC<{ closed: boolean }> = ({ closed }) => (
  <svg width="40" height="40" viewBox="0 0 40 40" style={{ display: "block", translate: "-14px -10px" }}>
    {closed ? (
      <path
        d="M10 16 C10 13 14 13 14 16 L14 15 C14 12 18 12 18 15 L18 14.5 C18 11.5 22 11.5 22 14.5 L22 15.5 C22 12.5 26 12.5 26 15.5 L26 24 C26 31 22 35 17 35 C12 35 9 32 8 28 L6.5 22 C6 20 8.5 19 9.5 21 L10 22 Z"
        fill="#ffffff"
        stroke="#0a0b0d"
        strokeWidth="2"
        strokeLinejoin="round"
      />
    ) : (
      <path
        d="M10 18 L10 9 C10 6.5 13.5 6.5 13.5 9 L13.5 16 L13.5 6.5 C13.5 4 17 4 17 6.5 L17 16 L17 7.5 C17 5 20.5 5 20.5 7.5 L20.5 16.5 L20.5 10 C20.5 7.5 24 7.5 24 10 L24 24 C24 31 20.5 35 15.5 35 C11 35 8.5 32.5 7 28.5 L4.5 21.5 C3.8 19.5 6.5 18 7.8 20 Z"
        fill="#ffffff"
        stroke="#0a0b0d"
        strokeWidth="2"
        strokeLinejoin="round"
      />
    )}
  </svg>
);
