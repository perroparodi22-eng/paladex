/**
 * Admin data access: listing, loading and saving rackets (with every related
 * record) in one transaction, plus brands, retailers and dashboard stats.
 * Callers must run requireAdmin() first.
 */
import "server-only";
import { and, desc, eq, inArray, like, ne, notInArray, or, sql } from "drizzle-orm";
import { getDb, schema } from "@/server/db";
import type { RacketInput } from "@/server/validation/admin";
import { modelDefaults } from "@/lib/model-defaults";
import { hostMatches, isPlaceholderLink } from "@/lib/urls";
import { siteConfig } from "@/config/site";
import { photoDesigns } from "@/data/designs";
import generatedModels from "@/data/models.generated.json";
import type { Basis, CameraView, ModelStatus, PlayerLevel, PlayingStyle, RacketVisual, SpecKey } from "@/domain/types";

export class SaveError extends Error {}

type GeneratedModel = { url: string; previewUrl: string; bytes: number; triangles: number; bbox: { min: number[]; max: number[] } };
const generated = generatedModels as Record<string, GeneratedModel>;
const stripQuery = (u: string) => u.split("?")[0];

/* --------------------------------------------------------------- rackets */

export async function adminListRackets(q = "") {
  const db = await getDb();
  const term = q.trim();
  const rows = await db.query.products.findMany({
    where: term ? or(like(schema.products.name, `%${term}%`), like(schema.products.slug, `%${term}%`)) : undefined,
    with: { brand: true, models: true, offers: true, specs: true },
    orderBy: (p) => [desc(p.updatedAt)],
  });
  return rows.map((r) => {
    const primary = r.models.find((m) => m.role === "primary");
    return {
      id: r.id,
      slug: r.slug,
      name: r.name,
      brand: r.brand.name,
      status: r.status,
      featured: r.featured,
      shape: r.specs?.shape ?? null,
      modelStatus: (primary?.status ?? "unavailable") as ModelStatus,
      offers: r.offers.length,
      placeholderLinks: r.offers.filter((o) => isPlaceholderLink(o.affiliateUrl)).length,
      updatedAt: r.updatedAt,
    };
  });
}

export async function adminOptions() {
  const db = await getDb();
  const [brands, retailers] = await Promise.all([
    db.select({ id: schema.brands.id, name: schema.brands.name, slug: schema.brands.slug }).from(schema.brands).orderBy(schema.brands.name),
    db
      .select({ id: schema.retailers.id, name: schema.retailers.name, isDemo: schema.retailers.isDemo, currency: schema.retailers.currency })
      .from(schema.retailers)
      .orderBy(schema.retailers.name),
  ]);
  return { brands, retailers };
}

const DEFAULT_VISUAL: RacketVisual = {
  face: "#1b232d",
  frame: "#0e1116",
  accent: "#8f9bb3",
  accent2: "#f3f4f9",
  grip: "#111214",
  pattern: "sweep",
  holes: "hex",
  bridge: false,
};

type DerivedSpecs = Pick<
  RacketInput["specs"],
  "shape" | "balance" | "balanceMm" | "hardness" | "thicknessMm" | "frameMaterial" | "faceMaterial" | "coreMaterial" | "surfaceFinish"
>;

/**
 * Hotspots, 3D notes and overlays derived from the specs, using the same rules
 * as the seed. Uses the traced outline when the racket has a photo design and
 * the model's bounding box when one is known.
 */
export function derivedAnnotations(input: {
  slug: string;
  specs: DerivedSpecs;
  sweetSpotScore: number;
  modelStatus: ModelStatus;
  bbox?: { min: number[]; max: number[] } | null;
}) {
  const design = photoDesigns[input.slug];
  const trace = input.modelStatus === "platform" ? design?.trace : undefined;
  const throatY = trace?.throat.length ? trace.throat.reduce((s, p) => s + p[1], 0) / trace.throat.length : undefined;
  const kind = input.modelStatus === "unavailable" ? "none" : input.modelStatus === "placeholder" ? "placeholder" : "platform";
  const d = modelDefaults({
    ...input.specs,
    sweetSpotScore: input.sweetSpotScore,
    kind,
    bbox: input.bbox ?? generated[input.slug]?.bbox ?? null,
    outline: trace?.frameOuter,
    throatY,
    sweetSpotV: trace ? design?.sweetSpotV : undefined,
    screwsY: trace ? design?.screws?.y : undefined,
    hasBumper: kind === "placeholder",
  });
  return {
    hotspots: d.hotspots.map(({ sortOrder: _s, ...h }) => h),
    annotations: d.annotations.map(({ sortOrder: _s, ...a }) => a),
    overlays: d.overlays.map((o) => ({ ...o, enabled: o.kind !== "material-layers" || kind !== "none" })),
  };
}

