/**
 * Domain types: the shapes the UI works with.
 *
 * The database rows (src/server/db/schema.ts) are mapped into these types by
 * the repositories (src/server/repositories/*). UI code never imports DB rows,
 * so the storage can change without touching components.
 */

/* ---------------------------------------------------------------- vocab */

/** Product categories. Only rackets ship in the MVP; the rest are reserved. */
export const PRODUCT_CATEGORIES = ["racket", "shoe", "ball", "bag", "grip", "apparel"] as const;
export type ProductCategory = (typeof PRODUCT_CATEGORIES)[number];

export const RACKET_SHAPES = ["round", "teardrop", "hybrid", "diamond"] as const;
export type RacketShape = (typeof RACKET_SHAPES)[number];

export const BALANCES = ["low", "medium-low", "medium", "medium-high", "high"] as const;
export type Balance = (typeof BALANCES)[number];

export const HARDNESSES = ["soft", "medium-soft", "medium", "medium-hard", "hard"] as const;
export type Hardness = (typeof HARDNESSES)[number];

export const SURFACE_FINISHES = ["smooth", "rough", "sand", "3d"] as const;
export type SurfaceFinish = (typeof SURFACE_FINISHES)[number];

export const PLAYER_LEVELS = ["beginner", "intermediate", "advanced"] as const;
export type PlayerLevel = (typeof PLAYER_LEVELS)[number];

export const PLAYING_STYLES = ["power", "control", "all-round", "defensive", "aggressive"] as const;
export type PlayingStyle = (typeof PLAYING_STYLES)[number];

/** How far a piece of factual data has been checked. */
export const VERIFICATION_STATES = ["verified", "unverified", "placeholder"] as const;
export type Verification = (typeof VERIFICATION_STATES)[number];

/**
 * Where a 3D model comes from. This is shown to visitors, so it must be true.
 * - official:     supplied by the manufacturer
 * - licensed:     licensed from a third party
 * - platform:     built by us to represent the real racket
 * - placeholder:  generic model of the right shape class, NOT this racket's design
 * - unavailable:  no model; the page shows an image preview instead
 */
export const MODEL_STATUSES = ["official", "licensed", "platform", "placeholder", "unavailable"] as const;
export type ModelStatus = (typeof MODEL_STATUSES)[number];

export const LICENSE_STATUSES = ["owned", "licensed", "permission", "supplied", "pending", "none"] as const;
export type LicenseStatus = (typeof LICENSE_STATUSES)[number];

export const APPROVAL_STATUSES = ["approved", "pending", "rejected"] as const;
export type ApprovalStatus = (typeof APPROVAL_STATUSES)[number];

export const MODEL_VARIANT_KINDS = [
  "standard",
  "close-up",
  "exploded",
  "colorway",
  "finish",
  "manufacturer",
  "platform-visualization",
] as const;
export type ModelVariantKind = (typeof MODEL_VARIANT_KINDS)[number];

/** Basis of an explanatory element: is it backed by data, or an illustration? */
export const BASES = ["manufacturer", "platform", "illustrative"] as const;
export type Basis = (typeof BASES)[number];

export const OVERLAY_KINDS = [
  "sweet-spot",
  "impact-zone",
  "balance",
  "dimensions",
  "weight-distribution",
  "material-layers",
] as const;
export type OverlayKind = (typeof OVERLAY_KINDS)[number];

export const CAMERA_VIEWS = ["hero", "front", "back", "edge", "top", "grip", "detail"] as const;
export type CameraView = (typeof CAMERA_VIEWS)[number];

export const STOCK_STATUSES = ["in_stock", "low_stock", "out_of_stock", "preorder", "unknown"] as const;
export type StockStatus = (typeof STOCK_STATUSES)[number];

export const PUBLISH_STATUSES = ["draft", "published"] as const;
export type PublishStatus = (typeof PUBLISH_STATUSES)[number];

/* --------------------------------------------------------------- shapes */

