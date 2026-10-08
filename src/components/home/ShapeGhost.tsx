/**
 * Two racket silhouettes overlaid at the butt cap, the same alignment the 3D
 * overlay comparison uses, to show how shape moves the sweet spot.
 */
import type { RacketShape } from "@/domain/types";
import { buildBlueprint, DIMS, type Vec2 } from "@/lib/racket-geometry";

const X = (x: number) => (x * 1000 + 140).toFixed(1);
const Y = (y: number) => ((0.468 - y) * 1000).toFixed(1);
const path = (poly: Vec2[]) => `M${poly.map(([x, y]) => `${X(x)} ${Y(y)}`).join("L")}Z`;
const box = (rx: number, y0: number, y1: number): Vec2[] => [[-rx, y0], [rx, y0], [rx, y1], [-rx, y1]];
const A = "var(--color-court)";
const B = "var(--color-series-2)";

export function ShapeGhost({ a, b, labelA, labelB }: { a: RacketShape; b: RacketShape; labelA: string; labelB: string }) {
  const pa = buildBlueprint(a, { pattern: "border", holes: "hex", bridge: false });
  const pb = buildBlueprint(b, { pattern: "border", holes: "hex", bridge: false });
  return (
    <figure className="relative">
      <svg viewBox="0 0 280 480" className="mx-auto h-[420px] w-auto max-w-full" role="img" aria-label={`${labelA} and ${labelB} outlines overlaid at the butt cap`}>
        {/* The handle and butt cap are the same for every shape: the shared anchor. */}
        <path d={path(box(DIMS.handle.rx, DIMS.handle.y0, DIMS.neckBottom))} fill="var(--color-surface-3)" stroke="var(--color-ink-3)" strokeWidth="1.2" />
        <path d={path(box(DIMS.cap.rx, DIMS.cap.y0, DIMS.cap.y1))} fill="var(--color-ink-3)" />
        <path d={path(pb.frameOuter)} fill={B} fillOpacity="0.08" stroke={B} strokeWidth="2.2" strokeDasharray="6 5" strokeLinejoin="round" />
        <path d={path(pa.frameOuter)} fill={A} fillOpacity="0.06" stroke={A} strokeWidth="2.4" strokeLinejoin="round" />
        <ellipse cx={X(0)} cy={Y(pa.sweetSpot.y)} rx={pa.sweetSpot.rx * 1000} ry={pa.sweetSpot.ry * 1000} fill={A} fillOpacity="0.1" stroke={A} strokeWidth="1.4" />
        <ellipse cx={X(0)} cy={Y(pb.sweetSpot.y)} rx={pb.sweetSpot.rx * 1000} ry={pb.sweetSpot.ry * 1000} fill="none" stroke={B} strokeWidth="1.4" strokeDasharray="3 3" />
      </svg>
      <figcaption className="mt-4 flex flex-wrap justify-center gap-4 text-sm">
        <span className="flex items-center gap-2">
          <span className="h-1 w-6 rounded-full bg-court" /> {labelA}
        </span>
        <span className="flex items-center gap-2">
          <span className="h-0.5 w-6 border-t-2 border-dashed border-series-2" /> {labelB}
        </span>
        <span className="text-ink-3">Ellipses: illustrative sweet spots</span>
      </figcaption>
    </figure>
  );
}