/** An empty racket for the "new racket" form, with honest defaults. */
export function blankRacket(brandId: number): RacketInput {
  const specs: RacketInput["specs"] = {
    shape: "teardrop",
    weightMinG: null,
    weightMaxG: null,
    balance: "medium",
    balanceMm: null,
    hardness: "medium",
    thicknessMm: 38,
    frameMaterial: null,
    faceMaterial: null,
    coreMaterial: null,
    surfaceFinish: null,
    verification: "unverified",
    sourceNote: null,
    sourceUrl: null,
  };
  const derived = derivedAnnotations({ slug: "", specs, sweetSpotScore: 7, modelStatus: "unavailable" });
  return {
    basics: {
      brandId,
      slug: "",
      name: "",
      collection: null,
      year: new Date().getFullYear(),
      shortDescription: "",
      description: "",
      status: "draft",
      featured: false,
      isNew: true,
      levels: [],
      styles: [],
      indicativePriceEur: null,
      dataStatus: "unverified",
    },
    specs,
    evaluation: {
      power: 7,
      control: 7,
      maneuverability: 7,
      forgiveness: 7,
      sweetSpot: 7,
      defense: 7,
      attack: 7,
      bestFor: "",
      recommendedFor: "",
      notIdealFor: "",
      isSample: true,
    },
    visual: DEFAULT_VISUAL,
    model: {
      status: "unavailable",
      url: null,
      previewUrl: null,
      posterUrl: null,
      thumbnailUrl: null,
      explodedUrl: null,
      version: "1",
      supportsExplode: false,
      source: null,
      licenseStatus: "none",
      attribution: null,
      creator: null,
      usageRestrictions: null,
      approvalStatus: "pending",
      notes: null,
    },
    ...derived,
    images: [],
    offers: [],
    review: null,
  };
}