export interface Money {
  /** Integer minor units (cents). Never use floats for money. */
  amountCents: number;
  currency: string;
}

export interface BrandSummary {
  id: number;
  slug: string;
  name: string;
}

export interface Brand extends BrandSummary {
  country: string | null;
  description: string;
  websiteUrl: string | null;
  logoUrl: string | null;
  racketCount?: number;
}

/** Manufacturer specification. Every field is nullable: unknown is shown as unknown. */
export interface ManufacturerSpec {
  shape: RacketShape;
  weightMinG: number | null;
  weightMaxG: number | null;
  balance: Balance | null;
  /** Balance point in mm from the butt cap, when the manufacturer publishes it. */
  balanceMm: number | null;
  hardness: Hardness | null;
  thicknessMm: number | null;
  frameMaterial: string | null;
  faceMaterial: string | null;
  coreMaterial: string | null;
  surfaceFinish: SurfaceFinish | null;
  verification: Verification;
  sourceNote: string | null;
  sourceUrl: string | null;
}

/** The platform's own evaluation. Never presented as a manufacturer measurement. */
export interface PlatformEvaluation {
  power: number;
  control: number;
  maneuverability: number;
  forgiveness: number;
  sweetSpot: number;
  defense: number;
  attack: number;
  /** Weighted overall, computed by lib/scores. */
  overall: number;
  bestFor: string;
  recommendedFor: string;
  notIdealFor: string;
  methodologyVersion: string;
  isSample: boolean;
}

/** Colourway and graphic recipe for the procedural placeholder model and the illustration. */
/** A touring professional who plays a racket. */
export interface ProPlayer {
  name: string;
  tour: "men" | "women";
  /** Order in the owner's catalogue (top of the tour first). */
  order: number;
}

export interface RacketVisual {
  face: string;
  frame: string;
  accent: string;
  accent2: string;
  grip: string;
  pattern: "sweep" | "split" | "chevron" | "ring" | "border" | "blade";
  holes: "hex" | "rings";
  bridge: boolean;
}

export interface AssetProvenance {
  source: string | null;
  licenseStatus: LicenseStatus;
  attribution: string | null;
  creator: string | null;
  usageRestrictions: string | null;
  approvalStatus: ApprovalStatus;
}

export interface ModelVariant {
  id: number;
  kind: ModelVariantKind;
  label: string;
  url: string;
  status: ModelStatus;
}

export interface Model3D {
  id: number;
  status: ModelStatus;
  format: "glb" | "gltf";
  /** Full-quality model. */
  url: string | null;
  /** Lightweight model for cards, carousels and the first paint of a viewer. */
  previewUrl: string | null;
  version: string;
  posterUrl: string | null;
  thumbnailUrl: string | null;
  explodedUrl: string | null;
  /** True when the model has named parts that can be exploded (see docs/3D-PIPELINE.md). */
  supportsExplode: boolean;
  fileSizeBytes: number | null;
  provenance: AssetProvenance;
  variants: ModelVariant[];
}

/**
 * Hotspot position in normalized bounding-box space:
 * u: 0 = left edge, 1 = right edge (x)
 * v: 0 = butt cap, 1 = top of the head (y)
 * w: 0 = back face, 1 = front face (z)
 * Works for any model that follows the orientation convention.
 */
export interface Hotspot {
  id: number;
  key: string;
  label: string;
  body: string;
  u: number;
  v: number;
  w: number;
  view: CameraView;
  specKey: SpecKey | null;
  basis: Basis;
}

export interface Annotation {
  id: number;
  view: CameraView;
  title: string;
  body: string;
  basis: Basis;
}

export interface OverlayConfig {
  kind: OverlayKind;
  basis: Basis;
  note: string | null;
  params: Record<string, number | string | boolean>;
}

export interface Retailer {
  id: number;
  slug: string;
  name: string;
  websiteUrl: string;
  logoUrl: string | null;
  country: string;
  currency: string;
  shippingInfo: string | null;
  affiliateNetwork: string | null;
  allowedDomains: string[];
  isDemo: boolean;
  active: boolean;
}

