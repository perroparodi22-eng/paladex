"use client";
/**
 * Racket3DViewer: the reusable interactive 3D viewer.
 *
 * Loading strategy (progressive):
 *   1. poster (product photo or generated illustration), server-rendered
 *   2. lightweight preview model when the viewer is visible / requested
 *   3. full-detail model after the visitor interacts (or when idle on a good connection)
 *   4. optional surface-grain detail textures on high-end devices
 * three.js and the model loader are imported on demand, never in the page bundle.
 */
import dynamic from "next/dynamic";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { Annotation, CameraView, Hotspot, Model3D, OverlayConfig, OverlayKind, RacketShape, RacketVisual, SurfaceFinish } from "@/domain/types";
import { MODEL_STATUS_INFO, OVERLAY_INFO, SHAPE_INFO, VIEW_INFO } from "@/domain/vocab";
import { RacketPoster } from "@/components/racket/RacketPoster";
import { ProvenanceBadge } from "@/components/racket/ProvenanceBadge";
import { Icon } from "@/components/ui/Icon";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/cn";
import type { LoadedModel } from "./model-loader";
import { prefersReducedMotion, readPreference, resolveQuality, writePreference, type QualityPreference } from "./quality";
import { forcedModelFailure, hasWebGL } from "./webgl";
import type { LightingPreset, RigApi, ViewerCommand, ViewerCommandInput } from "./types";
import type { SyncBus } from "./sync";
import { Racket3DControls } from "./Racket3DControls";
import { Racket3DHotspotPins } from "./Racket3DHotspots";
import { SimpleControls, ViewerToggle, sideAt, type Side } from "./SimpleControls";
import { Racket3DOverlayLabels } from "./Racket3DOverlay";
import { Racket3DLoadingState } from "./Racket3DLoadingState";
import { Racket3DFallback } from "./Racket3DFallback";
import { useViewerBridge, type ViewerAction } from "./ViewerBridge";

const ViewerScene = dynamic(() => import("./scene/ViewerScene"), { ssr: false });

export interface ViewerRacket {
  slug: string;
  fullName: string;
  shape: RacketShape;
  visual: RacketVisual;
  imageUrl: string | null;
  imageAlt: string;
  model: Pick<Model3D, "status" | "url" | "previewUrl" | "posterUrl" | "supportsExplode"> | null;
  hotspots?: Hotspot[];
  annotations?: Annotation[];
  overlays?: OverlayConfig[];
  surfaceFinish?: SurfaceFinish | null;
  /** 0..1 from balance and weight: how long a flicked racket keeps turning. */
  inertia?: number;
}

export type ViewerVariant = "page" | "hero" | "showroom" | "compact" | "compare";

type Phase = "idle" | "loading" | "ready" | "error" | "nowebgl" | "unavailable" | "lost";

export interface Racket3DViewerProps {
  racket: ViewerRacket;
  variant?: ViewerVariant;
  loadStrategy?: "eager" | "visible" | "interaction";
  stage?: boolean;
  autoRotate?: boolean;
  /** Ghost model (overlay comparison) is handled by Racket3DComparison. */
  sync?: { bus: SyncBus; id: string };
  command?: ViewerCommand | null;
  bridge?: boolean;
  priorityPoster?: boolean;
  onCompare?: () => void;
  className?: string;
  /** Called with the current camera view label for parent UIs. */
  onViewChange?: (v: CameraView | null) => void;
  /** A second racket drawn as a translucent ghost over this one (overlay comparison). */
  ghost?: { slug: string; url: string; color: string } | null;
  /** Start on a specific camera view (e.g. "edge" in a guide about balance). */
  initialView?: CameraView;
  /** Overlays switched on from the start. */
  initialOverlays?: OverlayKind[];
  /** Extra canvas area covered by the page's own content (e.g. the hero copy), in px. */
  frameInsets?: Partial<{ top: number; right: number; bottom: number; left: number }>;
  /** Distance of the top chrome (provenance badge) from the viewer's top edge, when a floating header covers it. */
  chromeTop?: number;
}

const HINT_KEY = "paladex:hint-seen";