export async function adminGetRacket(id: number): Promise<RacketInput | null> {
  const db = await getDb();
  const r = await db.query.products.findFirst({
    where: eq(schema.products.id, id),
    with: {
      specs: true,
      evaluation: true,
      styles: { with: { style: true } },
      models: true,
      hotspots: { orderBy: (h, { asc }) => [asc(h.sortOrder)] },
      annotations: { orderBy: (a, { asc }) => [asc(a.sortOrder)] },
      overlays: true,
      images: { orderBy: (i, { asc }) => [asc(i.sortOrder)] },
      offers: true,
      review: true,
    },
  });
  if (!r) return null;
  const blank = blankRacket(r.brandId);
  const m = r.models.find((x) => x.role === "primary");
  const s = r.specs;
  const e = r.evaluation;
  return {
    id: r.id,
    basics: {
      brandId: r.brandId,
      slug: r.slug,
      name: r.name,
      collection: r.collection,
      year: r.year,
      shortDescription: r.shortDescription,
      description: r.description,
      status: r.status,
      featured: r.featured,
      isNew: r.isNew,
      levels: r.levels as PlayerLevel[],
      styles: r.styles.map((x) => x.style.slug as PlayingStyle),
      indicativePriceEur: r.indicativePriceCents ? Math.round(r.indicativePriceCents / 100) : null,
      dataStatus: r.dataStatus,
    },
    specs: s
      ? {
          shape: s.shape,
          weightMinG: s.weightMinG,
          weightMaxG: s.weightMaxG,
          balance: s.balance,
          balanceMm: s.balanceMm,
          hardness: s.hardness,
          thicknessMm: s.thicknessMm,
          frameMaterial: s.frameMaterial,
          faceMaterial: s.faceMaterial,
          coreMaterial: s.coreMaterial,
          surfaceFinish: s.surfaceFinish,
          verification: s.verification,
          sourceNote: s.sourceNote,
          sourceUrl: s.sourceUrl,
        }
      : blank.specs,
    evaluation: e
      ? {
          power: e.power,
          control: e.control,
          maneuverability: e.maneuverability,
          forgiveness: e.forgiveness,
          sweetSpot: e.sweetSpot,
          defense: e.defense,
          attack: e.attack,
          bestFor: e.bestFor,
          recommendedFor: e.recommendedFor,
          notIdealFor: e.notIdealFor,
          isSample: e.isSample,
        }
      : blank.evaluation,
    visual: { ...DEFAULT_VISUAL, ...r.visual },
    model: m
      ? {
          status: m.status,
          url: m.url,
          previewUrl: m.previewUrl,
          posterUrl: m.posterUrl,
          thumbnailUrl: m.thumbnailUrl,
          explodedUrl: m.explodedUrl,
          version: m.version,
          supportsExplode: m.supportsExplode,
          source: m.source,
          licenseStatus: m.licenseStatus,
          attribution: m.attribution,
          creator: m.creator,
          usageRestrictions: m.usageRestrictions,
          approvalStatus: m.approvalStatus,
          notes: m.notes,
        }
      : blank.model,
    hotspots: r.hotspots.map((h) => ({
      key: h.key,
      label: h.label,
      body: h.body,
      u: h.u,
      v: h.v,
      w: h.w,
      view: h.view as CameraView,
      specKey: (h.specKey ?? null) as SpecKey | null,
      basis: h.basis as Basis,
    })),
    annotations: r.annotations.map((a) => ({ view: a.view as CameraView, title: a.title, body: a.body, basis: a.basis as Basis })),
    overlays: r.overlays.map((o) => ({ kind: o.kind, enabled: o.enabled, basis: o.basis, note: o.note, params: o.params })),
    images: r.images.map((i) => ({
      url: i.url,
      alt: i.alt,
      kind: i.kind,
      source: i.source,
      licenseStatus: i.licenseStatus,
      attribution: i.attribution,
      creator: i.creator,
      usageRestrictions: i.usageRestrictions,
      approvalStatus: i.approvalStatus,
    })),
    offers: r.offers.map((o) => ({
      id: o.id,
      retailerId: o.retailerId,
      productUrl: o.productUrl,
      affiliateUrl: o.affiliateUrl,
      priceEur: o.priceCents / 100,
      currency: o.currency,
      stockStatus: o.stockStatus,
      available: o.available,
      shippingInfo: o.shippingInfo,
      isDemo: o.isDemo,
      active: o.active,
    })),
    review: r.review
      ? {
          title: r.review.title,
          summary: r.review.summary,
          body: r.review.body,
          pros: r.review.pros,
          cons: r.review.cons,
          verdict: r.review.verdict,
          inspectionNotes: r.review.inspectionNotes,
          modelQualityNote: r.review.modelQualityNote,
          isSample: r.review.isSample,
        }
      : null,
  };
}

/** Stored bounding box of the primary model, used to place generated hotspots. */
export async function adminModelBbox(productId: number) {
  const db = await getDb();
  const [row] = await db
    .select({ bbox: schema.modelAssets.bbox, url: schema.modelAssets.url })
    .from(schema.modelAssets)
    .where(and(eq(schema.modelAssets.productId, productId), eq(schema.modelAssets.role, "primary")))
    .limit(1);
  return row ?? null;
}

function firstDuplicate<T>(items: T[], key: (t: T) => string | number): string | number | null {
  const seen = new Set<string | number>();
  for (const it of items) {
    const k = key(it);
    if (seen.has(k)) return k;
    seen.add(k);
  }
  return null;
}

/**
 * Saves a racket. Returns the offers' ids by retailer (one offer per retailer)
 * so the editor can adopt the ids of offers it just created: otherwise the next
 * save would recreate them and break /go/<id> links already on pages.
 */