export interface Offer {
  id: number;
  retailer: Retailer;
  price: Money;
  stockStatus: StockStatus;
  available: boolean;
  country: string;
  shippingInfo: string | null;
  lastCheckedAt: string | null;
  /** True while the affiliate link is AFFILIATE_URL_HERE or missing. */
  linkIsPlaceholder: boolean;
  isDemo: boolean;
}

export interface EditorialReview {
  title: string;
  summary: string;
  body: string;
  pros: string[];
  cons: string[];
  verdict: string;
  inspectionNotes: string | null;
  modelQualityNote: string | null;
  author: string;
  isSample: boolean;
  publishedAt: string | null;
}

export interface UserRatingSummary {
  average: number;
  count: number;
}

/** Compact racket used by cards, the catalog, search and the showroom carousel. */
export interface RacketSummary {
  id: number;
  slug: string;
  name: string;
  fullName: string;
  brand: BrandSummary;
  year: number | null;
  shortDescription: string;
  shape: RacketShape;
  weightMinG: number | null;
  weightMaxG: number | null;
  balance: Balance | null;
  hardness: Hardness | null;
  surfaceFinish: SurfaceFinish | null;
  levels: PlayerLevel[];
  styles: PlayingStyle[];
  scores: Pick<PlatformEvaluation, "power" | "control" | "maneuverability" | "forgiveness" | "sweetSpot" | "defense" | "attack" | "overall"> | null;
  priceFrom: Money | null;
  indicativePrice: Money | null;
  offerCount: number;
  modelStatus: ModelStatus;
  modelPreviewUrl: string | null;
  modelUrl: string | null;
  imageUrl: string | null;
  imageAlt: string;
  visual: RacketVisual;
  featured: boolean;
  isNew: boolean;
  dataStatus: Verification;
  userRating: UserRatingSummary | null;
  createdAt: string;
  proPlayers: ProPlayer[];
}

export interface ProductImage {
  url: string;
  alt: string;
  kind: string;
}

/** Everything a racket page needs. */
export interface Racket extends RacketSummary {
  collection: string | null;
  description: string;
  status: PublishStatus;
  specs: ManufacturerSpec;
  evaluation: PlatformEvaluation | null;
  model: Model3D | null;
  hotspots: Hotspot[];
  annotations: Annotation[];
  overlays: OverlayConfig[];
  offers: Offer[];
  review: EditorialReview | null;
  /** What published reviewers and testers say, summarised by Paladex. */
  roundup: ReviewRoundup | null;
  images: ProductImage[];
  updatedAt: string;
}

/**
 * A summary of what published reviews, retailer tests and buyer reviews say
 * about a racket, written in Paladex's words with every source linked. The
 * opinions belong to the sources; `ourRead` is Paladex's own take drawn from
 * them (not a play test).
 */
export interface ReviewRoundup {
  /** reviewed: independent reviews exist. early: too new, so built from measured data and retailer tests. */
  status: "reviewed" | "early";
  summary: string;
  liked: string[];
  watchOuts: string[];
  suits: string;
  ourRead: string;
  /** Extra details beyond the spec table (measured swingweight, tech, hitting area). */
  facts: Array<{ label: string; value: string }>;
  sources: Array<{ name: string; url: string }>;
  /** ISO date the sources were checked. */
  checkedOn: string;
}

/** Keys that tie spec rows, hotspots and viewer actions together. */
export const SPEC_KEYS = [
  "shape",
  "weight",
  "balance",
  "thickness",
  "hardness",
  "surface",
  "face",
  "core",
  "frame",
  "sweet-spot",
  "grip",
] as const;
export type SpecKey = (typeof SPEC_KEYS)[number];

export type ScoreKey = "power" | "control" | "maneuverability" | "forgiveness" | "sweetSpot" | "defense" | "attack";
