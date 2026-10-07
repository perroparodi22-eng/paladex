"use client";
/**
 * The viewer's control bar, kept to what anyone understands at a glance:
 * turn left, Front / Side / Back, turn right, reset, full screen.
 * Dragging the racket does the same as the arrows.
 */
import type { CameraView } from "@/domain/types";
import { Icon, type IconName } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

const TAU = Math.PI * 2;

export type Side = "front" | "edge" | "back";

/** Which face of the racket the camera is looking at, from its azimuth. */
export function sideAt(azimuth: number): Side {
  const a = ((azimuth % TAU) + TAU) % TAU;
  if (a < Math.PI / 4 || a > (7 * Math.PI) / 4) return "front";
  if (a > (3 * Math.PI) / 4 && a < (5 * Math.PI) / 4) return "back";
  return "edge";
}

const VIEWS: Array<{ view: CameraView; side: Side; label: string }> = [
  { view: "front", side: "front", label: "Front" },
  { view: "edge", side: "edge", label: "Side" },
  { view: "back", side: "back", label: "Back" },
];

function IconButton({ icon, label, onClick, pressed, className }: { icon: IconName; label: string; onClick: () => void; pressed?: boolean; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className={cn(
        "grid h-11 w-11 shrink-0 place-items-center rounded-full text-ink-2 transition-colors duration-200 hover:bg-white/8 hover:text-ink",
        pressed && "bg-white/10 text-ink",
        className,
      )}
    >
      <Icon name={icon} size={19} />
    </button>
  );
}

export function SimpleControls({
  side,
  view,
  fullscreen,
  autoRotate,
  reducedMotion,
  onTurn,
  onView,
  onReset,
  onFullscreen,
  onToggleAutoRotate,
}: {
  side: Side;
  view: CameraView | null;
  fullscreen: boolean;
  autoRotate: boolean;
  reducedMotion: boolean;
  onTurn: (dir: -1 | 1) => void;
  onView: (v: CameraView) => void;
  onReset: () => void;
  onFullscreen: () => void;
  onToggleAutoRotate: () => void;
}) {
  // Highlight the face in view: the chosen view, or the face the camera has turned to.
  const current: Side | null = view === "front" || view === "edge" || view === "back" ? (view as Side) : view && view !== "hero" ? null : side;
  return (
    <div
      className="flex items-center gap-0.5 rounded-full border border-white/10 bg-[#111317]/95 p-1 shadow-lift"
      role="toolbar"
      aria-label="3D viewer controls"
    >
      <IconButton icon="chevronLeft" label="Turn left" onClick={() => onTurn(-1)} />
      <div className="flex rounded-full bg-white/5 p-0.5" role="group" aria-label="Views">
        {VIEWS.map((v) => (
          <button
            key={v.view}
            type="button"
            onClick={() => onView(v.view)}
            aria-pressed={current === v.side}
            className={cn(
              "h-10 min-w-[3.4rem] rounded-full px-3 text-[0.8125rem] font-medium transition-colors duration-200",
              current === v.side ? "bg-court text-on-court" : "text-ink-2 hover:text-ink",
            )}
          >
            {v.label}
          </button>
        ))}
      </div>
      <IconButton icon="chevronRight" label="Turn right" onClick={() => onTurn(1)} />
      <span aria-hidden className="mx-0.5 hidden h-6 w-px bg-white/10 @md:block" />
      {!reducedMotion && (
        <IconButton icon={autoRotate ? "pause" : "play"} label={autoRotate ? "Stop turning" : "Turn slowly"} onClick={onToggleAutoRotate} pressed={autoRotate} className="hidden @md:grid" />
      )}
      <IconButton icon="reset" label="Reset view" onClick={onReset} className="hidden @md:grid" />
      <IconButton icon={fullscreen ? "fullscreenExit" : "fullscreen"} label={fullscreen ? "Exit full screen" : "Full screen"} onClick={onFullscreen} />
    </div>
  );
}

/** Small switch shown at the top of the viewer. */
export function ViewerToggle({ icon, label, on, onClick }: { icon: IconName; label: string; on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-full border px-3 text-[0.8125rem] font-medium transition-colors",
        on ? "border-court bg-court text-on-court" : "border-white/12 bg-[#111317]/95 text-ink-2 hover:text-ink",
      )}
    >
      <Icon name={icon} size={15} /> <span className="hidden @md:inline">{label}</span>
    </button>
  );
}