export async function adminSaveRacket(
  input: RacketInput,
): Promise<{ id: number; slug: string; previousSlug: string | null; offerIds: Record<number, number> }> {
  const db = await getDb();
  const b = input.basics;

  const [slugClash] = await db
    .select({ id: schema.products.id })
    .from(schema.products)
    .where(input.id ? and(eq(schema.products.slug, b.slug), ne(schema.products.id, input.id)) : eq(schema.products.slug, b.slug))
    .limit(1);
  if (slugClash) throw new SaveError(`The slug "${b.slug}" is already used by another racket.`);
  if (input.specs.weightMinG !== null && input.specs.weightMaxG !== null && input.specs.weightMinG > input.specs.weightMaxG) {
    throw new SaveError("The minimum weight is above the maximum weight.");
  }
  const dupKey = firstDuplicate(input.hotspots, (h) => h.key);
  if (dupKey !== null) throw new SaveError(`Two hotspots use the key "${dupKey}". Keys must be unique.`);
  const dupOverlay = firstDuplicate(input.overlays, (o) => o.kind);
  if (dupOverlay !== null) throw new SaveError(`The "${dupOverlay}" overlay is listed twice.`);
  if (firstDuplicate(input.offers, (o) => o.retailerId) !== null) throw new SaveError("A retailer can only have one offer per racket.");
  // Same rule as the /go redirect: a live link must stay on the retailer's allowed domains.
  const linked = input.offers.filter((o) => !isPlaceholderLink(o.affiliateUrl));
  if (linked.length) {
    const rows = await db
      .select({ id: schema.retailers.id, name: schema.retailers.name, allowedDomains: schema.retailers.allowedDomains })
      .from(schema.retailers)
      .where(inArray(schema.retailers.id, linked.map((o) => o.retailerId)));
    for (const o of linked) {
      const r = rows.find((x) => x.id === o.retailerId);
      if (r && r.allowedDomains.length && !hostMatches(o.affiliateUrl!, r.allowedDomains)) {
        throw new SaveError(`The ${r.name} affiliate link isn't on its allowed domains (${r.allowedDomains.join(", ")}). Fix the link, or add the domain to the retailer first.`);
      }
    }
  }
  if (input.model.status !== "unavailable" && !input.model.url) {
    throw new SaveError('Add a model file or URL, or set the model status to "No model yet".');
  }
  if (input.model.status === "unavailable" && input.model.url) {
    throw new SaveError('The model status is "No model yet" but a model file is set. Choose where the model comes from (official, licensed, platform or placeholder), or remove the file.');
  }
  if (b.status === "published" && input.model.status !== "unavailable" && input.model.approvalStatus === "rejected") {
    throw new SaveError("The 3D model is marked rejected. Replace it, or set the model to unavailable, before publishing.");
  }

  return db.transaction(async (tx) => {
    const [category] = await tx.select().from(schema.productCategories).where(eq(schema.productCategories.slug, "rackets")).limit(1);
    if (!category) throw new SaveError('The "rackets" category is missing. Run the seed first.');

    const productValues = {
      categoryId: category.id,
      brandId: b.brandId,
      slug: b.slug,
      name: b.name,
      collection: b.collection,
      year: b.year,
      shortDescription: b.shortDescription,
      description: b.description,
      status: b.status,
      featured: b.featured,
      isNew: b.isNew,
      levels: b.levels,
      dataStatus: b.dataStatus,
      visual: input.visual,
      indicativePriceCents: b.indicativePriceEur ? Math.round(b.indicativePriceEur * 100) : null,
      updatedAt: new Date(),
    };

    let productId: number;
    let previousSlug: string | null = null;
    if (input.id) {
      const [prev] = await tx
        .select({ slug: schema.products.slug, publishedAt: schema.products.publishedAt })
        .from(schema.products)
        .where(eq(schema.products.id, input.id))
        .limit(1);
      if (!prev) throw new SaveError("This racket no longer exists.");
      previousSlug = prev.slug;
      await tx
        .update(schema.products)
        .set({ ...productValues, publishedAt: b.status === "published" ? (prev.publishedAt ?? new Date()) : prev.publishedAt })
        .where(eq(schema.products.id, input.id));
      productId = input.id;
    } else {
      const [row] = await tx
        .insert(schema.products)
        .values({ ...productValues, publishedAt: b.status === "published" ? new Date() : null })
        .returning({ id: schema.products.id });
      productId = row.id;
    }

    // Manufacturer specification and platform evaluation (1:1, replaced).
    await tx.delete(schema.racketSpecs).where(eq(schema.racketSpecs.productId, productId));
    await tx.insert(schema.racketSpecs).values({ productId, ...input.specs, verifiedAt: input.specs.verification === "verified" ? new Date() : null });
    await tx.delete(schema.platformEvaluations).where(eq(schema.platformEvaluations.productId, productId));
    await tx.insert(schema.platformEvaluations).values({ productId, ...input.evaluation, methodologyVersion: siteConfig.scoreMethodology });

    await tx.delete(schema.productPlayingStyles).where(eq(schema.productPlayingStyles.productId, productId));
    if (b.styles.length) {
      const styles = await tx.select().from(schema.playingStyles).where(inArray(schema.playingStyles.slug, b.styles));
      if (styles.length) await tx.insert(schema.productPlayingStyles).values(styles.map((st) => ({ productId, styleId: st.id })));
    }

    // Primary 3D model. File facts (size, triangles, bounds) are kept while the
    // URL is unchanged, filled from the generator manifest for generated
    // models, and cleared for a new external file.
    const m = input.model;
    const [primary] = await tx
      .select()
      .from(schema.modelAssets)
      .where(and(eq(schema.modelAssets.productId, productId), eq(schema.modelAssets.role, "primary")))
      .limit(1);
    const url = m.status === "unavailable" ? null : m.url;
    const fromManifest = url ? Object.values(generated).find((g) => stripQuery(g.url) === stripQuery(url)) : undefined;
    const sameFile = !!primary && !!url && primary.url === url;
    const modelValues = {
      productId,
      role: "primary" as const,
      variantKind: "standard" as const,
      label:
        m.status === "unavailable" ? "No model yet" : m.status === "placeholder" ? "Placeholder model" : m.status === "platform" ? "Platform model" : "Model",
      status: m.status,
      format: url && stripQuery(url).toLowerCase().endsWith(".gltf") ? ("gltf" as const) : ("glb" as const),
      url,
      previewUrl: m.status === "unavailable" ? null : m.previewUrl,
      posterUrl: m.posterUrl,
      thumbnailUrl: m.thumbnailUrl,
      explodedUrl: m.explodedUrl,
      version: m.version,
      supportsExplode: m.supportsExplode,
      fileSizeBytes: fromManifest?.bytes ?? (sameFile ? primary.fileSizeBytes : null),
      triangleCount: fromManifest?.triangles ?? (sameFile ? primary.triangleCount : null),
      bbox: fromManifest?.bbox ?? (sameFile ? primary.bbox : null),
      source: m.source,
      licenseStatus: m.licenseStatus,
      attribution: m.attribution,
      creator: m.creator,
      usageRestrictions: m.usageRestrictions,
      approvalStatus: m.approvalStatus,
      notes: m.notes,
      updatedAt: new Date(),
    };
    if (primary) await tx.update(schema.modelAssets).set(modelValues).where(eq(schema.modelAssets.id, primary.id));
    else await tx.insert(schema.modelAssets).values(modelValues);

    await tx.delete(schema.modelHotspots).where(eq(schema.modelHotspots.productId, productId));
    if (input.hotspots.length) await tx.insert(schema.modelHotspots).values(input.hotspots.map((h, i) => ({ ...h, productId, sortOrder: i })));
    await tx.delete(schema.modelAnnotations).where(eq(schema.modelAnnotations.productId, productId));
    if (input.annotations.length) await tx.insert(schema.modelAnnotations).values(input.annotations.map((a, i) => ({ ...a, productId, sortOrder: i })));
    await tx.delete(schema.modelOverlays).where(eq(schema.modelOverlays.productId, productId));
    if (input.overlays.length) await tx.insert(schema.modelOverlays).values(input.overlays.map((o) => ({ ...o, productId })));
    await tx.delete(schema.productImages).where(eq(schema.productImages.productId, productId));
    if (input.images.length) await tx.insert(schema.productImages).values(input.images.map((im, i) => ({ ...im, productId, sortOrder: i })));

    // Offers: keep ids stable (click history refers to them), delete removed ones.
    const keepIds = input.offers.map((o) => o.id).filter((x): x is number => typeof x === "number");
    await tx
      .delete(schema.offers)
      .where(keepIds.length ? and(eq(schema.offers.productId, productId), notInArray(schema.offers.id, keepIds)) : eq(schema.offers.productId, productId));
    for (const o of input.offers) {
      const values = {
        productId,
        retailerId: o.retailerId,
        productUrl: o.productUrl,
        affiliateUrl: o.affiliateUrl,
        priceCents: Math.round(o.priceEur * 100),
        currency: o.currency,
        stockStatus: o.stockStatus,
        available: o.available,
        shippingInfo: o.shippingInfo,
        isDemo: o.isDemo,
        active: o.active,
        lastCheckedAt: new Date(),
        updatedAt: new Date(),
      };
      if (o.id) await tx.update(schema.offers).set(values).where(and(eq(schema.offers.id, o.id), eq(schema.offers.productId, productId)));
      else await tx.insert(schema.offers).values(values);
    }

    // Editorial review: the upsert keeps the original publish date.
    if (input.review) {
      const review = { ...input.review, author: input.review.isSample ? "Paladex editorial (sample)" : "Paladex editorial", updatedAt: new Date() };
      await tx
        .insert(schema.editorialReviews)
        .values({ productId, ...review, publishedAt: new Date() })
        .onConflictDoUpdate({ target: schema.editorialReviews.productId, set: review });
    } else {
      await tx.delete(schema.editorialReviews).where(eq(schema.editorialReviews.productId, productId));
    }

    const savedOffers = await tx.select({ id: schema.offers.id, retailerId: schema.offers.retailerId }).from(schema.offers).where(eq(schema.offers.productId, productId));
    const offerIds = Object.fromEntries(savedOffers.map((o) => [o.retailerId, o.id]));
    return { id: productId, slug: b.slug, previousSlug, offerIds };
  });
}

