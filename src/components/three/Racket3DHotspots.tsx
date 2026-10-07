"use client";
/**
 * Hotspot pins on the model (positioned by the 3D projector through
 * data-anchor). Real buttons, reachable by keyboard and screen readers. The
 * chosen pin turns ball-lime and its caption opens as a lower third.
 */
import type { Hotspot } from "@/domain/types";
import { cn } from "@/lib/cn";

export function Racket3DHotspotPins({
  hotspots,
  visible,
  selected,
  onSelect,
}: {
  hotspots: Hotspot[];
  visible: boolean;
  selected: string | null;
  onSelect: (key: string | null) => void;
}) {
  if (!visible) return null;
  return (
    <>
      {hotspots.map((h, i) => {
        const on = selected === h.key;
        return (
          <div key={h.key} data-anchor={`hs:${h.key}`} className="anchor group">
            <button
              type="button"
              onClick={() => onSelect(on ? null : h.key)}
              aria-expanded={on}
              aria-label={`Hotspot ${i + 1}: ${h.label}`}
              className={cn(
                "relative grid h-8 w-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full text-[0.8125rem] font-bold shadow-[0_6px_16px_-6px_rgb(17_22_58/0.7)] transition-[transform,background-color,color] duration-300 [--rond:100] [transition-timing-function:var(--ease-spring)] hover:scale-110",
                on ? "scale-110 bg-ball text-ball-deep ring-2 ring-white/80" : "bg-court text-on-court",
              )}
            >
              {!on && <span aria-hidden className="absolute inset-0 rounded-full border-2 border-white/80 motion-safe:animate-[pulse-ring_2.6s_ease-out_infinite]" />}
              {i + 1}
            </button>
          </div>
        );
      })}
    </>
  );
}
