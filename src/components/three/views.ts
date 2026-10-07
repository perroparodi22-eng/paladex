/**
 * Camera view presets. Positions are derived from the model's bounding box,
 * so the same presets frame any racket that follows the orientation
 * convention (+Y butt to tip, +Z front face).
 */
import type { CameraView } from "@/domain/types";

export interface ModelFrame {
  /** Bounding box in model space (before centring). */
  min: [number, number, number];
  max: [number, number, number];
  size: [number, number, number];
  center: [number, number, number];
}

export interface CameraPose {
  position: [number, number, number];
  target: [number, number, number];
}

/** Distance at which the whole racket fits the view, with margin. */
export function fitDistance(frame: ModelFrame, fovDeg: number, aspect: number, margin = 1.26): number {
  const half = (fovDeg * Math.PI) / 360;
  const h = frame.size[1] / 2 / Math.tan(half);
  const w = frame.size[0] / 2 / Math.tan(half) / Math.max(0.3, aspect);
  return Math.max(h, w) * margin;
}

function spherical(target: [number, number, number], distance: number, azimuth: number, polar: number): CameraPose {
  return {
    target,
    position: [
      target[0] + distance * Math.sin(polar) * Math.sin(azimuth),
      target[1] + distance * Math.cos(polar),
      target[2] + distance * Math.sin(polar) * Math.cos(azimuth),
    ],
  };
}

/**
 * Pose for a view, in the centred coordinate system (model centre at origin).
 * `sweetV` is the relative height (0 butt … 1 tip) of the sweet spot.
 */
export function viewPose(view: CameraView, frame: ModelFrame, fit: number, sweetV = 0.68, lowAngle = false): CameraPose {
  const [, h] = frame.size;
  const yAt = (v: number) => -h / 2 + v * h;
  switch (view) {
    case "front":
      return spherical([0, 0, 0], fit, 0, Math.PI / 2);
    case "back":
      return spherical([0, 0, 0], fit, Math.PI, Math.PI / 2);
    case "edge":
      return spherical([0, 0, 0], fit, Math.PI / 2, Math.PI / 2 - 0.04);
    case "top":
      return spherical([0, yAt(0.9), 0], fit * 0.5, 0.42, 0.62);
    case "grip":
      return spherical([0, yAt(0.2), 0], fit * 0.48, 0.62, 1.42);
    case "detail":
      return spherical([0, yAt(sweetV), 0.01], fit * 0.3, 0.22, 1.15);
    case "hero":
    default:
      // The homepage replay opens on a low hero shot: camera near the turf, racket against the sunset.
      if (lowAngle) return spherical([0, h * 0.02, 0], fit * 1.04, -0.62, 1.66);
      return spherical([0, -h * 0.02, 0], fit * 0.98, -0.58, 1.42);
  }
}
