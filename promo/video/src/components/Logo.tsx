// The Paladex mark (from the site's Logo.tsx): a racket face tilted into the shot,
// with the ball just hit off it. `hit` (0–1) animates the ball leaving the face.
import React from "react";
import { display } from "../theme";

export const LogoMark: React.FC<{ size?: number; hit?: number; style?: React.CSSProperties }> = ({ size = 64, hit = 1, style }) => (
  <svg viewBox="0 0 32 32" width={size} height={size} style={{ display: "block", overflow: "visible", ...style }} aria-hidden>
    <g transform="rotate(-18 15 17)">
      <rect x="13.1" y="21.5" width="3.8" height="9" rx="1.9" fill="#8b919c" />
      <ellipse cx="15" cy="12.6" rx="9.2" ry="10.4" fill="#eceef1" />
      <circle cx="11.6" cy="9.6" r="1.25" fill="#0a0b0d" />
      <circle cx="18.4" cy="9.6" r="1.25" fill="#0a0b0d" />
      <circle cx="15" cy="14.4" r="1.25" fill="#0a0b0d" />
    </g>
    <circle cx={19 + 6.4 * hit} cy={11 - 4.4 * hit} r={4.3 * (0.6 + 0.4 * hit)} fill="#d9f04a" opacity={Math.min(1, hit * 3)} />
  </svg>
);

export const Wordmark: React.FC<{ size?: number; style?: React.CSSProperties }> = ({ size = 64, style }) => (
  <span style={{ ...display, fontSize: size, lineHeight: 1, letterSpacing: "-0.03em", ...style }}>Paladex</span>
);
