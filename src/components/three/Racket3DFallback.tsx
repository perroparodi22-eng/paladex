"use client";
/**
 * Honest fallback states. The poster image stays visible underneath; this
 * panel explains what is happening and offers the one useful action.
 */
import Link from "next/link";
import { Icon } from "@/components/ui/Icon";

export type FallbackKind = "nowebgl" | "unavailable" | "error" | "lost";

const COPY: Record<FallbackKind, { title: string; body: string }> = {
  nowebgl: {
    title: "3D isn't available on this device",
    body: "Your browser or device can't run interactive 3D (WebGL). You're seeing an image instead, and every spec below still applies.",
  },
  unavailable: {
    title: "3D model coming soon",
    body: "We don't have a 3D model of this racket yet, so you're seeing an image preview.",
  },
  error: {
    title: "The 3D model didn't load",
    body: "The model file couldn't be downloaded or read. Check your connection and try again.",
  },
  lost: {
    title: "3D view paused",
    body: "Your device paused 3D rendering to save memory. Restart it whenever you're ready.",
  },
};

export function Racket3DFallback({ kind, onRetry, compact = false }: { kind: FallbackKind; onRetry?: () => void; compact?: boolean }) {
  const c = COPY[kind];
  if (compact) {
    return (
      <div className="absolute left-3 top-3 z-40">
        <span className="badge bg-surface/90 shadow-soft">
          <Icon name={kind === "unavailable" ? "image" : "warning"} size={12} />
          {kind === "unavailable" ? "3D coming soon" : kind === "nowebgl" ? "Image preview" : "3D unavailable"}
        </span>
      </div>
    );
  }
  return (
    <div className="absolute inset-x-3 bottom-3 z-40 sm:inset-x-auto sm:bottom-4 sm:left-4 sm:max-w-sm" role={kind === "error" ? "alert" : "status"}>
      <div className="plate p-5">
        <p className="title flex items-center gap-2 text-lg text-ink">
          <Icon name={kind === "unavailable" ? "image" : "warning"} size={16} className={kind === "error" ? "text-danger" : "text-ink-2"} />
          {c.title}
        </p>
        <p className="mt-1.5 text-sm text-ink-2">{c.body}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {(kind === "error" || kind === "lost") && onRetry && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
              <Icon name="reset" size={16} /> {kind === "lost" ? "Restart 3D" : "Try again"}
            </button>
          )}
          <Link href="/legal/3d-assets" className="btn btn-ghost btn-sm">
            About our 3D models
          </Link>
        </div>
      </div>
    </div>
  );
}
