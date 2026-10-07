"use client";
/**
 * Viewer controls. Every button performs a real camera or scene action, and
 * each one has a keyboard shortcut (listed in the help popover).
 */
import type { CameraView, OverlayConfig, OverlayKind } from "@/domain/types";
import { BASIS_INFO, OVERLAY_INFO, VIEW_INFO } from "@/domain/vocab";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Popover } from "@/components/ui/Popover";
import { cn } from "@/lib/cn";
import { LIGHTING_LABELS, type LightingPreset } from "./types";
import type { QualityPreference } from "./quality";

export interface ControlsState {
  autoRotate: boolean;
  view: CameraView | null;
  hotspotsOn: boolean;
  hasHotspots: boolean;
  overlays: OverlayConfig[];
  active: OverlayKind[];
  canExplode: boolean;
  explode: boolean;
  lighting: LightingPreset;
  quality: QualityPreference;
  fullscreen: boolean;
  reducedMotion: boolean;
}

export interface ControlsHandlers {
  onToggleAutoRotate: () => void;
  onReset: () => void;
  onZoom: (step: number) => void;
  onView: (v: CameraView) => void;
  onToggleHotspots: () => void;
  onToggleOverlay: (k: OverlayKind) => void;
  onToggleExplode: () => void;
  onLighting: (p: LightingPreset) => void;
  onQuality: (q: QualityPreference) => void;
  onFullscreen: () => void;
  onCompare?: () => void;
}

const VIEWS: CameraView[] = ["hero", "front", "back", "edge", "top", "grip", "detail"];

function ToolButton({
  icon,
  label,
  onClick,
  pressed,
  shortcut,
  className,
}: {
  icon: IconName;
  label: string;
  onClick: () => void;
  pressed?: boolean;
  shortcut?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={shortcut ? `${label} (${shortcut})` : label}
      title={shortcut ? `${label} · ${shortcut}` : label}
      aria-pressed={pressed}
      className={cn(
        "grid h-11 w-11 shrink-0 place-items-center rounded-full text-ink-2 transition-colors hover:bg-ink/6 hover:text-ink",
        pressed && "bg-court-tint text-court-deep",
        className,
      )}
    >
      <Icon name={icon} size={20} />
    </button>
  );
}

