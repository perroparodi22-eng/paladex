/**
 * Device-aware rendering quality. "auto" picks a tier from the device;
 * visitors can force "lite" or "high" from the viewer menu (remembered
 * locally). Lite mode also prefers the lightweight preview model.
 */
export type QualityTier = "lite" | "standard" | "high";
export type QualityPreference = "auto" | "lite" | "high";

export interface QualitySettings {
  tier: QualityTier;
  dpr: [number, number];
  antialias: boolean;
  shadows: boolean;
  envResolution: number;
  /** Load the full model after the preview (otherwise stay on the preview). */
  fullModel: boolean;
  /** Generate detail textures (carbon weave, face grain) after load. */
  detailTextures: boolean;
}

const KEY = "paladex:3d-quality";

export function readPreference(): QualityPreference {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "lite" || v === "high" ? v : "auto";
  } catch {
    return "auto";
  }
}

export function writePreference(p: QualityPreference) {
  try {
    if (p === "auto") window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, p);
  } catch {
    // ignore
  }
}

function detectTier(): QualityTier {
  if (typeof navigator === "undefined") return "standard";
  const nav = navigator as Navigator & { deviceMemory?: number; connection?: { saveData?: boolean; effectiveType?: string } };
  if (nav.connection?.saveData) return "lite";
  if (nav.connection?.effectiveType && /(^|-)2g|slow/.test(nav.connection.effectiveType)) return "lite";
  const cores = nav.hardwareConcurrency ?? 4;
  const memory = nav.deviceMemory ?? 4;
  const small = typeof window !== "undefined" && Math.min(window.screen.width, window.screen.height) < 500;
  if (cores <= 2 || memory <= 2) return "lite";
  if (small || cores <= 4 || memory <= 4) return "standard";
  return "high";
}

export function resolveQuality(pref: QualityPreference = "auto"): QualitySettings {
  const tier: QualityTier = pref === "lite" ? "lite" : pref === "high" ? "high" : detectTier();
  switch (tier) {
    case "lite":
      return { tier, dpr: [1, 1], antialias: false, shadows: false, envResolution: 32, fullModel: false, detailTextures: false };
    case "high":
      return { tier, dpr: [1, 1.5], antialias: true, shadows: true, envResolution: 256, fullModel: true, detailTextures: true };
    default:
      return { tier, dpr: [1, 1.25], antialias: true, shadows: true, envResolution: 128, fullModel: true, detailTextures: false };
  }
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}
