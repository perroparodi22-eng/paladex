"use client";
/**
 * Racket3DComparison: 2–4 rackets in 3D.
 *  - Side by side: one viewer each on a shared SyncBus. Rotation and zoom can
 *    be synchronised or independent; view buttons drive every viewer at once.
 *  - Overlay: the first racket solid and another as a translucent ghost,
 *    aligned at the butt cap, to show shape and size differences.
 * On phones the side-by-side viewers stack vertically.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { CameraView, Racket } from "@/domain/types";
import { MODEL_STATUS_INFO, VIEW_INFO } from "@/domain/vocab";
import { Racket3DViewer } from "@/components/three/Racket3DViewer";
import { SyncBus } from "@/components/three/sync";
import type { ViewerCommand, ViewerCommandInput } from "@/components/three/types";
import { Icon } from "@/components/ui/Icon";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/cn";

const SERIES = ["#2343d6", "#f07a3e", "#11163a", "#0f9a83"];
const VIEWS: CameraView[] = ["hero", "front", "back", "edge", "top", "grip"];

export function Racket3DComparison({ rackets }: { rackets: Racket[] }) {
  const bus = useMemo(() => new SyncBus(), []);
  const [mode, setMode] = useState<"side" | "overlay">("side");
  const [syncRotation, setSyncRotation] = useState(true);
  const [syncZoom, setSyncZoom] = useState(true);
  const [command, setCommand] = useState<ViewerCommand | null>(null);
  const [ghostIndex, setGhostIndex] = useState(1);
  const nonce = useRef(0);
  const interactive = rackets.filter((r) => r.model && r.model.status !== "unavailable" && (r.model.previewUrl || r.model.url));

  useEffect(() => {
    bus.rotation = syncRotation;
    bus.zoom = syncZoom;
  }, [bus, syncRotation, syncZoom]);

  useEffect(() => {
    track("comparison_completed", { slugs: rackets.map((r) => r.slug).join(","), count: rackets.length });
  }, [rackets]);

  const send = (c: ViewerCommandInput) => {
    nonce.current += 1;
    setCommand({ ...c, nonce: nonce.current } as ViewerCommand);
  };

  const base = interactive[0];
  const ghostRacket = interactive[Math.min(ghostIndex, interactive.length - 1)];
  const ghost = useMemo(() => {
    if (!ghostRacket || ghostRacket.slug === base?.slug) return null;
    const url = ghostRacket.model?.previewUrl ?? ghostRacket.model?.url;
    return url ? { slug: ghostRacket.slug, url, color: SERIES[1] } : null;
  }, [ghostRacket, base]);

  const viewerRacket = (r: Racket) => ({
    slug: r.slug,
    fullName: r.fullName,
    shape: r.specs.shape,
    visual: r.visual,
    imageUrl: r.model?.posterUrl ?? r.imageUrl,
    imageAlt: r.imageAlt,
    model: r.model,
    overlays: r.overlays,
  });

  return (
    <div>
      {/* Toolbar */}
      <div className="plate mb-4 flex flex-col gap-3 p-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Comparison mode">
          <button type="button" className="chip" data-active={mode === "side"} aria-pressed={mode === "side"} onClick={() => setMode("side")}>
            <Icon name="grid" size={16} /> Side by side
          </button>
          <button
            type="button"
            className="chip"
            data-active={mode === "overlay"}
            aria-pressed={mode === "overlay"}
            disabled={interactive.length < 2}
            onClick={() => {
              setMode("overlay");
              track("comparison_sync_used", { mode: "overlay" });
            }}
          >
            <Icon name="ghost" size={16} /> Ghost overlay
          </button>
          {mode === "side" && (
            <>
              <span className="mx-1 hidden h-6 w-px bg-ink/10 sm:block" aria-hidden />
              <label className="chip cursor-pointer gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-court"
                  checked={syncRotation}
                  onChange={(e) => {
                    setSyncRotation(e.target.checked);
                    track("comparison_sync_used", { kind: "rotation", on: e.target.checked });
                  }}
                />
                Sync rotation
              </label>
              <label className="chip cursor-pointer gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-court"
                  checked={syncZoom}
                  onChange={(e) => {
                    setSyncZoom(e.target.checked);
                    track("comparison_sync_used", { kind: "zoom", on: e.target.checked });
                  }}
                />
                Sync zoom
              </label>
            </>
          )}
          {mode === "overlay" && interactive.length > 2 && (
            <label className="flex items-center gap-2 text-sm text-ink-2">
              Ghost:
              <select className="field h-9 min-h-9 w-auto py-0 text-sm" value={ghostIndex} onChange={(e) => setGhostIndex(Number(e.target.value))}>
                {interactive.slice(1).map((r, i) => (
                  <option key={r.slug} value={i + 1}>
                    {r.fullName}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <div className="no-scrollbar -mx-1 flex gap-1 overflow-x-auto px-1" role="toolbar" aria-label="Views for every racket">
          {VIEWS.map((v) => (
            <button key={v} type="button" className="chip shrink-0" onClick={() => send({ type: "view", view: v })}>
              {VIEW_INFO[v].label}
            </button>
          ))}
          <button type="button" className="chip shrink-0" onClick={() => send({ type: "reset" })} aria-label="Reset all views">
            <Icon name="reset" size={16} />
          </button>
        </div>
      </div>

      {mode === "side" ? (
        <ul className={cn("grid gap-3", rackets.length === 2 ? "sm:grid-cols-2" : rackets.length === 3 ? "sm:grid-cols-2 lg:grid-cols-3" : "sm:grid-cols-2 xl:grid-cols-4")}>
          {rackets.map((r, i) => (
            <li key={r.slug} className="relative overflow-hidden rounded-plate border border-ink/8">
              <div className="flex items-center gap-2 border-b border-ink/8 bg-surface px-3 py-2">
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SERIES[i] }} aria-hidden />
                <p className="min-w-0 flex-1 truncate text-sm font-semibold">{r.fullName}</p>
                <span className="text-[0.6875rem] text-ink-3">{MODEL_STATUS_INFO[r.model?.status ?? "unavailable"].badge}</span>
              </div>
              <div className="relative h-[52svh] min-h-[340px] lg:h-[60vh]">
                <Racket3DViewer
                  racket={viewerRacket(r)}
                  variant="compare"
                  loadStrategy="visible"
                  stage={false}
                  sync={{ bus, id: r.slug }}
                  command={command}
                  autoRotate={false}
                  className="absolute inset-0 stage-sky"
                />
              </div>
            </li>
          ))}
        </ul>
      ) : (
        base && (
          <div className="relative h-[70svh] min-h-[420px] overflow-hidden rounded-plate border border-ink/8">
            <Racket3DViewer racket={viewerRacket(base)} variant="page" loadStrategy="eager" ghost={ghost} command={command} className="absolute inset-0" />
            <div className="pointer-events-none absolute bottom-[132px] left-3 z-30 flex flex-col gap-1 text-sm">
              <span className="flex items-center gap-2 rounded-xl bg-surface/80 px-2 py-1">
                <span className="h-2.5 w-2.5 rounded-full bg-ink" aria-hidden /> {base.fullName} (solid)
              </span>
              {ghostRacket && ghostRacket.slug !== base.slug && (
                <span className="flex items-center gap-2 rounded-xl bg-surface/80 px-2 py-1">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: SERIES[1] }} aria-hidden /> {ghostRacket.fullName} (ghost, aligned at the butt cap)
                </span>
              )}
            </div>
          </div>
        )
      )}
      {interactive.length < rackets.length && (
        <p className="mt-3 text-sm text-ink-2">
          {rackets.length - interactive.length} of these rackets {rackets.length - interactive.length === 1 ? "has" : "have"} no 3D model yet, so an image is shown instead.
        </p>
      )}
    </div>
  );
}
