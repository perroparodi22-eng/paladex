/**
 * Database schema (Drizzle ORM, SQLite/libSQL dialect).
 *
 * Design notes
 * - `products` is category-agnostic (rackets today; shoes, balls, bags later).
 *   Category-specific manufacturer data lives in its own 1:1 table
 *   (`racket_specs`). A future `shoe_specs` table slots in beside it.
 * - Manufacturer specification (`racket_specs`) and the platform's own
 *   opinion (`platform_evaluations`, `editorial_reviews`) are separate tables
 *   so the UI can never blur the two.
 * - Every visual asset (3D model, image) carries provenance and licensing
 *   fields so placeholder or unlicensed assets can be found and replaced.
 * - Money is stored as integer cents.
 */
import { relations, sql } from "drizzle-orm";
import { index, integer, primaryKey, real, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";
import type { ProPlayer, RacketVisual, ReviewRoundup } from "@/domain/types";

const timestamps = {
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .notNull()
    .default(sql`(unixepoch() * 1000)`),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" })
    .notNull()
    .default(sql`(unixepoch() * 1000)`)
    .$onUpdateFn(() => new Date()),
};

/* ------------------------------------------------------------- catalog */

export const productCategories = sqliteTable("product_categories", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  slug: text("slug").notNull().unique(),
  name: text("name").notNull(),
  description: text("description").notNull().default(""),
});

export const brands = sqliteTable("brands", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  slug: text("slug").notNull().unique(),
  name: text("name").notNull(),
  country: text("country"),
  description: text("description").notNull().default(""),
  websiteUrl: text("website_url"),
  logoUrl: text("logo_url"),
  ...timestamps,
});

export const products = sqliteTable(
  "products",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    categoryId: integer("category_id")
      .notNull()
      .references(() => productCategories.id),
    brandId: integer("brand_id")
      .notNull()
      .references(() => brands.id),
    slug: text("slug").notNull().unique(),
    name: text("name").notNull(),
    collection: text("collection"),
    year: integer("year"),
    shortDescription: text("short_description").notNull().default(""),
    description: text("description").notNull().default(""),
    status: text("status", { enum: ["draft", "published"] }).notNull().default("draft"),
    featured: integer("featured", { mode: "boolean" }).notNull().default(false),
    isNew: integer("is_new", { mode: "boolean" }).notNull().default(false),
    /** Overall data quality of the record: verified | unverified | placeholder. */
    dataStatus: text("data_status", { enum: ["verified", "unverified", "placeholder"] }).notNull().default("unverified"),
    /** Platform classification (not a manufacturer claim). */
    levels: text("levels", { mode: "json" }).$type<string[]>().notNull().default(sql`'[]'`),
    /** Colourway and print recipe for placeholder models and illustrations. */
    visual: text("visual", { mode: "json" }).$type<RacketVisual>().notNull(),
    /** Touring pros who play this racket (from the owner's pro-players catalogue). */
    proPlayers: text("pro_players", { mode: "json" }).$type<ProPlayer[]>().notNull().default(sql`'[]'`),
    /** Summary of published reviews with linked sources (src/data/seed/racket-research.ts). */
    roundup: text("roundup", { mode: "json" }).$type<ReviewRoundup>(),
    indicativePriceCents: integer("indicative_price_cents"),
    currency: text("currency").notNull().default("EUR"),
    publishedAt: integer("published_at", { mode: "timestamp_ms" }),
    ...timestamps,
  },
  (t) => [index("products_brand_idx").on(t.brandId), index("products_status_idx").on(t.status)],
);

/** Manufacturer specification for rackets. Unknown values stay NULL. */
export const racketSpecs = sqliteTable("racket_specs", {
  productId: integer("product_id")
    .primaryKey()
    .references(() => products.id, { onDelete: "cascade" }),
  shape: text("shape", { enum: ["round", "teardrop", "hybrid", "diamond"] }).notNull(),
  weightMinG: integer("weight_min_g"),
  weightMaxG: integer("weight_max_g"),
  balance: text("balance", { enum: ["low", "medium-low", "medium", "medium-high", "high"] }),
  balanceMm: integer("balance_mm"),
  hardness: text("hardness", { enum: ["soft", "medium-soft", "medium", "medium-hard", "hard"] }),
  thicknessMm: real("thickness_mm"),
  frameMaterial: text("frame_material"),
  faceMaterial: text("face_material"),
  coreMaterial: text("core_material"),
  surfaceFinish: text("surface_finish", { enum: ["smooth", "rough", "sand", "3d"] }),
  verification: text("verification", { enum: ["verified", "unverified", "placeholder"] }).notNull().default("unverified"),
  sourceNote: text("source_note"),
  sourceUrl: text("source_url"),
  verifiedAt: integer("verified_at", { mode: "timestamp_ms" }),
});

