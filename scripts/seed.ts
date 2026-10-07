/**
 * Seeds the database with the sample catalog.
 *   npm run db:seed            # only if the catalog is empty
 *   npm run db:seed -- --force # wipe catalog tables and reseed
 *
 * Analytics events and affiliate clicks are never deleted.
 */
import { existsSync, readFileSync } from "node:fs";
import { sql } from "drizzle-orm";
import { loadEnv } from "./lib/env";
import { getDb, schema } from "../src/server/db/connection";
import { seedBrands } from "../src/data/seed/brands";
import { seedRackets, SPEC_SOURCE_NOTE } from "../src/data/seed/rackets";
import { AFFILIATE_PLACEHOLDER, seedRetailers } from "../src/data/seed/retailers";
import { photoDesigns } from "../src/data/designs";
import { modelDefaults } from "../src/lib/model-defaults";
import { siteConfig } from "../src/config/site";
import { STYLE_INFO } from "../src/domain/vocab";
import { PLAYING_STYLES } from "../src/domain/types";

interface ManifestEntry {
  kind: "platform" | "placeholder";
  url: string;
  previewUrl: string;
  bytes: number;
  triangles: number;
  bbox: { min: number[]; max: number[] };
  version: string;
}

/** Round to a retail-looking price ending in .95 (integer cents). */
const retailCents = (eur: number) => Math.max(1, Math.round(eur)) * 100 - 5;