export async function adminDeleteRacket(id: number): Promise<string | null> {
  const db = await getDb();
  return db.transaction(async (tx) => {
    const [row] = await tx.select({ slug: schema.products.slug }).from(schema.products).where(eq(schema.products.id, id)).limit(1);
    if (!row) return null;
    // Explicit deletes so this also works where foreign-key cascades are off.
    // Click history (affiliate_clicks) is kept for reporting.
    await tx.delete(schema.offers).where(eq(schema.offers.productId, id));
    await tx.delete(schema.productImages).where(eq(schema.productImages.productId, id));
    await tx.delete(schema.modelOverlays).where(eq(schema.modelOverlays.productId, id));
    await tx.delete(schema.modelAnnotations).where(eq(schema.modelAnnotations.productId, id));
    await tx.delete(schema.modelHotspots).where(eq(schema.modelHotspots.productId, id));
    await tx.delete(schema.modelAssets).where(eq(schema.modelAssets.productId, id));
    await tx.delete(schema.editorialReviews).where(eq(schema.editorialReviews.productId, id));
    await tx.delete(schema.userReviews).where(eq(schema.userReviews.productId, id));
    await tx.delete(schema.productPlayingStyles).where(eq(schema.productPlayingStyles.productId, id));
    await tx.delete(schema.platformEvaluations).where(eq(schema.platformEvaluations.productId, id));
    await tx.delete(schema.racketSpecs).where(eq(schema.racketSpecs.productId, id));
    await tx.delete(schema.products).where(eq(schema.products.id, id));
    return row.slug;
  });
}

