/**
 * Design specs for platform-created racket models built from reference photos.
 * The trace (geometry) comes from scripts/trace-racket-photo.ts; the rest is
 * art direction measured by eye from the photos. See docs/3D-PIPELINE.md.
 */
export type V2 = [number, number];

export interface RacketTrace {
  slug: string;
  source: string;
  rotateDeg: number;
  imageSize: [number, number];
  metresPerPixel: number;
  axisX: number;
  buttY: number;
  topY: number;
  gripAxisOffsetM: number;
  frameOuter: V2[];
  throat: V2[];
  holes: Array<{ x: number; y: number; r: number }>;
  neckY: number;
  faceInsetM: number;
  grip: { halfWidth: number };
  headWidthM: number;
}

export interface PhotoDesign {
  slug: string;
  /** Front photo (transparent background) used for tracing and as the face texture. */
  frontImage: string;
  trace: RacketTrace;
  thicknessMm: number;
  /** Total thickness of the hitting surface (face skins + core); the frame stands proud of it. */
  faceThicknessMm: number;
  /** Bottom edge of the face: lowest at the centre (y, metres), rising with |x| * slope. */
  faceBottom: { centerY: number; slope: number };
  /** Chamfer style of the frame edge: 1 = octagonal section, 3 = rounded. */
  frameBevelSegments: number;
  colors: {
    frame: string;
    faceEdge: string;
    core: string;
    grip: string;
    gripDots: string;
    collar: string;
  };
  frameRoughness: number;
  /** Side weight screws: heights (metres from the butt) on both sides of the frame. */
  screws?: { y: number[]; ring: string };
  /** Where the sweet-spot overlay is centred (relative height, 0 butt … 1 tip). */
  sweetSpotV: number;
  /** Mirror the front print onto the back face (most rackets share the design on both faces). */
  mirrorBack: boolean;
}
