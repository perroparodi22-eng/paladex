/**
 * Front-view illustration of a racket, generated from the same geometry as
 * the placeholder 3D models (src/lib/racket-geometry). Used as the instant
 * poster before a model loads and as the fallback image without WebGL.
 * Server-rendered SVG: no JavaScript, crisp at any size.
 */
import { useId } from "react";
import type { RacketShape, RacketVisual } from "@/domain/types";
import { buildBlueprint, DIMS, type Vec2 } from "@/lib/racket-geometry";

const S = 1000; // metres -> SVG units (mm)
const X = (x: number) => +(x * S + 140).toFixed(2);
const Y = (y: number) => +((0.468 - y) * S).toFixed(2);
const path = (poly: Vec2[]) => `M${poly.map(([x, y]) => `${X(x)} ${Y(y)}`).join("L")}Z`;
const circle = (x: number, y: number, r: number) => {
  const rr = +(r * S).toFixed(2);
  return `M${X(x) - rr} ${Y(y)}a${rr} ${rr} 0 1 0 ${rr * 2} 0a${rr} ${rr} 0 1 0 ${-rr * 2} 0Z`;
};

export function RacketIllustration({
  shape,
  visual,
  title,
  className,
  shadow = true,
  sweetSpotScore = 7,
}: {
  shape: RacketShape;
  visual: RacketVisual;
  title?: string;
  className?: string;
  shadow?: boolean;
  sweetSpotScore?: number;
}) {
  const uid = useId().replace(/:/g, "");
  const bp = buildBlueprint(shape, visual, { samples: 56, sweetSpotScore });
  const holes = bp.holes.map((h) => circle(h.x, h.y, h.r)).join("");
  const h = DIMS.handle;
  const gripRx = (h.rx + 0.0013) * S;
  const gripTop = Y(DIMS.neckBottom - 0.016);
  const gripBottom = Y(DIMS.cap.y1);
  const seams: string[] = [];
  for (let y = gripBottom - 6; y > gripTop + 4; y -= 9) seams.push(`M${140 - gripRx} ${y + 5}L${140 + gripRx} ${y - 5}`);

  return (
    <svg viewBox="0 0 280 480" className={className} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      <defs>
        <linearGradient id={`fr-${uid}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.22" />
          <stop offset="0.35" stopColor="#ffffff" stopOpacity="0.04" />
          <stop offset="1" stopColor="#000000" stopOpacity="0.35" />
        </linearGradient>
        <radialGradient id={`fl-${uid}`} cx="0.45" cy="0.12" r="0.9">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.2" />
          <stop offset="0.55" stopColor="#ffffff" stopOpacity="0.03" />
          <stop offset="1" stopColor="#000000" stopOpacity="0.25" />
        </radialGradient>
        <linearGradient id={`gr-${uid}`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#000" stopOpacity="0.45" />
          <stop offset="0.45" stopColor="#fff" stopOpacity="0.12" />
          <stop offset="1" stopColor="#000" stopOpacity="0.5" />
        </linearGradient>
        <radialGradient id={`sh-${uid}`} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#000" stopOpacity="0.55" />
          <stop offset="1" stopColor="#000" stopOpacity="0" />
        </radialGradient>
      </defs>
      {shadow && <ellipse cx="140" cy="472" rx="60" ry="6" fill={`url(#sh-${uid})`} />}

      {/* Handle and grip. */}
      <rect x={140 - gripRx} y={gripTop} width={gripRx * 2} height={gripBottom - gripTop} rx="4" fill={visual.grip} />
      <path d={seams.join("")} stroke="#000" strokeOpacity="0.45" strokeWidth="1.2" fill="none" />
      <rect x={140 - gripRx} y={gripTop} width={gripRx * 2} height={gripBottom - gripTop} rx="4" fill={`url(#gr-${uid})`} />
      <rect x={140 - gripRx * 1.12} y={gripBottom - 1} width={gripRx * 2.24} height={(DIMS.cap.y1 - DIMS.cap.y0) * S + 2} rx="3" fill={visual.frame} />
      <rect x={140 - gripRx * 1.08} y={gripTop - 14} width={gripRx * 2.16} height="15" rx="2" fill={visual.frame} />

      {/* Face with real see-through holes. */}
      <path d={`${path(bp.face)}${holes}`} fill={visual.face} fillRule="evenodd" />
      {bp.decals.map((d, i) => (
        <path
          key={i}
          d={`${path(d.polygon)}${d.inner ? path(d.inner) : ""}${d.holes.map((k) => circle(bp.holes[k].x, bp.holes[k].y, bp.holes[k].r)).join("")}`}
          fill={d.tone === "accent" ? visual.accent : visual.accent2}
          fillRule="evenodd"
        />
      ))}
      <path d={`${path(bp.face)}${holes}`} fill={`url(#fl-${uid})`} fillRule="evenodd" />
      <path d={holes} fill="none" stroke="#000" strokeOpacity="0.5" strokeWidth="0.9" />

      {/* Frame with the throat opening. */}
      <path d={`${path(bp.frameOuter)}${path(bp.face)}${path(bp.heart)}`} fill={visual.frame} fillRule="evenodd" />
      <path d={`${path(bp.frameOuter)}${path(bp.face)}${path(bp.heart)}`} fill={`url(#fr-${uid})`} fillRule="evenodd" />
      {bp.bridge && <path d={path(bp.bridge)} fill={visual.frame} />}
      <path d={path(bp.bumper)} fill="#2a2e35" fillOpacity="0.85" />
      <path d={path(bp.frameOuter)} fill="none" stroke="#fff" strokeOpacity="0.14" strokeWidth="0.8" />
    </svg>
  );
}
