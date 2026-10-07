import type { MutableRefObject } from "react";
import type { CameraView, OverlayConfig, OverlayKind } from "@/domain/types";
import type { LoadedModel } from "./model-loader";
import type { QualitySettings } from "./quality";
import type { SyncBus } from "./sync";

export type LightingPreset = "dark" | "light";

export const LIGHTING_LABELS: Record<LightingPreset, string> = {
  dark: "Black studio",
  light: "White studio",
};

/** Imperative handle on the camera, used by the replay scrubber. */
export interface RigApi {
  /** Turn to an absolute azimuth in radians (0 = front face, PI/2 = edge, PI = back). */
  setAzimuth: (azimuth: number, smooth: boolean) => void;
  /** Stop a coasting spin. */
  stop: () => void;
}

export type ViewerCommand =
  | { nonce: number; type: "view"; view: CameraView }
  | { nonce: number; type: "zoom"; step: number }
  | { nonce: number; type: "rotate"; azimuth: number; polar: number }
  | { nonce: number; type: "reset" };

/** A command without its nonce (distributes over the union so each variant keeps its fields). */
export type ViewerCommandInput = ViewerCommand extends infer T ? (T extends unknown ? Omit<T, "nonce"> : never) : never;

/** A point the DOM layer pins a label or hotspot button to. */
export interface Anchor {
  /** Matches data-anchor on the DOM element. */
  key: string;
  /** Model-space position (metres, before centring). */
  position: [number, number, number];
  /** Outward direction, used to dim anchors facing away from the camera. */
  normal: [number, number, number];
}

export interface HotspotAnchorInput {
  key: string;
  u: number;
  v: number;
  w: number;
}

export interface SceneProps {
  model: LoadedModel;
  /** Stable identity of the racket; the camera refits only when it changes. */
  modelKey: string;
  quality: QualitySettings;
  reducedMotion: boolean;
  interactive: boolean;
  autoRotate: boolean;
  explode: boolean;
  activeOverlays: OverlayKind[];
  overlays: OverlayConfig[];
  lighting: LightingPreset;
  /** Court, sky and sun around the racket (off for small cards). */
  stage: boolean;
  /** 0..1: how long a flicked racket keeps spinning (from its balance and weight). */
  inertia?: number;
  /** The racket leans toward the mouse pointer while idle (desktop hero and showroom). */
  parallax?: boolean;
  /** Receives the camera handle once the scene is ready. */
  rig?: MutableRefObject<RigApi | null>;
  /** Called with the camera azimuth whenever it changes (keep it cheap: no React state). */
  onOrbit?: (azimuth: number) => void;
  /** Open on the low hero shot instead of the standard three-quarter view. */
  lowAngle?: boolean;
  /** Pixels of the canvas covered by chrome; the racket is framed in the rest. */
  insets?: { top: number; right: number; bottom: number; left: number };
  wheelZoom: boolean;
  fullscreen: boolean;
  initialView: CameraView;
  command: ViewerCommand | null;
  hotspots: HotspotAnchorInput[];
  /** Container holding [data-anchor] elements to position. */
  anchorLayer: HTMLElement | null;
  anchorVersion: number;
  surfaceGrain: boolean;
  sync?: { bus: SyncBus; id: string };
  /** Second model rendered as a translucent ghost (overlay comparison). */
  ghost?: { model: LoadedModel; color: string } | null;
  ghostColor?: string;
  /** Tint for the primary model in overlay comparison. */
  onUserInteract?: () => void;
  onFreeView?: () => void;
  onContextLost?: () => void;
  onFirstFrame?: () => void;
}
