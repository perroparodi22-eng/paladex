"use client";
/**
 * Card-level 3D preview. Shows the poster by default; on desktop hover it
 * mounts a live, auto-rotating preview model (only one card is live at a
 * time, so the page never holds more than one extra WebGL context). On any
 * device, "View in 3D" opens a quick-view dialog with the full viewer.
 */
import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ModelStatus, RacketShape, RacketVisual } from "@/domain/types";
import { MODEL_STATUS_INFO } from "@/domain/vocab";
import { RacketPoster } from "@/components/racket/RacketPoster";
import { Dialog } from "@/components/ui/Dialog";
import { Icon } from "@/components/ui/Icon";
import { Racket3DViewer } from "./Racket3DViewer";
import { hasWebGL } from "./webgl";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/cn";

export interface PreviewRacket {
  slug: string;
  fullName: string;
  shape: RacketShape;
  visual: RacketVisual;
  imageUrl: string | null;
  imageAlt: string;
  modelStatus: ModelStatus;
  modelUrl: string | null;
  modelPreviewUrl: string | null;
}

// One live preview at a time across the page.
let activeSlug: string | null = null;
const listeners = new Set<() => void>();
const setActive = (s: string | null) => {
  activeSlug = s;
  listeners.forEach((l) => l());
};
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export function Racket3DPreview({ racket, className, priority = false }: { racket: PreviewRacket; className?: string; priority?: boolean }) {
  const active = useSyncExternalStore(subscribe, () => activeSlug, () => null);
  const [quick, setQuick] = useState(false);
  const timer = useRef<number | null>(null);
  const interactive = MODEL_STATUS_INFO[racket.modelStatus].interactive && !!(racket.modelPreviewUrl || racket.modelUrl);
  const live = active === racket.slug;
  const viewerRacket = {
    slug: racket.slug,
    fullName: racket.fullName,
    shape: racket.shape,
    visual: racket.visual,
    imageUrl: racket.imageUrl,
    imageAlt: racket.imageAlt,
    model: interactive
      ? { status: racket.modelStatus, url: racket.modelUrl, previewUrl: racket.modelPreviewUrl, posterUrl: null, supportsExplode: false }
      : null,
  };

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
      if (activeSlug === racket.slug) setActive(null);
    },
    [racket.slug],
  );

  // Hover is detected on the whole card ([data-preview-host]) so stretched links above the stage don't block it.
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const host = (root.current?.closest("[data-preview-host]") as HTMLElement | null) ?? root.current;
    if (!host || !interactive) return;
    const canHover = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (!canHover) return;
    const enter = () => {
      if (!hasWebGL()) return;
      timer.current = window.setTimeout(() => setActive(racket.slug), 220);
    };
    const leave = () => {
      if (timer.current) window.clearTimeout(timer.current);
      if (activeSlug === racket.slug) setActive(null);
    };
    host.addEventListener("pointerenter", enter);
    host.addEventListener("pointerleave", leave);
    return () => {
      host.removeEventListener("pointerenter", enter);
      host.removeEventListener("pointerleave", leave);
    };
  }, [interactive, racket.slug]);

  return (
    <div ref={root} className={className ?? "relative"}>
      {live ? (
        <Racket3DViewer racket={viewerRacket} variant="compact" loadStrategy="eager" stage={false} className="absolute inset-0" />
      ) : (
        <RacketPoster racket={racket} priority={priority} className="absolute inset-0 p-4" sizes="(max-width: 640px) 70vw, (max-width: 1024px) 40vw, 300px" />
      )}
      {interactive && (
        <button
          type="button"
          onClick={() => {
            setQuick(true);
            track("viewer_opened", { slug: racket.slug, variant: "quick-view" });
          }}
          className="btn btn-secondary btn-sm absolute bottom-3 right-3 z-30 opacity-100 transition-opacity sm:opacity-0 sm:focus-visible:opacity-100 sm:group-hover/card:opacity-100"
        >
          <Icon name="cube" size={16} /> View in 3D
        </button>
      )}
      {quick && (
        <Dialog open={quick} onClose={() => setQuick(false)} title={racket.fullName} variant="center" className="w-[min(96vw,1100px)]">
          <div className="relative h-[min(72dvh,720px)]">
            <Racket3DViewer racket={viewerRacket} variant="page" loadStrategy="eager" className="absolute inset-0" />
          </div>
          <div className="flex items-center justify-between gap-3 border-t border-ink/10 px-5 py-3">
            <p className="text-sm text-ink-2">{MODEL_STATUS_INFO[racket.modelStatus].label}</p>
            <Link href={`/rackets/${racket.slug}`} className="btn btn-primary btn-sm">
              Full details <Icon name="arrowRight" size={16} />
            </Link>
          </div>
        </Dialog>
      )}
    </div>
  );
}