/** The platform's own evaluation. Scores are 1–10; never presented as measurements. */
export const platformEvaluations = sqliteTable("platform_evaluations", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  productId: integer("product_id")
    .notNull()
    .unique()
    .references(() => products.id, { onDelete: "cascade" }),
  power: real("power").notNull(),
  control: real("control").notNull(),
  maneuverability: real("maneuverability").notNull(),
  forgiveness: real("forgiveness").notNull(),
  sweetSpot: real("sweet_spot").notNull(),
  defense: real("defense").notNull(),
  attack: real("attack").notNull(),
  bestFor: text("best_for").notNull().default(""),
  recommendedFor: text("recommended_for").notNull().default(""),
  notIdealFor: text("not_ideal_for").notNull().default(""),
  methodologyVersion: text("methodology_version").notNull(),
  isSample: integer("is_sample", { mode: "boolean" }).notNull().default(true),
  evaluatedAt: integer("evaluated_at", { mode: "timestamp_ms" })
    .notNull()
    .default(sql`(unixepoch() * 1000)`),
});

export const playingStyles = sqliteTable("playing_styles", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  slug: text("slug").notNull().unique(),
  name: text("name").notNull(),
  description: text("description").notNull().default(""),
});

export const productPlayingStyles = sqliteTable(
  "product_playing_styles",
  {
    productId: integer("product_id")
      .notNull()
      .references(() => products.id, { onDelete: "cascade" }),
    styleId: integer("style_id")
      .notNull()
      .references(() => playingStyles.id, { onDelete: "cascade" }),
  },
  (t) => [primaryKey({ columns: [t.productId, t.styleId] })],
);

/* ---------------------------------------------------------- 3D & media */

const provenance = {
  source: text("source"),
  licenseStatus: text("license_status", { enum: ["owned", "licensed", "permission", "supplied", "pending", "none"] })
    .notNull()
    .default("pending"),
  attribution: text("attribution"),
  creator: text("creator"),
  usageRestrictions: text("usage_restrictions"),
  approvalStatus: text("approval_status", { enum: ["approved", "pending", "rejected"] }).notNull().default("pending"),
};

/** 3D models: one primary model per product, plus optional variants. */
export const modelAssets = sqliteTable(
  "model_assets",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    productId: integer("product_id")
      .notNull()
      .references(() => products.id, { onDelete: "cascade" }),
    role: text("role", { enum: ["primary", "variant"] }).notNull().default("primary"),
    variantKind: text("variant_kind", {
      enum: ["standard", "close-up", "exploded", "colorway", "finish", "manufacturer", "platform-visualization"],
    })
      .notNull()
      .default("standard"),
    label: text("label").notNull().default("Standard"),
    /** official | licensed | platform | placeholder | unavailable */
    status: text("status", { enum: ["official", "licensed", "platform", "placeholder", "unavailable"] }).notNull(),
    format: text("format", { enum: ["glb", "gltf"] }).notNull().default("glb"),
    url: text("url"),
    previewUrl: text("preview_url"),
    explodedUrl: text("exploded_url"),
    version: text("version").notNull().default("1"),
    posterUrl: text("poster_url"),
    thumbnailUrl: text("thumbnail_url"),
    supportsExplode: integer("supports_explode", { mode: "boolean" }).notNull().default(false),
    fileSizeBytes: integer("file_size_bytes"),
    triangleCount: integer("triangle_count"),
    bbox: text("bbox", { mode: "json" }).$type<{ min: number[]; max: number[] }>(),
    materialConfig: text("material_config", { mode: "json" }).$type<Record<string, string>>(),
    notes: text("notes"),
    ...provenance,
    ...timestamps,
  },
  (t) => [index("model_assets_product_idx").on(t.productId)],
);

export const modelHotspots = sqliteTable(
  "model_hotspots",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    productId: integer("product_id")
      .notNull()
      .references(() => products.id, { onDelete: "cascade" }),
    key: text("key").notNull(),
    label: text("label").notNull(),
    body: text("body").notNull(),
    /** Normalized bounding-box position: u across, v along (0 butt → 1 tip), w through (0 back → 1 front). */
    u: real("u").notNull(),
    v: real("v").notNull(),
    w: real("w").notNull(),
    view: text("view").notNull().default("front"),
    specKey: text("spec_key"),
    basis: text("basis", { enum: ["manufacturer", "platform", "illustrative"] }).notNull().default("illustrative"),
    sortOrder: integer("sort_order").notNull().default(0),
  },
  (t) => [index("model_hotspots_product_idx").on(t.productId)],
);