/* ---------------------------------------------------------------- brands */

export async function adminListBrands() {
  const db = await getDb();
  return db
    .select({
      id: schema.brands.id,
      slug: schema.brands.slug,
      name: schema.brands.name,
      country: schema.brands.country,
      description: schema.brands.description,
      websiteUrl: schema.brands.websiteUrl,
      logoUrl: schema.brands.logoUrl,
      rackets: sql<number>`(select count(*) from products p where p.brand_id = "brands"."id")`,
    })
    .from(schema.brands)
    .orderBy(schema.brands.name);
}

export async function adminSaveBrand(input: {
  id?: number;
  slug: string;
  name: string;
  country: string | null;
  description: string;
  websiteUrl: string | null;
  logoUrl: string | null;
}) {
  const db = await getDb();
  const { id, ...values } = input;
  const [clash] = await db.select({ id: schema.brands.id }).from(schema.brands).where(eq(schema.brands.slug, values.slug)).limit(1);
  if (clash && clash.id !== id) throw new SaveError(`The brand slug "${values.slug}" is already used.`);
  if (id) await db.update(schema.brands).set({ ...values, updatedAt: new Date() }).where(eq(schema.brands.id, id));
  else await db.insert(schema.brands).values(values);
}

export async function adminDeleteBrand(id: number) {
  const db = await getDb();
  const [used] = await db.select({ n: sql<number>`count(*)` }).from(schema.products).where(eq(schema.products.brandId, id));
  if (used.n > 0) throw new SaveError("This brand still has rackets. Move or delete them first.");
  await db.delete(schema.brands).where(eq(schema.brands.id, id));
}

