/**
 * Analytics abstraction. Components call track(); providers decide where
 * events go. Configure with NEXT_PUBLIC_ANALYTICS_PROVIDER:
 *   none | console | first-party | plausible
 * No cookies, no identifiers. Visitors with Global Privacy Control enabled
 * are never tracked.
 */
export const ANALYTICS_EVENTS = [
  "racket_viewed",
  "viewer_opened",
  "model_loaded",
  "model_failed",
  "viewer_fullscreen",
  "viewer_reset",
  "view_changed",
  "annotation_opened",
  "hotspot_selected",
  "overlay_enabled",
  "explode_toggled",
  "comparison_started",
  "comparison_completed",
  "comparison_sync_used",
  "finder_started",
  "finder_completed",
  "affiliate_clicked",
  "search_performed",
  "filter_used",
  "showroom_opened",
  "showroom_model_selected",
] as const;
export type AnalyticsEvent = (typeof ANALYTICS_EVENTS)[number];
export type EventProps = Record<string, string | number | boolean>;

interface Provider {
  send(name: AnalyticsEvent, props: EventProps, path: string): void;
}

const consoleProvider: Provider = {
  send: (name, props) => console.info(`[analytics] ${name}`, props),
};

/** Batches events and posts them to /api/events (stored in the local database). */
function firstPartyProvider(): Provider {
  let queue: Array<{ name: string; props: EventProps; path: string }> = [];
  let timer: ReturnType<typeof setTimeout> | null = null;
  const flush = () => {
    if (!queue.length) return;
    const body = JSON.stringify({ events: queue.splice(0, 20) });
    queue = [];
    const ok = typeof navigator.sendBeacon === "function" && navigator.sendBeacon("/api/events", new Blob([body], { type: "application/json" }));
    if (!ok) fetch("/api/events", { method: "POST", body, headers: { "content-type": "application/json" }, keepalive: true }).catch(() => {});
  };
  if (typeof window !== "undefined") {
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && flush());
  }
  return {
    send(name, props, path) {
      queue.push({ name, props, path });
      if (timer) clearTimeout(timer);
      timer = setTimeout(flush, 1500);
    },
  };
}

const plausibleProvider: Provider = {
  send(name, props) {
    const w = window as unknown as { plausible?: (n: string, o: { props: EventProps }) => void };
    w.plausible?.(name, { props });
  },
};

let provider: Provider | null | undefined;

function getProvider(): Provider | null {
  if (provider !== undefined) return provider;
  const kind = process.env.NEXT_PUBLIC_ANALYTICS_PROVIDER ?? (process.env.NODE_ENV === "development" ? "console" : "none");
  provider =
    kind === "first-party" ? firstPartyProvider() : kind === "plausible" ? plausibleProvider : kind === "console" ? consoleProvider : null;
  return provider;
}

function trackingAllowed(): boolean {
  if (typeof navigator === "undefined") return false;
  const nav = navigator as Navigator & { globalPrivacyControl?: boolean };
  return nav.globalPrivacyControl !== true;
}

export function track(name: AnalyticsEvent, props: EventProps = {}): void {
  try {
    if (typeof window === "undefined" || !trackingAllowed()) return;
    getProvider()?.send(name, props, window.location.pathname);
  } catch {
    // Analytics must never break the page.
  }
}
