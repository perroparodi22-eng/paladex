/**
 * Default hotspots, 3D inspection notes and overlays for a racket model,
 * derived from its specs and geometry. Used by the seed and by the admin when
 * a racket is created, so every model starts with sensible, honest annotations.
 *
 * Positions are computed in metres on the model, then normalised to the
 * model's bounding box (u across, v butt → tip, w back → front).
 */
import type { Balance, Basis, CameraView, Hardness, OverlayKind, RacketShape, SpecKey, SurfaceFinish } from "@/domain/types";
import { BALANCE_INFO, HARDNESS_INFO, SHAPE_INFO, SURFACE_INFO, thicknessEffect } from "@/domain/vocab";
import { buildBlueprint, DIMS, estimatedBalanceMm, PLACEHOLDER_BOUNDS, sweetSpot, type Vec2 } from "@/lib/racket-geometry";

export interface DefaultsInput {
  shape: RacketShape;
  balance: Balance | null;
  balanceMm: number | null;
  hardness: Hardness | null;
  thicknessMm: number | null;
  frameMaterial: string | null;
  faceMaterial: string | null;
  coreMaterial: string | null;
  surfaceFinish: SurfaceFinish | null;
  sweetSpotScore: number;
  kind: "platform" | "placeholder" | "none";
  bbox?: { min: number[]; max: number[] } | null;
  /** Frame silhouette (metres). Defaults to the placeholder outline for the shape. */
  outline?: Vec2[];
  /** Centre of the throat opening (y, metres). */
  throatY?: number;
  /** Override for platform models: relative height of the sweet spot. */
  sweetSpotV?: number;
  /** Platform models with side weight screws. */
  screwsY?: number[];
  hasBumper?: boolean;
}

export interface HotspotDraft {
  key: string;
  label: string;
  body: string;
  u: number;
  v: number;
  w: number;
  view: CameraView;
  specKey: SpecKey | null;
  basis: Basis;
  sortOrder: number;
}

export interface AnnotationDraft {
  view: CameraView;
  title: string;
  body: string;
  basis: Basis;
  sortOrder: number;
}

export interface OverlayDraft {
  kind: OverlayKind;
  basis: Basis;
  note: string;
  params: Record<string, number | string | boolean>;
}

const r3 = (n: number) => Math.round(n * 1000) / 1000;

function edgeX(outline: Vec2[], y: number): number {
  let best = 0;
  for (let i = 0; i < outline.length; i++) {
    const a = outline[i];
    const b = outline[(i + 1) % outline.length];
    if ((a[1] - y) * (b[1] - y) > 0 || a[1] === b[1]) continue;
    const x = a[0] + ((y - a[1]) / (b[1] - a[1])) * (b[0] - a[0]);
    best = Math.max(best, x);
  }
  return best;
}