export function Racket3DControls({ state, on, variant }: { state: ControlsState; on: ControlsHandlers; variant: "full" | "minimal" }) {
  if (variant === "minimal") {
    return (
      <div className="plate absolute bottom-3 right-3 z-30 flex gap-0.5 rounded-full p-1" role="toolbar" aria-label="3D viewer controls">
        <ToolButton icon="reset" label="Reset view" onClick={on.onReset} shortcut="R" />
        <ToolButton icon="zoomOut" label="Zoom out" onClick={() => on.onZoom(-1)} shortcut="−" className="hidden sm:grid" />
        <ToolButton icon="zoomIn" label="Zoom in" onClick={() => on.onZoom(1)} shortcut="+" className="hidden sm:grid" />
        {!state.reducedMotion && (
          <ToolButton
            icon={state.autoRotate ? "pause" : "play"}
            label={state.autoRotate ? "Stop auto-rotate" : "Auto-rotate"}
            onClick={on.onToggleAutoRotate}
            pressed={state.autoRotate}
            shortcut="A"
          />
        )}
        <ToolButton icon={state.fullscreen ? "fullscreenExit" : "fullscreen"} label={state.fullscreen ? "Exit full screen" : "Full screen"} onClick={on.onFullscreen} />
      </div>
    );
  }

  return (
    <div className="absolute inset-x-0 bottom-0 z-30 flex flex-col gap-2 p-2 sm:p-3">
      {/* Camera views: the staged thresholds, from full racket to detail. */}
      <div className="no-scrollbar -mx-2 flex gap-1 overflow-x-auto px-2 sm:mx-0 sm:px-0" role="toolbar" aria-label="Camera views">
        {VIEWS.map((v) => (
          <button
            key={v}
            type="button"
            className="chip shrink-0 bg-surface/70"
            data-active={state.view === v}
            aria-pressed={state.view === v}
            onClick={() => on.onView(v)}
            title={`${VIEW_INFO[v].label} · ${VIEW_INFO[v].shortcut}`}
          >
            {VIEW_INFO[v].label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1 rounded-plate border border-ink/10 bg-surface/80 p-1" role="toolbar" aria-label="3D viewer controls">
        <ToolButton icon="reset" label="Reset view" onClick={on.onReset} shortcut="R" />
        <ToolButton icon="zoomOut" label="Zoom out" onClick={() => on.onZoom(-1)} shortcut="−" />
        <ToolButton icon="zoomIn" label="Zoom in" onClick={() => on.onZoom(1)} shortcut="+" />
        {!state.reducedMotion && (
          <ToolButton
            icon={state.autoRotate ? "pause" : "play"}
            label={state.autoRotate ? "Stop auto-rotate" : "Auto-rotate"}
            onClick={on.onToggleAutoRotate}
            pressed={state.autoRotate}
            shortcut="A"
          />
        )}
        <span className="mx-1 hidden h-6 w-px bg-ink/10 sm:block" aria-hidden />
        {state.hasHotspots && (
          <ToolButton icon={state.hotspotsOn ? "eye" : "eyeOff"} label={state.hotspotsOn ? "Hide hotspots" : "Show hotspots"} onClick={on.onToggleHotspots} pressed={state.hotspotsOn} shortcut="H" />
        )}
        {state.overlays.length > 0 && (
          <Popover
            label="Technical overlays"
            side="top"
            align="center"
            triggerClassName={cn(
              "grid h-11 w-11 place-items-center rounded-xl text-ink-2 hover:bg-ink/8 hover:text-ink",
              state.active.length > 0 && "bg-court/20 text-ink ring-1 ring-court/70",
            )}
            trigger={() => <Icon name="layers" />}
            panelClassName="w-72"
          >
            {() => (
              <div className="p-1">
                <p className="label px-2 pb-2 pt-1">Overlays</p>
                {state.overlays
                  .filter((o) => o.kind !== "material-layers")
                  .map((o) => (
                    <label key={o.kind} className="flex cursor-pointer items-start gap-3 rounded-xl px-2 py-2 hover:bg-ink/5">
                      <input type="checkbox" className="mt-1 h-4 w-4 accent-court" checked={state.active.includes(o.kind)} onChange={() => on.onToggleOverlay(o.kind)} />
                      <span className="min-w-0">
                        <span className="block text-sm font-semibold text-ink">{OVERLAY_INFO[o.kind].label}</span>
                        <span className="block text-xs text-ink-2">{OVERLAY_INFO[o.kind].description}</span>
                        <span className="mt-1 inline-block text-[0.6875rem] font-semibold text-ink-3">{BASIS_INFO[o.basis].label}</span>
                      </span>
                    </label>
                  ))}
              </div>
            )}
          </Popover>
        )}
        {state.canExplode && (
          <ToolButton icon="explode" label={state.explode ? "Reassemble" : "Show material layers (illustrative)"} onClick={on.onToggleExplode} pressed={state.explode} shortcut="X" />
        )}
        <Popover
          label="Lighting and quality"
          side="top"
          align="end"
          triggerClassName="grid h-11 w-11 place-items-center rounded-xl text-ink-2 hover:bg-ink/8 hover:text-ink"
          trigger={() => <Icon name="light" />}
          panelClassName="w-64"
        >
          {(close) => (
            <div className="p-1">
              <p className="label px-2 pb-1 pt-1">Lighting</p>
              {(Object.keys(LIGHTING_LABELS) as LightingPreset[]).map((p) => (
                <button
                  key={p}
                  type="button"
                  className="flex w-full items-center justify-between rounded-xl px-2 py-2 text-left text-sm hover:bg-ink/5"
                  aria-pressed={state.lighting === p}
                  onClick={() => {
                    on.onLighting(p);
                    close();
                  }}
                >
                  {LIGHTING_LABELS[p]}
                  {state.lighting === p && <Icon name="check" size={16} className="text-court" />}
                </button>
              ))}
              <p className="label px-2 pb-1 pt-3">Rendering quality</p>
              {(["auto", "lite", "high"] as QualityPreference[]).map((q) => (
                <button
                  key={q}
                  type="button"
                  className="flex w-full items-center justify-between rounded-xl px-2 py-2 text-left text-sm hover:bg-ink/5"
                  aria-pressed={state.quality === q}
                  onClick={() => {
                    on.onQuality(q);
                    close();
                  }}
                >
                  {q === "auto" ? "Automatic" : q === "lite" ? "Lite (saves battery and data)" : "High detail"}
                  {state.quality === q && <Icon name="check" size={16} className="text-court" />}
                </button>
              ))}
            </div>
          )}
        </Popover>
        <Popover
          label="Keyboard shortcuts"
          side="top"
          align="end"
          className="hidden sm:block"
          triggerClassName="grid h-11 w-11 place-items-center rounded-xl text-ink-2 hover:bg-ink/8 hover:text-ink"
          trigger={() => <Icon name="keyboard" />}
          panelClassName="w-64"
        >
          {() => (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 p-3 text-sm">
              {[
                ["← → ↑ ↓", "Rotate"],
                ["+ / −", "Zoom"],
                ["R", "Reset"],
                ["1 F B E T G D", "Views"],
                ["A", "Auto-rotate"],
                ["H", "Hotspots"],
                ["X", "Material layers"],
                ["Esc", "Exit full screen"],
              ].map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="num text-ink">{k}</dt>
                  <dd className="text-ink-2">{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </Popover>
        <span className="flex-1" />
        {on.onCompare && (
          <button type="button" className="btn btn-ghost btn-sm hidden sm:inline-flex" onClick={on.onCompare}>
            <Icon name="compare" size={16} /> Compare
          </button>
        )}
        <ToolButton icon={state.fullscreen ? "fullscreenExit" : "fullscreen"} label={state.fullscreen ? "Exit full screen" : "Full screen"} onClick={on.onFullscreen} />
      </div>
    </div>
  );
}
