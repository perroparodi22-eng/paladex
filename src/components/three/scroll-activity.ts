/**
 * Page-scroll activity, shared by every 3D viewer on the page. While the page
 * is scrolling, viewers stop their idle animation (auto-turn, pointer lean) so
 * the GPU only has to composite the page, which keeps scrolling smooth. One
 * passive listener for the whole page; viewers resume when scrolling settles.
 */
const SETTLE_MS = 160;

let scrolling = false;
let timer: number | null = null;
let installed = false;
const settleListeners = new Set<() => void>();

function onScroll() {
  scrolling = true;
  if (timer !== null) window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    scrolling = false;
    timer = null;
    settleListeners.forEach((l) => l());
  }, SETTLE_MS);
}

function install() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("scroll", onScroll, { passive: true });
}

export function isPageScrolling(): boolean {
  return scrolling;
}

/** Calls `listener` each time scrolling comes to rest. Returns an unsubscribe function. */
export function onScrollSettle(listener: () => void): () => void {
  install();
  settleListeners.add(listener);
  return () => {
    settleListeners.delete(listener);
  };
}