export function modelDefaults(input: DefaultsInput) {
  const bbox = input.bbox ?? { min: [...PLACEHOLDER_BOUNDS.min], max: [...PLACEHOLDER_BOUNDS.max] };
  const [x0, y0, z0] = bbox.min;
  const [x1, y1, z1] = bbox.max;
  const norm = (x: number, y: number, z: number) => ({
    u: r3((x - x0) / (x1 - x0)),
    v: r3((y - y0) / (y1 - y0)),
    w: r3((z - z0) / (z1 - z0)),
  });

  const outline = input.outline ?? buildBlueprint(input.shape, { pattern: "border", holes: "hex", bridge: false }).frameOuter;
  const length = y1 - y0;
  const zFace = DIMS.faceThickness / 2;
  const zFrame = DIMS.frameThickness / 2;
  const ss = sweetSpot(input.shape, input.sweetSpotScore);
  const sweetY = input.sweetSpotV !== undefined ? y0 + input.sweetSpotV * length : ss.y;
  const balanceMm = input.balanceMm ?? estimatedBalanceMm(input.balance);
  const balanceY = balanceMm / 1000;
  const balanceKnown = input.balanceMm !== null;
  const throatY = input.throatY ?? (DIMS.heartBottom + DIMS.headBottom) / 2;
  const shape = SHAPE_INFO[input.shape];

  const hotspots: HotspotDraft[] = [];
  const add = (h: Omit<HotspotDraft, "u" | "v" | "w" | "sortOrder">, p: [number, number, number]) =>
    hotspots.push({ ...h, ...norm(...p), sortOrder: hotspots.length });

  add(
    {
      key: "sweet-spot",
      label: "Sweet spot",
      body: `${shape.label} heads put the sweet spot ${input.shape === "round" ? "low and central" : input.shape === "diamond" ? "high on the face" : "slightly above the middle"}. This marker shows where contact is cleanest for this shape class. It is an illustration, not a measurement.`,
      view: "front",
      specKey: "sweet-spot",
      basis: "illustrative",
    },
    [0, sweetY, zFace],
  );
  add(
    {
      key: "face",
      label: "Hitting face",
      body: `${input.faceMaterial ? `Face: ${input.faceMaterial}.` : "Face material not published yet."} ${input.surfaceFinish ? SURFACE_INFO[input.surfaceFinish].effect : ""}`.trim(),
      view: "detail",
      specKey: "face",
      basis: input.faceMaterial ? "manufacturer" : "platform",
    },
    [0.055, sweetY + 0.05, zFace],
  );
  add(
    {
      key: "core",
      label: "Core",
      body: `${input.coreMaterial ? `Core: ${input.coreMaterial}.` : "Core material not published yet."} ${input.hardness ? HARDNESS_INFO[input.hardness].effect : ""} You can see the core through the walls of the holes.`.trim(),
      view: "detail",
      specKey: "core",
      basis: input.coreMaterial ? "manufacturer" : "platform",
    },
    [-0.062, sweetY - 0.035, zFace],
  );
  add(
    {
      key: "frame",
      label: "Frame",
      body: `${input.frameMaterial ? `${input.frameMaterial}.` : "Frame material not published yet."} The frame holds the face and largely sets how stiff and stable the racket feels.`,
      view: "top",
      specKey: "frame",
      basis: input.frameMaterial ? "manufacturer" : "platform",
    },
    [0, y1 - 0.001, 0],
  );
  add(
    {
      key: "balance",
      label: "Balance point",
      body: `${balanceKnown ? `About ${balanceMm} mm from the butt cap (published).` : `Estimated at around ${balanceMm} mm from the butt cap, from the "${input.balance ?? "medium"}" balance category.`} ${input.balance ? BALANCE_INFO[input.balance].effect : ""}`.trim(),
      view: "edge",
      specKey: "balance",
      basis: balanceKnown ? "manufacturer" : "platform",
    },
    [edgeX(outline, balanceY) + 0.002, balanceY, 0],
  );
  add(
    {
      key: "profile",
      label: "Profile",
      body: `${input.thicknessMm ? `${input.thicknessMm} mm thick.` : "Thickness not published yet."} ${thicknessEffect(input.thicknessMm)}`,
      view: "edge",
      specKey: "thickness",
      basis: input.thicknessMm ? "manufacturer" : "platform",
    },
    [edgeX(outline, 0.35) + 0.001, 0.35, 0],
  );
  add(
    {
      key: "throat",
      label: "Throat",
      body: "The open throat between the arms keeps weight down and lets the racket cut through the air. Its shape also affects how stiff the racket feels.",
      view: "front",
      specKey: null,
      basis: "platform",
    },
    [0, throatY, zFrame],
  );
  add(
    {
      key: "grip",
      label: "Grip and handle",
      body: "The handle is wrapped in an overgrip, which you replace as it wears. Choke up here for faster volleys at the net.",
      view: "grip",
      specKey: "grip",
      basis: "platform",
    },
    [0, 0.075, DIMS.handle.rz + 0.0015],
  );
  if (input.hasBumper) {
    add(
      {
        key: "bumper",
        label: "Protector",
        body: "A protective strip over the top of the frame guards against scrapes when the racket touches the ground or the walls.",
        view: "top",
        specKey: "frame",
        basis: "platform",
      },
      [edgeX(outline, y1 - 0.04) + 0.001, y1 - 0.04, 0],
    );
  }
  if (input.screwsY?.length) {
    const y = input.screwsY.reduce((a, b) => a + b, 0) / input.screwsY.length;
    add(
      {
        key: "weights",
        label: "Weight screws",
        body: "Screw-in weights on both sides of the head let you add mass and shift the balance towards the tip. The screws are modelled from the reference photos.",
        view: "edge",
        specKey: "weight",
        basis: "manufacturer",
      },
      [edgeX(outline, y) + 0.003, y, 0],
    );
  }

  const annotations: AnnotationDraft[] = [
    { view: "front", title: `Shape: ${shape.label}`, body: `${shape.meaning} ${shape.effect}`, basis: "platform", sortOrder: 0 },
    {
      view: "edge",
      title: "Profile",
      body: `${thicknessEffect(input.thicknessMm)} From the side you can also judge how the frame tapers into the handle.`,
      basis: input.thicknessMm ? "manufacturer" : "platform",
      sortOrder: 1,
    },
    {
      view: "top",
      title: "Top edge",
      body: "The top of the frame takes the most knocks. Check for a protector strip and how thick the frame is here, because both affect durability and how much the head weighs.",
      basis: "platform",
      sortOrder: 2,
    },
    {
      view: "grip",
      title: "Handle",
      body: "Look at where the throat meets the handle. A stiffer, wider junction adds stability, and a slimmer one feels quicker in the hand.",
      basis: "platform",
      sortOrder: 3,
    },
    {
      view: "detail",
      title: "Surface",
      body: input.surfaceFinish ? `${SURFACE_INFO[input.surfaceFinish].meaning} ${SURFACE_INFO[input.surfaceFinish].effect}` : "Surface finish not published yet.",
      basis: input.surfaceFinish ? "manufacturer" : "platform",
      sortOrder: 4,
    },
    {
      view: "back",
      title: "Back face",
      body:
        input.kind === "platform"
          ? "This model repeats the front print on the back. Most rackets share one design on both faces, but check the real racket if the back matters to you."
          : "Most rackets carry the same design on both faces.",
      basis: "platform",
      sortOrder: 5,
    },
  ];

  const width = x1 - x0;
  const overlays: OverlayDraft[] = [
    {
      kind: "sweet-spot",
      basis: "illustrative",
      note: "Illustration of where contact is cleanest for this shape class. Not a measurement of this racket.",
      params: { u: 0.5, v: r3((sweetY - y0) / length), ru: r3(ss.rx / width), rv: r3(ss.ry / length) },
    },
    {
      kind: "impact-zone",
      basis: "illustrative",
      note: "The wider zone where hits still feel solid. Illustrative.",
      params: { u: 0.5, v: r3((sweetY - 0.012 - y0) / length), ru: r3((ss.rx * 1.75) / width), rv: r3((ss.ry * 1.6) / length) },
    },
    {
      kind: "balance",
      basis: balanceKnown ? "manufacturer" : "platform",
      note: balanceKnown ? "Balance point published by the manufacturer." : "Estimated from the published balance category.",
      params: { mm: balanceMm, v: r3((balanceY - y0) / length), estimated: !balanceKnown },
    },
    {
      kind: "dimensions",
      basis: input.thicknessMm ? "manufacturer" : "platform",
      note: "Length and width are measured on the model, and the profile comes from the specification.",
      params: { lengthMm: Math.round(length * 1000), widthMm: Math.round((x1 - x0) * 1000), thicknessMm: input.thicknessMm ?? 38 },
    },
    {
      kind: "weight-distribution",
      basis: "illustrative",
      note: "Illustration of where the mass sits along the racket, derived from the balance point.",
      params: { bias: r3(Math.max(-1, Math.min(1, (balanceMm - 263) / 10))) },
    },
    {
      kind: "material-layers",
      basis: "illustrative",
      note: "Generic layer order (face skins, core, frame, grip). Not this racket's verified layup.",
      params: {},
    },
  ];

  return { hotspots, annotations, overlays };
}
