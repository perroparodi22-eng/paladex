"use client";
/**
 * Bridge between page content and the 3D viewer: a spec row can say "show
 * balance on the model" and the viewer moves its camera and enables the
 * overlay ("choosing a spec moves the camera, not the page").
 */
import { createContext, useCallback, useContext, useMemo, useRef, type ReactNode } from "react";
import type { CameraView, OverlayKind } from "@/domain/types";

export interface ViewerAction {
  view?: CameraView;
  overlays?: OverlayKind[];
  hotspot?: string;
  explode?: boolean;
}

interface BridgeValue {
  register: (fn: (a: ViewerAction) => void, el: HTMLElement | null) => () => void;
  act: (a: ViewerAction) => void;
}

const BridgeContext = createContext<BridgeValue | null>(null);

export function ViewerBridgeProvider({ children }: { children: ReactNode }) {
  const handler = useRef<((a: ViewerAction) => void) | null>(null);
  const element = useRef<HTMLElement | null>(null);
  const register = useCallback((fn: (a: ViewerAction) => void, el: HTMLElement | null) => {
    handler.current = fn;
    element.current = el;
    return () => {
      if (handler.current === fn) handler.current = null;
    };
  }, []);
  const act = useCallback((a: ViewerAction) => {
    const el = element.current;
    if (el) {
      const r = el.getBoundingClientRect();
      const visible = r.top < window.innerHeight * 0.7 && r.bottom > window.innerHeight * 0.25;
      if (!visible) el.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    }
    handler.current?.(a);
  }, []);
  const value = useMemo(() => ({ register, act }), [register, act]);
  return <BridgeContext.Provider value={value}>{children}</BridgeContext.Provider>;
}

export function useViewerBridge() {
  return useContext(BridgeContext);
}
