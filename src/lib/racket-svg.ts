/**
 * String version of the racket illustration, for places that need raw SVG
 * markup (Open Graph images, emails). Mirrors components/racket/RacketIllustration.
 */
import type { RacketShape, RacketVisual } from "@/domain/types";
import { buildBlueprint, DIMS, type Vec2 } from "@/lib/racket-geometry";

const X = (x: number) => (x * 1000 + 140).toFixed(2);
const Y = (y: number) => ((0.468 - y) * 1000).toFixed(2);
const path = (poly: Vec2[]) => `M${poly.map(([x, y]) => `${X(x)} ${Y(y)}`).join("L")}Z`;
const circle = (x: number, y: number, r: number) => {
  const rr = r * 1000;
  return `M${(x * 1000 + 140 - rr).toFixed(2)} ${Y(y)}a${rr} ${rr} 0 1 0 ${rr * 2} 0a${rr} ${rr} 0 1 0 ${-rr * 2} 0Z`;
};

export function racketSvgMarkup(shape: RacketShape, visual: RacketVisual): string {
  const bp = buildBlueprint(shape, visual, { samples: 48 });
  const holes = bp.holes.map((h) => circle(h.x, h.y, h.r)).join("");
  const gripRx = (DIMS.handle.rx + 0.0013) * 1000;
  const gripTop = Number(Y(DIMS.neckBottom - 0.016));
  const gripBottom = Number(Y(DIMS.cap.y1));
  const decals = bp.decals
    .map(
      (d) =>
        `<path d="${path(d.polygon)}${d.inner ? path(d.inner) : ""}${d.holes.map((k) => circle(bp.holes[k].x, bp.holes[k].y, bp.holes[k].r)).join("")}" fill="${d.tone === "accent" ? visual.accent : visual.accent2}" fill-rule="evenodd"/>`,
    )
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 480" width="280" height="480">
<rect x="${140 - gripRx}" y="${gripTop}" width="${gripRx * 2}" height="${gripBottom - gripTop}" rx="4" fill="${visual.grip}"/>
<path d="${path(bp.face)}${holes}" fill="${visual.face}" fill-rule="evenodd"/>
${decals}
<path d="${path(bp.frameOuter)}${path(bp.face)}${path(bp.heart)}" fill="${visual.frame}" fill-rule="evenodd"/>
<path d="${path(bp.bumper)}" fill="#2a2e35" fill-opacity="0.85"/>
<path d="${path(bp.frameOuter)}" fill="none" stroke="#ffffff" stroke-opacity="0.18" stroke-width="1"/>
</svg>`;
}

export function racketSvgDataUri(shape: RacketShape, visual: RacketVisual): string {
  return `data:image/svg+xml;base64,${Buffer.from(racketSvgMarkup(shape, visual)).toString("base64")}`;
}