export function Racket3DViewer({
  racket,
  variant = "page",
  loadStrategy = "visible",
  stage = variant === "hero" || variant === "showroom" || variant === "page",
  autoRotate: autoRotateDefault,
  sync,
  command: externalCommand,
  bridge = false,
  priorityPoster = false,
  onCompare,
  className,
  onViewChange,
  ghost = null,
  initialView = "hero",
  initialOverlays,
  frameInsets,
  chromeTop,
}: Racket3DViewerProps) {
  const descId = useId();
  const container = useRef<HTMLDivElement>(null);
  const [anchorLayer, setAnchorLayer] = useState<HTMLDivElement | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<number | null>(0);
  const [model, setModel] = useState<LoadedModel | null>(null);
  const [lod, setLod] = useState<"preview" | "full" | null>(null);
  const [modelKey, setModelKey] = useState(racket.slug);
  const [canvasShown, setCanvasShown] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [qualityPref, setQualityPref] = useState<QualityPreference>("auto");
  const quality = useMemo(() => resolveQuality(qualityPref), [qualityPref]);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [autoRotate, setAutoRotate] = useState(autoRotateDefault ?? (variant === "hero" || variant === "showroom" || variant === "compact"));
  const [explode, setExplode] = useState(false);
  const [active, setActive] = useState<OverlayKind[]>(initialOverlays ?? []);
  const [lighting, setLighting] = useState<LightingPreset>("dark");
  const [hotspotsOn, setHotspotsOn] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<CameraView | null>(initialView);
  const [command, setCommand] = useState<ViewerCommand | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [pseudoFull, setPseudoFull] = useState(false);
  const [engaged, setEngaged] = useState(false);
  const [interacted, setInteracted] = useState(false);
  const [showHint, setShowHint] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [anchorVersion, setAnchorVersion] = useState(0);
  const [inView, setInView] = useState(true);
  const [ghostModel, setGhostModel] = useState<LoadedModel | null>(null);
  const [side, setSide] = useState<Side>("front");
  const sideRef = useRef<Side>("front");
  const rig = useRef<RigApi | null>(null);
  const deckRef = useRef<HTMLDivElement>(null);
  const [deckH, setDeckH] = useState(0);
  const nonce = useRef(0);
  const loadStart = useRef(0);
  const alive = useRef(true);
  const loadingSlug = useRef<string | null>(null);

  const interactive = variant !== "compact";
  const isFull = fullscreen || pseudoFull;
  const hotspots = useMemo(() => racket.hotspots ?? [], [racket.hotspots]);
  const overlays = useMemo(() => racket.overlays ?? [], [racket.overlays]);
  const status = racket.model?.status ?? "unavailable";
  const fullUrl = racket.model?.url ?? null;
  const previewUrl = racket.model?.previewUrl ?? fullUrl;
  const usable = status !== "unavailable" && !!(fullUrl || previewUrl);
  const canExplode = !!racket.model?.supportsExplode && lod === "full" && !!model && model.parts.some((p) => p === "part_face_front");

  useEffect(() => {
    alive.current = true;
    setReducedMotion(prefersReducedMotion());
    setQualityPref(readPreference());
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (reducedMotion) setAutoRotate(false);
  }, [reducedMotion]);

  // Stop auto-rotation (and therefore rendering) while the viewer is off screen.
  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => setInView(entries.some((e) => e.isIntersecting)), { threshold: 0.05 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const issue = useCallback((c: ViewerCommandInput) => {
    nonce.current += 1;
    setCommand({ ...c, nonce: nonce.current } as ViewerCommand);
  }, []);

  /* ---------------------------------------------------------- loading */

  /**
   * `primary` marks the load the visitor is waiting for (the first model on
   * screen, or a racket switched in place): it drives the loading state and
   * progress, and its failure shows the error fallback. A background upgrade
   * from preview to full detail is not primary and fails silently.
   */
  const load = useCallback(
    async (which: "preview" | "full", slug: string, url: string | null, primary: boolean = which === "preview") => {
      if (!url) return;
      const target = forcedModelFailure() ? "/models/__missing__.glb" : url;
      if (primary) {
        loadingSlug.current = slug;
        setPhase((p) => (p === "ready" ? p : "loading"));
        setProgress(0);
        loadStart.current = performance.now();
      }
      try {
        const { loadRacketModel } = await import("./model-loader");
        const m = await loadRacketModel(target, (f) => {
          if (primary && alive.current) setProgress(f);
        });
        if (!alive.current || loadingSlug.current !== slug) return;
        setModel(m);
        setLod(which);
        setModelKey(slug);
        setPhase("ready");
        requestAnimationFrame(() => alive.current && setSwitching(false));
        track("model_loaded", { slug, lod: which, ms: Math.round(performance.now() - loadStart.current) });
      } catch {
        if (!alive.current || loadingSlug.current !== slug) return;
        setSwitching(false);
        if (primary) {
          setPhase("error");
          track("model_failed", { slug });
        }
      }
    },
    [],
  );

  const start = useCallback(() => {
    if (phase !== "idle") return;
    if (!usable) return setPhase("unavailable");
    if (!hasWebGL()) return setPhase("nowebgl");
    track("viewer_opened", { slug: racket.slug, variant });
    const first = quality.fullModel && variant === "page" && fullUrl && lodFirstFull() ? "full" : "preview";
    void load(first, racket.slug, first === "full" ? fullUrl : previewUrl, true);
  }, [phase, usable, racket.slug, variant, load, quality.fullModel, fullUrl, previewUrl]);

  // Racket switched in place (showroom): dim the lights, load, swap, light up.
  useEffect(() => {
    if (racket.slug === modelKey || phase === "idle") return;
    setSelected(null);
    setExplode(false);
    setActive([]);
    setView("hero");
    setLod(null);
    if (!usable) {
      setModel(null);
      setCanvasShown(false);
      setModelKey(racket.slug);
      setPhase("unavailable");
      return;
    }
    if (!model) setCanvasShown(false);
    setSwitching(true);
    void load("preview", racket.slug, previewUrl, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [racket.slug]);

  // Initial trigger.
  useEffect(() => {
    if (phase !== "idle") return;
    if (!usable) {
      setPhase("unavailable");
      return;
    }
    if (loadStrategy === "eager") {
      const id = window.requestIdleCallback ? window.requestIdleCallback(() => start(), { timeout: 600 }) : window.setTimeout(start, 120);
      return () => (window.cancelIdleCallback ? window.cancelIdleCallback(id as number) : window.clearTimeout(id as number));
    }
    if (loadStrategy === "visible" && container.current) {
      // Warm up well before the viewer scrolls into view, in idle time, so the one-off
      // cost (model download, shader compile, texture upload) never lands mid-scroll.
      let idleId: number | null = null;
      const io = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            io.disconnect();
            idleId = window.requestIdleCallback ? window.requestIdleCallback(() => start(), { timeout: 800 }) : window.setTimeout(start, 60);
          }
        },
        { rootMargin: "150% 0px" },
      );
      io.observe(container.current);
      return () => {
        io.disconnect();
        if (idleId !== null) (window.cancelIdleCallback ? window.cancelIdleCallback(idleId) : window.clearTimeout(idleId));
      };
    }
  }, [phase, usable, loadStrategy, start]);

  // Overlay comparison: load the ghost racket once the main one is on screen.
  useEffect(() => {
    if (!ghost || phase !== "ready") {
      setGhostModel(null);
      return;
    }
    let cancelled = false;
    void import("./model-loader")
      .then(({ loadRacketModel }) => loadRacketModel(ghost.url))
      .then((m) => !cancelled && alive.current && setGhostModel(m))
      .catch(() => !cancelled && setGhostModel(null));
    return () => {
      cancelled = true;
    };
  }, [ghost, phase]);

  // Watchdog: a model that loaded but never drew a frame (e.g. the browser refused
  // another WebGL context) falls back to the paused state instead of hanging.
  // Only visible time counts: a page opened in a background tab draws no frames
  // until the visitor switches to it, and that is not a failure.
  useEffect(() => {
    if (phase !== "ready" || !model || canvasShown) return;
    let visibleMs = 0;
    let last = performance.now();
    const t = window.setInterval(() => {
      const now = performance.now();
      if (document.visibilityState === "visible") visibleMs += now - last;
      last = now;
      if (visibleMs > 9000 && alive.current) {
        window.clearInterval(t);
        setPhase("lost");
      }
    }, 500);
    return () => window.clearInterval(t);
  }, [phase, model, canvasShown]);

  // Upgrade preview -> full detail on intent, or when idle on a good connection.
  useEffect(() => {
    if (phase !== "ready" || lod !== "preview" || !quality.fullModel || !fullUrl || fullUrl === previewUrl) return;
    if (interacted) {
      void load("full", racket.slug, fullUrl);
      return;
    }
    if (variant !== "page" && variant !== "showroom") return;
    const nav = navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } };
    if (nav.connection?.saveData || (nav.connection?.effectiveType && nav.connection.effectiveType !== "4g")) return;
    const t = window.setTimeout(() => void load("full", racket.slug, fullUrl), variant === "page" ? 1800 : 3500);
    return () => window.clearTimeout(t);
  }, [phase, lod, quality.fullModel, fullUrl, previewUrl, interacted, variant, racket.slug, load]);

  // External commands (comparison toolbar).
  useEffect(() => {
    if (!externalCommand) return;
    setCommand(externalCommand);
    if (externalCommand.type === "view") setView(externalCommand.view);
    if (externalCommand.type === "reset") setView("hero");
  }, [externalCommand]);

  useEffect(() => onViewChange?.(view), [view, onViewChange]);

  // Gesture hint, once per browser.
  useEffect(() => {
    if (phase !== "ready" || !interactive || variant === "compare") return;
    try {
      if (!window.localStorage.getItem(HINT_KEY)) setShowHint(true);
    } catch {
      setShowHint(true);
    }
  }, [phase, interactive, variant]);

  const markInteracted = useCallback(() => {
    if (!interacted) setInteracted(true);
    if (showHint) {
      setShowHint(false);
      try {
        window.localStorage.setItem(HINT_KEY, "1");
      } catch {
        // ignore
      }
    }
  }, [interacted, showHint]);

  // Camera angle stream from the scene: moves the scrubber's playhead directly
  // and only touches React state when the face in view changes.
  const onOrbit = useCallback((az: number) => {
    const next = sideAt(az);
    if (next !== sideRef.current) {
      sideRef.current = next;
      setSide(next);
    }
  }, []);

  /* --------------------------------------------------------- actions */

  const goView = useCallback(
    (v: CameraView) => {
      issue({ type: "view", view: v });
      setView(v);
      setAnnouncement(`${VIEW_INFO[v].label} view`);
      markInteracted();
      track("view_changed", { slug: racket.slug, view: v });
    },
    [issue, markInteracted, racket.slug],
  );

  const toggleOverlay = useCallback(
    (k: OverlayKind, force?: boolean) => {
      setActive((cur) => {
        const on = force ?? !cur.includes(k);
        if (on) track("overlay_enabled", { slug: racket.slug, kind: k });
        setAnnouncement(`${OVERLAY_INFO[k].label} overlay ${on ? "on" : "off"}`);
        return on ? [...new Set([...cur, k])] : cur.filter((x) => x !== k);
      });
      markInteracted();
    },
    [markInteracted, racket.slug],
  );

  const toggleFullscreen = useCallback(async () => {
    const el = container.current;
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
        return;
      }
      if (pseudoFull) {
        setPseudoFull(false);
        return;
      }
      if (el?.requestFullscreen && document.fullscreenEnabled) await el.requestFullscreen();
      else setPseudoFull(true);
      track("viewer_fullscreen", { slug: racket.slug });
    } catch {
      setPseudoFull((p) => !p);
    }
  }, [pseudoFull, racket.slug]);

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === container.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  useEffect(() => {
    if (!pseudoFull) return;
    document.documentElement.style.overflow = "hidden";
    return () => {
      document.documentElement.style.overflow = "";
    };
  }, [pseudoFull]);

  // Spec rows elsewhere on the page can drive this viewer.
  const bridgeCtx = useViewerBridge();
  useEffect(() => {
    if (!bridge || !bridgeCtx) return;
    return bridgeCtx.register((a: ViewerAction) => {
      if (phase === "idle") start();
      if (a.view) goView(a.view);
      if (a.overlays) for (const k of a.overlays) toggleOverlay(k, true);
      if (a.hotspot) {
        setHotspotsOn(true);
        setSelected(a.hotspot);
      }
      if (a.explode !== undefined) setExplode(a.explode);
    }, container.current);
  }, [bridge, bridgeCtx, phase, start, goView, toggleOverlay]);

  useEffect(() => setAnchorVersion((v) => v + 1), [hotspotsOn, active, model]);

  const onKey = (e: React.KeyboardEvent) => {
    if (!interactive || phase !== "ready") return;
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
    const step = Math.PI / 12;
    const map: Record<string, () => void> = {
      ArrowLeft: () => issue({ type: "rotate", azimuth: -step, polar: 0 }),
      ArrowRight: () => issue({ type: "rotate", azimuth: step, polar: 0 }),
      ArrowUp: () => issue({ type: "rotate", azimuth: 0, polar: -step / 1.5 }),
      ArrowDown: () => issue({ type: "rotate", azimuth: 0, polar: step / 1.5 }),
      "+": () => issue({ type: "zoom", step: 1 }),
      "=": () => issue({ type: "zoom", step: 1 }),
      "-": () => issue({ type: "zoom", step: -1 }),
      r: () => {
        issue({ type: "reset" });
        setView(initialView);
      },
      "0": () => {
        issue({ type: "reset" });
        setView(initialView);
      },
      "1": () => goView("hero"),
      f: () => goView("front"),
      b: () => goView("back"),
      e: () => goView("edge"),
      t: () => goView("top"),
      g: () => goView("grip"),
      d: () => goView("detail"),
      a: () => !reducedMotion && setAutoRotate((x) => !x),
      h: () => setHotspotsOn((x) => !x),
      x: () => canExplode && setExplode((x) => !x),
    };
    const fn = map[e.key] ?? map[e.key.toLowerCase()];
    if (fn && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      fn();
      markInteracted();
      if (e.key.startsWith("Arrow")) setView(null);
    } else if (e.key === "Escape") {
      if (selected) setSelected(null);
      else if (pseudoFull) setPseudoFull(false);
    }
  };

  const selectedIndex = hotspots.findIndex((h) => h.key === selected);
  const selectedHotspot = selectedIndex >= 0 ? hotspots[selectedIndex] : null;
  const showChrome = phase === "ready" && interactive;
  const statusLabel = MODEL_STATUS_INFO[status];

  // Measure the replay deck so the camera frames the racket above it.
  useEffect(() => {
    const el = deckRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setDeckH(Math.round(el.getBoundingClientRect().height)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [showChrome, variant]);
  const fi = frameInsets;
  const insets = useMemo(
    () => ({
      top: (variant === "page" || variant === "showroom" ? 64 : 0) + (fi?.top ?? 0),
      right: fi?.right ?? 0,
      // Below the racket: the control bar.
      bottom: (variant === "compare" ? 64 : variant === "compact" ? 0 : deckH ? deckH + 24 : 0) + (fi?.bottom ?? 0),
      left: fi?.left ?? 0,
    }),
    [variant, deckH, fi?.top, fi?.right, fi?.bottom, fi?.left],
  );

  return (
    <div
      ref={container}
      className={cn(
        "group/viewer @container isolate select-none overflow-hidden outline-offset-[-2px]",
        !/(^|\s)(absolute|fixed)(\s|$)/.test(className ?? "") && "relative",
        stage && (lighting === "light" ? "stage-light" : "stage-sky"),
        isFull && "!fixed inset-0 z-[100] h-dvh w-screen bg-ground",
        className,
      )}
      role="group"
      aria-roledescription="3D viewer"
      aria-label={`3D model of the ${racket.fullName}`}
      aria-describedby={descId}
      tabIndex={interactive ? 0 : -1}
      onKeyDown={onKey}
      onPointerEnter={() => loadStrategy === "interaction" && start()}
      onFocus={() => loadStrategy === "interaction" && start()}
      onPointerLeave={() => setEngaged(false)}
    >
      <p id={descId} className="sr-only">
        {racket.fullName}, {SHAPE_INFO[racket.shape].label.toLowerCase()} shape. {statusLabel.label}. {statusLabel.description}
        {interactive && " Use the arrow keys to rotate, plus and minus to zoom and R to reset. The buttons below the model switch between front, back, edge, top, grip and detail views."}
      </p>
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>

      {/* 1. Poster: visible until the first 3D frame, and as the fallback. */}
      <div className={cn("absolute inset-0 transition-opacity duration-700", canvasShown && phase === "ready" ? "opacity-0" : "opacity-100")} aria-hidden={phase === "ready"}>
        <RacketPoster
          racket={racket}
          priority={priorityPoster}
          sizes={variant === "compact" ? "(max-width: 768px) 45vw, 280px" : "(max-width: 768px) 100vw, 60vw"}
          className={variant === "compact" ? "p-4" : "p-[8%]"}
        />
      </div>

      {/* 2. WebGL canvas. */}
      {model && (phase === "ready" || phase === "loading") && (
        <div
          className={cn("absolute inset-0 transition-opacity duration-700", canvasShown ? "opacity-100" : "opacity-0")}
          onPointerDown={() => {
            setEngaged(true);
            markInteracted();
          }}
          onWheel={() => engaged && markInteracted()}
        >
          <ViewerScene
            model={model}
            modelKey={modelKey}
            quality={quality}
            reducedMotion={reducedMotion}
            interactive={interactive}
            autoRotate={autoRotate && inView && !isHidden()}
            explode={explode}
            activeOverlays={active}
            overlays={overlays}
            lighting={lighting}
            stage={stage}
            wheelZoom={isFull || engaged}
            fullscreen={isFull}
            initialView={initialView}
            command={command}
            hotspots={hotspotsOn ? hotspots : []}
            anchorLayer={anchorLayer}
            anchorVersion={anchorVersion}
            surfaceGrain={quality.detailTextures && lod === "full"}
            sync={sync}
            ghost={ghost && ghostModel ? { model: ghostModel, color: ghost.color } : null}
            onUserInteract={markInteracted}
            onFreeView={() => setView(null)}
            onContextLost={() => setPhase("lost")}
            onFirstFrame={() => setCanvasShown(true)}
            rig={rig}
            onOrbit={onOrbit}
            inertia={racket.inertia ?? 0.5}
            parallax={variant === "hero" || variant === "showroom"}
            insets={insets}
            lowAngle={variant === "hero"}
          />
        </div>
      )}

      {/* Lights dim while a different racket loads in place. */}
      <div
        aria-hidden
        className={cn("pointer-events-none absolute inset-0 z-[15] bg-ground transition-opacity", switching ? "opacity-75 duration-200" : "opacity-0 duration-500")}
      />

      {/* 3. Pinned HTML: hotspots and overlay labels. */}
      <div ref={setAnchorLayer} className="pointer-events-none absolute inset-0 z-20 [&_button]:pointer-events-auto">
        {phase === "ready" && canvasShown && (
          <>
            <Racket3DHotspotPins
              hotspots={hotspots}
              visible={hotspotsOn && interactive && !explode}
              selected={selected}
              onSelect={(k) => {
                setSelected(k);
                if (k) track("hotspot_selected", { slug: racket.slug, key: k });
              }}
            />
            <Racket3DOverlayLabels overlays={overlays} active={active} />
          </>
        )}
      </div>

      {/* 4. Top: where the model comes from (always), and two plain switches. */}
      <div
        className="pointer-events-none absolute inset-x-3 top-3 z-30 flex items-start justify-between gap-2 sm:inset-x-4 sm:top-4 [&_*]:pointer-events-auto"
        style={chromeTop !== undefined ? { top: chromeTop } : undefined}
      >
        <ProvenanceBadge status={status} />
        {showChrome && variant !== "compare" && variant !== "hero" && (
          <div className="flex flex-wrap justify-end gap-1.5">
            {hotspots.length > 0 && <ViewerToggle icon="info" label="Details" on={hotspotsOn} onClick={() => setHotspotsOn((x) => !x)} />}
            <ViewerToggle
              icon="light"
              label={lighting === "dark" ? "White studio" : "Black studio"}
              on={false}
              onClick={() => setLighting((l) => (l === "dark" ? "light" : "dark"))}
            />
          </div>
        )}
      </div>

      {explode && showChrome && (
        <p className="pointer-events-none absolute inset-x-0 top-16 z-30 text-center">
          <span className="badge badge-warn">Illustrative layers, not this racket&apos;s verified layup</span>
        </p>
      )}

      {/* 5. Bottom: the chosen detail, then the control bar. */}
      {showChrome && variant !== "compare" && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-30 flex flex-col items-center gap-2.5 p-3 sm:p-4 [&>*]:pointer-events-auto">
          {selectedHotspot && (
            <div className="plate relative w-full max-w-md p-4 pr-12" role="region" aria-label={selectedHotspot.label} aria-live="polite">
              <p className="title text-base">
                <span className="mr-2 inline-grid h-6 w-6 place-items-center rounded-full bg-court text-xs font-semibold text-on-court">{selectedIndex + 1}</span>
                {selectedHotspot.label}
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{selectedHotspot.body}</p>
              <button type="button" onClick={() => setSelected(null)} className="absolute right-2 top-2 grid h-9 w-9 place-items-center rounded-full text-ink-2 hover:bg-white/8 hover:text-ink" aria-label="Close">
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          <div ref={deckRef}>
            <SimpleControls
              side={side}
              view={view}
              fullscreen={isFull}
              autoRotate={autoRotate}
              reducedMotion={reducedMotion}
              onTurn={(dir) => {
                issue({ type: "rotate", azimuth: (dir * Math.PI) / 4, polar: 0 });
                setAutoRotate(false);
                setView(null);
                markInteracted();
              }}
              onView={(v) => {
                setAutoRotate(false);
                goView(v);
              }}
              onReset={() => {
                issue({ type: "reset" });
                setView(initialView);
                setSelected(null);
                track("viewer_reset", { slug: racket.slug });
              }}
              onFullscreen={() => void toggleFullscreen()}
              onToggleAutoRotate={() => setAutoRotate((x) => !x)}
            />
          </div>
        </div>
      )}

      {showChrome && variant === "compare" && (
        <Racket3DControls
          variant="minimal"
          state={{
            autoRotate,
            view,
            hotspotsOn,
            hasHotspots: hotspots.length > 0,
            overlays,
            active,
            canExplode,
            explode,
            lighting,
            quality: qualityPref,
            fullscreen: isFull,
            reducedMotion,
          }}
          on={{
            onToggleAutoRotate: () => setAutoRotate((x) => !x),
            onReset: () => {
              issue({ type: "reset" });
              setView(initialView);
              setSelected(null);
            },
            onZoom: (s) => {
              issue({ type: "zoom", step: s });
              markInteracted();
            },
            onView: goView,
            onToggleHotspots: () => setHotspotsOn((x) => !x),
            onToggleOverlay: (k) => toggleOverlay(k),
            onToggleExplode: () => setExplode((x) => !x),
            onLighting: setLighting,
            onQuality: (q) => {
              setQualityPref(q);
              writePreference(q);
            },
            onFullscreen: () => void toggleFullscreen(),
          }}
        />
      )}

      {(phase === "loading" || switching) && <Racket3DLoadingState progress={progress} label={switching ? "Switching racket" : "Loading 3D model"} />}

      {phase === "idle" && loadStrategy === "interaction" && usable && (
        <button type="button" onClick={start} className="btn btn-secondary absolute bottom-4 left-1/2 z-30 -translate-x-1/2">
          <Icon name="cube" size={18} /> View in 3D
        </button>
      )}

      {showHint && variant !== "compact" && (
        <div
          className="pointer-events-none absolute z-30 flex justify-center px-4"
          style={{ left: insets.left, right: insets.right, top: `calc(${insets.top}px + (100% - ${insets.top + insets.bottom}px) * 0.42)` }}
        >
          <span className="flex items-center gap-2.5 rounded-full border border-white/12 bg-[#111317]/95 px-4 py-2.5 text-sm font-medium text-ink shadow-lift [--rond:100]">
            <Icon name="hand" size={18} className="motion-safe:animate-[hint-drift_2.2s_ease-in-out_infinite]" />
            Drag to rotate
          </span>
        </div>
      )}

      {(phase === "nowebgl" || phase === "unavailable" || phase === "error" || phase === "lost") && (
        <Racket3DFallback
          kind={phase}
          compact={variant === "compact"}
          onRetry={() => {
            setModel(null);
            setCanvasShown(false);
            setPhase("loading");
            void load("preview", racket.slug, previewUrl);
          }}
        />
      )}
    </div>
  );
}

function isHidden(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

/** Desktop visitors on a fast connection get the full model straight away on product pages. */
function lodFirstFull(): boolean {
  if (typeof window === "undefined") return false;
  const nav = navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } };
  const fast = !nav.connection || (!nav.connection.saveData && (!nav.connection.effectiveType || nav.connection.effectiveType === "4g"));
  return fast && window.matchMedia("(min-width: 1024px) and (pointer: fine)").matches;
}