/* ------------------------------------------------------------- retailers */

export async function adminListRetailers() {
  const db = await getDb();
  return db
    .select({
      id: schema.retailers.id,
      slug: schema.retailers.slug,
      name: schema.retailers.name,
      websiteUrl: schema.retailers.websiteUrl,
      logoUrl: schema.retailers.logoUrl,
      country: schema.retailers.country,
      currency: schema.retailers.currency,
      shippingInfo: schema.retailers.shippingInfo,
      affiliateNetwork: schema.retailers.affiliateNetwork,
      allowedDomains: schema.retailers.allowedDomains,
      isDemo: schema.retailers.isDemo,
      active: schema.retailers.active,
      offers: sql<number>`(select count(*) from offers o where o.retailer_id = "retailers"."id")`,
    })
    .from(schema.retailers)
    .orderBy(schema.retailers.name);
}

export async function adminSaveRetailer(input: {
  id?: number;
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
}) {
  const db = await getDb();
  const { id, ...values } = input;
  const [clash] = await db.select({ id: schema.retailers.id }).from(schema.retailers).where(eq(schema.retailers.slug, values.slug)).limit(1);
  if (clash && clash.id !== id) throw new SaveError(`The retailer slug "${values.slug}" is already used.`);
  if (id) await db.update(schema.retailers).set({ ...values, updatedAt: new Date() }).where(eq(schema.retailers.id, id));
  else await db.insert(schema.retailers).values(values);
}

export async function adminDeleteRetailer(id: number) {
  const db = await getDb();
  await db.transaction(async (tx) => {
    await tx.delete(schema.offers).where(eq(schema.offers.retailerId, id));
    await tx.delete(schema.retailers).where(eq(schema.retailers.id, id));
  });
}

/* ------------------------------------------------------------- dashboard */

export async function adminDashboardStats() {
  const db = await getDb();
  const since = sql`(unixepoch() - 30 * 86400) * 1000`;
  const [products, models, offers, clicks, events] = await Promise.all([
    db.select({ status: schema.products.status, n: sql<number>`count(*)` }).from(schema.products).groupBy(schema.products.status),
    db
      .select({ status: schema.modelAssets.status, n: sql<number>`count(*)` })
      .from(schema.modelAssets)
      .where(eq(schema.modelAssets.role, "primary"))
      .groupBy(schema.modelAssets.status),
    db
      .select({
        total: sql<number>`count(*)`,
        placeholder: sql<number>`coalesce(sum(case when ${schema.offers.affiliateUrl} is null or trim(${schema.offers.affiliateUrl}) = '' or ${schema.offers.affiliateUrl} = 'AFFILIATE_URL_HERE' then 1 else 0 end), 0)`,
        demo: sql<number>`coalesce(sum(${schema.offers.isDemo}), 0)`,
      })
      .from(schema.offers),
    db.select({ n: sql<number>`count(*)` }).from(schema.affiliateClicks).where(sql`${schema.affiliateClicks.createdAt} > ${since}`),
    db.select({ n: sql<number>`count(*)` }).from(schema.analyticsEvents).where(sql`${schema.analyticsEvents.createdAt} > ${since}`),
  ]);
  const count = (rows: Array<{ status: string; n: number }>, s: string) => rows.find((r) => r.status === s)?.n ?? 0;
  return {
    published: count(products, "published"),
    drafts: count(products, "draft"),
    models: Object.fromEntries(models.map((m) => [m.status, m.n])) as Partial<Record<ModelStatus, number>>,
    offers: offers[0] ?? { total: 0, placeholder: 0, demo: 0 },
    clicks30: clicks[0]?.n ?? 0,
    events30: events[0]?.n ?? 0,
  };
}