/** 3D inspection notes bound to a camera view. */
export const modelAnnotations = sqliteTable("model_annotations", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  productId: integer("product_id")
    .notNull()
    .references(() => products.id, { onDelete: "cascade" }),
  view: text("view").notNull(),
  title: text("title").notNull(),
  body: text("body").notNull(),
  basis: text("basis", { enum: ["manufacturer", "platform", "illustrative"] }).notNull().default("platform"),
  sortOrder: integer("sort_order").notNull().default(0),
});

/** Technical overlays available for a product (sweet spot, balance, dimensions …). */
export const modelOverlays = sqliteTable(
  "model_overlays",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    productId: integer("product_id")
      .notNull()
      .references(() => products.id, { onDelete: "cascade" }),
    kind: text("kind", {
      enum: ["sweet-spot", "impact-zone", "balance", "dimensions", "weight-distribution", "material-layers"],
    }).notNull(),
    enabled: integer("enabled", { mode: "boolean" }).notNull().default(true),
    basis: text("basis", { enum: ["manufacturer", "platform", "illustrative"] }).notNull().default("illustrative"),
    note: text("note"),
    params: text("params", { mode: "json" }).$type<Record<string, number | string | boolean>>().notNull().default(sql`'{}'`),
  },
  (t) => [uniqueIndex("model_overlays_product_kind").on(t.productId, t.kind)],
);

export const productImages = sqliteTable("product_images", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  productId: integer("product_id")
    .notNull()
    .references(() => products.id, { onDelete: "cascade" }),
  url: text("url").notNull(),
  alt: text("alt").notNull(),
  kind: text("kind", { enum: ["front", "angle", "detail", "lifestyle"] }).notNull().default("front"),
  sortOrder: integer("sort_order").notNull().default(0),
  ...provenance,
});

/* --------------------------------------------------------- affiliate */

export const retailers = sqliteTable("retailers", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  slug: text("slug").notNull().unique(),
  name: text("name").notNull(),
  websiteUrl: text("website_url").notNull(),
  logoUrl: text("logo_url"),
  country: text("country").notNull().default("EU"),
  currency: text("currency").notNull().default("EUR"),
  shippingInfo: text("shipping_info"),
  affiliateNetwork: text("affiliate_network"),
  /** Hostnames this retailer's links may point to (redirect allow-list). */
  allowedDomains: text("allowed_domains", { mode: "json" }).$type<string[]>().notNull().default(sql`'[]'`),
  isDemo: integer("is_demo", { mode: "boolean" }).notNull().default(false),
  active: integer("active", { mode: "boolean" }).notNull().default(true),
  ...timestamps,
});

export const offers = sqliteTable(
  "offers",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    productId: integer("product_id")
      .notNull()
      .references(() => products.id, { onDelete: "cascade" }),
    retailerId: integer("retailer_id")
      .notNull()
      .references(() => retailers.id, { onDelete: "cascade" }),
    productUrl: text("product_url"),
    /** Affiliate link. "AFFILIATE_URL_HERE" (or empty) marks a placeholder. */
    affiliateUrl: text("affiliate_url"),
    priceCents: integer("price_cents").notNull(),
    currency: text("currency").notNull().default("EUR"),
    stockStatus: text("stock_status", { enum: ["in_stock", "low_stock", "out_of_stock", "preorder", "unknown"] })
      .notNull()
      .default("unknown"),
    available: integer("available", { mode: "boolean" }).notNull().default(true),
    country: text("country").notNull().default("EU"),
    shippingInfo: text("shipping_info"),
    lastCheckedAt: integer("last_checked_at", { mode: "timestamp_ms" }),
    isDemo: integer("is_demo", { mode: "boolean" }).notNull().default(false),
    active: integer("active", { mode: "boolean" }).notNull().default(true),
    ...timestamps,
  },
  (t) => [index("offers_product_idx").on(t.productId), uniqueIndex("offers_product_retailer").on(t.productId, t.retailerId)],
);

/** One row per outbound click. No personal data: no IP, no user agent, no cookies. */
export const affiliateClicks = sqliteTable(
  "affiliate_clicks",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    offerId: integer("offer_id").notNull(),
    productId: integer("product_id").notNull(),
    retailerId: integer("retailer_id").notNull(),
    sourcePath: text("source_path"),
    wasPlaceholder: integer("was_placeholder", { mode: "boolean" }).notNull().default(false),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .notNull()
      .default(sql`(unixepoch() * 1000)`),
  },
  (t) => [index("affiliate_clicks_created_idx").on(t.createdAt), index("affiliate_clicks_product_idx").on(t.productId)],
);

/* ------------------------------------------------------------ reviews */

