/**
 * adidas Metalbone 3.4: platform-created model from owner-supplied photos
 * (assets/reference/adidas-metalbone-3-4). Geometry is traced from the front
 * view (3.webp); screws, profile and finish are matched to the angled view
 * (1.webp) and the throat close-up (2.webp).
 */
import type { PhotoDesign, RacketTrace } from "./types";
import trace from "./adidas-metalbone-3-4.trace.json";

export const metalbone34: PhotoDesign = {
  slug: "adidas-metalbone-3-4",
  frontImage: "assets/reference/adidas-metalbone-3-4/3.webp",
  trace: trace as unknown as RacketTrace,
  thicknessMm: 38,
  faceThicknessMm: 34,
  // The face ends in a shallow V just above the throat (the orange/blue print line).
  faceBottom: { centerY: 0.2075, slope: 0.24 },
  // "Octagonal structure" frame: a single chamfer gives the eight-sided section.
  frameBevelSegments: 1,
  colors: {
    frame: "#0a0a0b",
    faceEdge: "#0d0e10",
    core: "#26292e",
    grip: "#101113",
    gripDots: "#c9ced3",
    collar: "#0c0d0f",
  },
  frameRoughness: 0.3,
  // Two adjustable weight screws on each side of the head, with blue anodised rings.
  screws: { y: [0.2445, 0.2585], ring: "#2fa6d9" },
  // adidas places the sweet spot high on the face ("sweet spot top").
  sweetSpotV: 0.735,
  mirrorBack: true,
};