async function main() {
  loadEnv();
  const force = process.argv.includes("--force");
  const db = await getDb();
  const manifest: Record<string, ManifestEntry> = existsSync("src/data/models.generated.json")
    ? JSON.parse(readFileSync("src/data/models.generated.json", "utf8"))
    : {};

  const existing = await db.select({ n: sql<number>`count(*)` }).from(schema.products);
  if (existing[0].n > 0 && !force) {
    console.log(`catalog already has ${existing[0].n} products; use --force to reseed`);
    return;
  }

  // Children first (foreign keys).
  for (const table of [
    schema.offers,
    schema.productImages,
    schema.modelOverlays,
    schema.modelAnnotations,
    schema.modelHotspots,
    schema.modelAssets,
    schema.editorialReviews,
    schema.userReviews,
    schema.productPlayingStyles,
    schema.platformEvaluations,
    schema.racketSpecs,
    schema.products,
    schema.playingStyles,
    schema.retailers,
    schema.brands,
    schema.productCategories,
  ]) {
    await db.delete(table);
  }

  const [category] = await db
    .insert(schema.productCategories)
    .values({ slug: "rackets", name: "Padel rackets", description: "Padel rackets (palas)." })
    .returning();

  const styleIds = new Map<string, number>();
  for (const slug of PLAYING_STYLES) {
    const [row] = await db
      .insert(schema.playingStyles)
      .values({ slug, name: STYLE_INFO[slug].label, description: STYLE_INFO[slug].description })
      .returning();
    styleIds.set(slug, row.id);
  }

  const brandIds = new Map<string, number>();
  for (const b of seedBrands) {
    const [row] = await db.insert(schema.brands).values(b).returning();
    brandIds.set(b.slug, row.id);
  }

  const retailerIds = new Map<string, number>();
  for (const r of seedRetailers) {
    const { priceFactor: _ignored, allowedDomains, ...rest } = r;
    void _ignored;
    const [row] = await db
      .insert(schema.retailers)
      .values({ ...rest, allowedDomains: [...allowedDomains], isDemo: true, active: true })
      .returning();
    retailerIds.set(r.slug, row.id);
  }

  const now = new Date();
  for (const [index, r] of seedRackets.entries()) {
    const design = photoDesigns[r.slug];
    const model = manifest[r.slug];
    const frontImage = r.images?.find((i) => i.kind === "front");
    const [product] = await db
      .insert(schema.products)
      .values({
        categoryId: category.id,
        brandId: brandIds.get(r.brand)!,
        slug: r.slug,
        name: r.name,
        collection: r.collection,
        year: r.year,
        shortDescription: r.shortDescription,
        description: r.description,
        status: "published",
        featured: !!r.featured,
        isNew: !!r.isNew,
        dataStatus: r.specs.verification === "verified" ? "verified" : "unverified",
        levels: r.levels,
        visual: r.visual,
        proPlayers: r.proPlayers ?? [],
        roundup: r.roundup ?? null,
        indicativePriceCents: r.indicativePriceEur === null ? null : retailCents(r.indicativePriceEur),
        currency: "EUR",
        publishedAt: new Date(now.getTime() - (seedRackets.length - index) * 86_400_000),
        createdAt: new Date(now.getTime() - (seedRackets.length - index) * 86_400_000),
      })
      .returning();

    await db.insert(schema.racketSpecs).values({ productId: product.id, ...r.specs, sourceNote: r.specSourceNote ?? SPEC_SOURCE_NOTE, sourceUrl: r.specSourceUrl ?? null });
    await db.insert(schema.platformEvaluations).values({
      productId: product.id,
      ...r.evaluation,
      methodologyVersion: siteConfig.scoreMethodology,
      isSample: true,
    });
    for (const s of r.styles) {
      await db.insert(schema.productPlayingStyles).values({ productId: product.id, styleId: styleIds.get(s)! });
    }

    // 3D model + derived annotations.
    const kind = r.noModel || !model ? "none" : model.kind;
    if (kind !== "none") {
      await db.insert(schema.modelAssets).values({
        productId: product.id,
        role: "primary",
        variantKind: "standard",
        label: kind === "platform" ? "Platform model" : "Placeholder model",
        status: kind,
        format: "glb",
        url: model.url,
        previewUrl: model.previewUrl,
        version: model.version,
        posterUrl: frontImage?.url ?? null,
        thumbnailUrl: frontImage?.url ?? null,
        supportsExplode: true,
        fileSizeBytes: model.bytes,
        triangleCount: model.triangles,
        bbox: model.bbox,
        source:
          kind === "platform"
            ? r.imageSource
              ? "Paladex 3D: modelled from the brand's product photos, supplied by the site owner"
              : "Paladex 3D: modelled from reference photos supplied by the site owner"
            : "Paladex placeholder generator (generic racket of this shape class)",
        licenseStatus: kind === "platform" ? "supplied" : "owned",
        creator: "Paladex",
        attribution: null,
        usageRestrictions: null,
        approvalStatus: "approved",
        notes:
          kind === "platform"
            ? r.imageSource
              ? "Geometry traced from the front product photo; print projected from it; profile from the listed thickness. Frame details and the back face are approximated (the back repeats the front print)."
              : "Geometry traced from the front photo; print projected from the photo; side screws, collar and grip modelled from the angled photos."
            : "Generic design in Paladex colours. Replace with a platform, licensed or official model.",
      });
    } else {
      await db.insert(schema.modelAssets).values({
        productId: product.id,
        role: "primary",
        status: "unavailable",
        label: "No model yet",
        url: null,
        source: null,
        licenseStatus: "none",
        approvalStatus: "pending",
        notes: "No 3D model yet. The page shows an illustration and '3D model coming soon'.",
      });
    }

    const trace = design?.trace;
    const throatY = trace?.throat.length ? trace.throat.reduce((s, p) => s + p[1], 0) / trace.throat.length : undefined;
    const defaults = modelDefaults({
      ...r.specs,
      sweetSpotScore: r.evaluation.sweetSpot,
      kind,
      bbox: model?.bbox ?? null,
      outline: trace?.frameOuter,
      throatY,
      sweetSpotV: design?.sweetSpotV,
      screwsY: design?.screws?.y,
      hasBumper: kind === "placeholder",
    });
    if (defaults.hotspots.length) await db.insert(schema.modelHotspots).values(defaults.hotspots.map((h) => ({ ...h, productId: product.id })));
    await db.insert(schema.modelAnnotations).values(defaults.annotations.map((a) => ({ ...a, productId: product.id })));
    await db.insert(schema.modelOverlays).values(
      defaults.overlays.map((o) => ({ ...o, productId: product.id, enabled: o.kind !== "material-layers" || kind !== "none" })),
    );

    for (const [i, img] of (r.images ?? []).entries()) {
      await db.insert(schema.productImages).values({
        productId: product.id,
        url: img.url,
        alt: img.alt,
        kind: img.kind,
        sortOrder: i,
        source: r.imageSource ?? "Supplied by the site owner",
        licenseStatus: r.imageSource ? "pending" : "supplied",
        approvalStatus: "approved",
      });
    }

    // Demo offers: clearly marked, placeholder affiliate links, example.com product pages.
    for (const [ri, ret] of seedRetailers.entries()) {
      if (r.indicativePriceEur === null) break; // no known price: no demo offers
      if (r.slug === "head-vibe-2026" && ret.slug === "store-c") continue; // not every retailer stocks every racket
      const price = retailCents(r.indicativePriceEur * ret.priceFactor);
      const stock = (index + ri) % 7 === 0 ? "out_of_stock" : (index + ri) % 5 === 0 ? "low_stock" : "in_stock";
      await db.insert(schema.offers).values({
        productId: product.id,
        retailerId: retailerIds.get(ret.slug)!,
        productUrl: `${ret.websiteUrl}/rackets/${r.slug}`,
        affiliateUrl: AFFILIATE_PLACEHOLDER,
        priceCents: price,
        currency: "EUR",
        stockStatus: stock,
        available: stock !== "out_of_stock",
        country: "EU",
        shippingInfo: ret.shippingInfo,
        lastCheckedAt: now,
        isDemo: true,
        active: true,
      });
    }

    if (r.review)
      await db.insert(schema.editorialReviews).values({
        productId: product.id,
        ...r.review,
        modelQualityNote:
          kind === "platform"
            ? "Platform-created model: geometry traced from the front photo, print projected from it; edge details approximated."
            : kind === "placeholder"
              ? "Placeholder model: correct shape class, generic design. Not this racket's real look."
              : "No 3D model yet.",
        author: "Paladex editorial (sample)",
        isSample: true,
        publishedAt: now,
      });
  }

  console.log(`seeded ${seedRackets.length} rackets, ${seedBrands.length} brands, ${seedRetailers.length} demo retailers`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