export const editorialReviews = sqliteTable("editorial_reviews", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  productId: integer("product_id")
    .notNull()
    .unique()
    .references(() => products.id, { onDelete: "cascade" }),
  title: text("title").notNull(),
  summary: text("summary").notNull(),
  body: text("body").notNull(),
  pros: text("pros", { mode: "json" }).$type<string[]>().notNull().default(sql`'[]'`),
  cons: text("cons", { mode: "json" }).$type<string[]>().notNull().default(sql`'[]'`),
  verdict: text("verdict").notNull(),
  inspectionNotes: text("inspection_notes"),
  modelQualityNote: text("model_quality_note"),
  author: text("author").notNull().default("Paladex editorial"),
  isSample: integer("is_sample", { mode: "boolean" }).notNull().default(true),
  publishedAt: integer("published_at", { mode: "timestamp_ms" }),
  ...timestamps,
});

/** User reviews: architecture only in the MVP (no public submission form yet). */
export const userReviews = sqliteTable(
  "user_reviews",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    productId: integer("product_id")
      .notNull()
      .references(() => products.id, { onDelete: "cascade" }),
    rating: integer("rating").notNull(),
    title: text("title"),
    body: text("body"),
    displayName: text("display_name"),
    status: text("status", { enum: ["pending", "approved", "rejected"] }).notNull().default("pending"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .notNull()
      .default(sql`(unixepoch() * 1000)`),
  },
  (t) => [index("user_reviews_product_idx").on(t.productId)],
);

/* ---------------------------------------------------------- analytics */

/** First-party analytics sink. Event name + whitelisted props + path. No identifiers. */
export const analyticsEvents = sqliteTable(
  "analytics_events",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    name: text("name").notNull(),
    props: text("props", { mode: "json" }).$type<Record<string, string | number | boolean>>().notNull().default(sql`'{}'`),
    path: text("path"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .notNull()
      .default(sql`(unixepoch() * 1000)`),
  },
  (t) => [index("analytics_events_name_idx").on(t.name, t.createdAt)],
);

/* ---------------------------------------------------------- relations */

export const brandsRelations = relations(brands, ({ many }) => ({ products: many(products) }));

export const productsRelations = relations(products, ({ one, many }) => ({
  brand: one(brands, { fields: [products.brandId], references: [brands.id] }),
  category: one(productCategories, { fields: [products.categoryId], references: [productCategories.id] }),
  specs: one(racketSpecs, { fields: [products.id], references: [racketSpecs.productId] }),
  evaluation: one(platformEvaluations, { fields: [products.id], references: [platformEvaluations.productId] }),
  review: one(editorialReviews, { fields: [products.id], references: [editorialReviews.productId] }),
  styles: many(productPlayingStyles),
  models: many(modelAssets),
  hotspots: many(modelHotspots),
  annotations: many(modelAnnotations),
  overlays: many(modelOverlays),
  images: many(productImages),
  offers: many(offers),
  userReviews: many(userReviews),
}));

export const racketSpecsRelations = relations(racketSpecs, ({ one }) => ({
  product: one(products, { fields: [racketSpecs.productId], references: [products.id] }),
}));
export const platformEvaluationsRelations = relations(platformEvaluations, ({ one }) => ({
  product: one(products, { fields: [platformEvaluations.productId], references: [products.id] }),
}));
export const editorialReviewsRelations = relations(editorialReviews, ({ one }) => ({
  product: one(products, { fields: [editorialReviews.productId], references: [products.id] }),
}));
export const productPlayingStylesRelations = relations(productPlayingStyles, ({ one }) => ({
  product: one(products, { fields: [productPlayingStyles.productId], references: [products.id] }),
  style: one(playingStyles, { fields: [productPlayingStyles.styleId], references: [playingStyles.id] }),
}));
export const modelAssetsRelations = relations(modelAssets, ({ one }) => ({
  product: one(products, { fields: [modelAssets.productId], references: [products.id] }),
}));
export const modelHotspotsRelations = relations(modelHotspots, ({ one }) => ({
  product: one(products, { fields: [modelHotspots.productId], references: [products.id] }),
}));
export const modelAnnotationsRelations = relations(modelAnnotations, ({ one }) => ({
  product: one(products, { fields: [modelAnnotations.productId], references: [products.id] }),
}));
export const modelOverlaysRelations = relations(modelOverlays, ({ one }) => ({
  product: one(products, { fields: [modelOverlays.productId], references: [products.id] }),
}));
export const productImagesRelations = relations(productImages, ({ one }) => ({
  product: one(products, { fields: [productImages.productId], references: [products.id] }),
}));
export const retailersRelations = relations(retailers, ({ many }) => ({ offers: many(offers) }));
export const offersRelations = relations(offers, ({ one }) => ({
  product: one(products, { fields: [offers.productId], references: [products.id] }),
  retailer: one(retailers, { fields: [offers.retailerId], references: [retailers.id] }),
}));
export const userReviewsRelations = relations(userReviews, ({ one }) => ({
  product: one(products, { fields: [userReviews.productId], references: [products.id] }),
}));
