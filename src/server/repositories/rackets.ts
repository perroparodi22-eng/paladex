/**
 * Racket repository: reads products from the database and maps them to the
 * domain types the UI uses. Public reads are cached and tagged "catalog";
 * admin writes call revalidateTag("catalog") so pages refresh.
 */
import "server-only";
import { unstable_cache } from "next/cache";
import { and, eq, inArray, sql } from "drizzle-orm";
import { getDb, schema } from "@/server/db";
import type {
  Annotation,
  ApprovalStatus,
  Balance,
  ProPlayer,
  ReviewRoundup,
  Basis,
  CameraView,
  EditorialReview,
  Hardness,
  Hotspot,
  LicenseStatus,
  Model3D,
  ModelStatus,
  Offer,
  OverlayConfig,
  PlayerLevel,
  PlayingStyle,
  Racket,
  RacketShape,
  RacketSummary,
  SpecKey,
  StockStatus,
  SurfaceFinish,
  UserRatingSummary,
  Verification,
} from "@/domain/types";
import { overallScore } from "@/lib/scores";
import { isPlaceholderLink } from "@/lib/urls";

export const CATALOG_TAG = "catalog";

const iso = (d: Date | null | undefined) => (d ? new Date(d).toISOString() : null);

async function querySummaries(filter: { slugs?: string[]; includeDrafts?: boolean } = {}) {
  const db = await getDb();
  const conditions = [];
  if (!filter.includeDrafts) conditions.push(eq(schema.products.status, "published"));
  if (filter.slugs?.length) conditions.push(inArray(schema.products.slug, filter.slugs));
  return db.query.products.findMany({
    where: conditions.length ? and(...conditions) : undefined,
    with: {
      brand: true,
      specs: true,
      evaluation: true,
      styles: { with: { style: true } },
      models: true,
      images: { orderBy: (i, { asc }) => [asc(i.sortOrder)] },
      offers: { with: { retailer: true } },
    },
    orderBy: (p, { desc }) => [desc(p.featured), desc(p.publishedAt)],
  });
}

type SummaryRow = Awaited<ReturnType<typeof querySummaries>>[number];

async function ratings(productIds: number[]): Promise<Map<number, UserRatingSummary>> {
  if (!productIds.length) return new Map();
  const db = await getDb();
  const rows = await db
    .select({
      productId: schema.userReviews.productId,
      avg: sql<number>`avg(${schema.userReviews.rating})`,
      n: sql<number>`count(*)`,
    })
    .from(schema.userReviews)
    .where(and(eq(schema.userReviews.status, "approved"), inArray(schema.userReviews.productId, productIds)))
    .groupBy(schema.userReviews.productId);
  return new Map(rows.map((r) => [r.productId, { average: Math.round(r.avg * 10) / 10, count: r.n }]));
}

function mapOffer(o: SummaryRow["offers"][number]): Offer {
  return {
    id: o.id,
    retailer: {
      id: o.retailer.id,
      slug: o.retailer.slug,
      name: o.retailer.name,
      websiteUrl: o.retailer.websiteUrl,
      logoUrl: o.retailer.logoUrl,
      country: o.retailer.country,
      currency: o.retailer.currency,
      shippingInfo: o.retailer.shippingInfo,
      affiliateNetwork: o.retailer.affiliateNetwork,
      allowedDomains: o.retailer.allowedDomains,
      isDemo: o.retailer.isDemo,
      active: o.retailer.active,
    },
    price: { amountCents: o.priceCents, currency: o.currency },
    stockStatus: o.stockStatus as StockStatus,
    available: o.available,
    country: o.country,
    shippingInfo: o.shippingInfo,
    lastCheckedAt: iso(o.lastCheckedAt),
    linkIsPlaceholder: isPlaceholderLink(o.affiliateUrl),
    isDemo: o.isDemo || o.retailer.isDemo,
  };
}

function visibleOffers(row: SummaryRow): Offer[] {
  return row.offers
    .filter((o) => o.active && o.retailer.active)
    .map(mapOffer)
    .sort((a, b) => Number(b.available) - Number(a.available) || a.price.amountCents - b.price.amountCents);
}

function primaryModel(row: SummaryRow) {
  return row.models.find((m) => m.role === "primary") ?? null;
}

function mapSummary(row: SummaryRow, rating?: UserRatingSummary): RacketSummary {
  const specs = row.specs;
  const ev = row.evaluation;
  const offers = visibleOffers(row);
  const available = offers.filter((o) => o.available);
  const model = primaryModel(row);
  const image = row.images[0];
  const shape = (specs?.shape ?? "teardrop") as RacketShape;
  return {
    id: row.id,
    slug: row.slug,
    name: row.name,
    fullName: `${row.brand.name} ${row.name}`,
    brand: { id: row.brand.id, slug: row.brand.slug, name: row.brand.name },
    year: row.year,
    shortDescription: row.shortDescription,
    shape,
    weightMinG: specs?.weightMinG ?? null,
    weightMaxG: specs?.weightMaxG ?? null,
    balance: (specs?.balance ?? null) as Balance | null,
    hardness: (specs?.hardness ?? null) as Hardness | null,
    surfaceFinish: (specs?.surfaceFinish ?? null) as SurfaceFinish | null,
    levels: (row.levels ?? []) as PlayerLevel[],
    styles: row.styles.map((s) => s.style.slug as PlayingStyle),
    scores: ev
      ? {
          power: ev.power,
          control: ev.control,
          maneuverability: ev.maneuverability,
          forgiveness: ev.forgiveness,
          sweetSpot: ev.sweetSpot,
          defense: ev.defense,
          attack: ev.attack,
          overall: overallScore(ev),
        }
      : null,
    priceFrom: available.length ? available[0].price : null,
    indicativePrice: row.indicativePriceCents ? { amountCents: row.indicativePriceCents, currency: row.currency } : null,
    offerCount: available.length,
    modelStatus: (model?.status ?? "unavailable") as ModelStatus,
    modelPreviewUrl: model?.previewUrl ?? null,
    modelUrl: model?.url ?? null,
    imageUrl: image?.url ?? null,
    imageAlt: image?.alt ?? `${row.brand.name} ${row.name} padel racket`,
    visual: row.visual,
    featured: row.featured,
    isNew: row.isNew,
    dataStatus: row.dataStatus as Verification,
    userRating: rating ?? null,
    createdAt: iso(row.createdAt)!,
    proPlayers: (row.proPlayers ?? []) as ProPlayer[],
  };
}

/* ------------------------------------------------------------ queries */

async function loadSummaries(): Promise<RacketSummary[]> {
  const rows = await querySummaries();
  const r = await ratings(rows.map((x) => x.id));
  return rows.map((row) => mapSummary(row, r.get(row.id)));
}

/** All published rackets (cards, catalog, showroom, finder, search). */
export const listRacketSummaries = unstable_cache(loadSummaries, ["racket-summaries"], { tags: [CATALOG_TAG], revalidate: 3600 });

async function loadRacket(slug: string, includeDrafts = false): Promise<Racket | null> {
  const db = await getDb();
  const row = await db.query.products.findFirst({
    where: includeDrafts ? eq(schema.products.slug, slug) : and(eq(schema.products.slug, slug), eq(schema.products.status, "published")),
    with: {
      brand: true,
      specs: true,
      evaluation: true,
      review: true,
      styles: { with: { style: true } },
      models: true,
      images: { orderBy: (i, { asc }) => [asc(i.sortOrder)] },
      offers: { with: { retailer: true } },
      hotspots: { orderBy: (h, { asc }) => [asc(h.sortOrder)] },
      annotations: { orderBy: (a, { asc }) => [asc(a.sortOrder)] },
      overlays: true,
    },
  });
  if (!row) return null;
  const rating = (await ratings([row.id])).get(row.id);
  const summary = mapSummary(row as unknown as SummaryRow, rating);
  const specs = row.specs;
  const ev = row.evaluation;
  const primary = row.models.find((m) => m.role === "primary");
  const model: Model3D | null = primary
    ? {
        id: primary.id,
        status: primary.status as ModelStatus,
        format: primary.format,
        url: primary.url,
        previewUrl: primary.previewUrl,
        version: primary.version,
        posterUrl: primary.posterUrl,
        thumbnailUrl: primary.thumbnailUrl,
        explodedUrl: primary.explodedUrl,
        supportsExplode: primary.supportsExplode,
        fileSizeBytes: primary.fileSizeBytes,
        provenance: {
          source: primary.source,
          licenseStatus: primary.licenseStatus as LicenseStatus,
          attribution: primary.attribution,
          creator: primary.creator,
          usageRestrictions: primary.usageRestrictions,
          approvalStatus: primary.approvalStatus as ApprovalStatus,
        },
        variants: row.models
          .filter((m) => m.role === "variant" && m.url)
          .map((m) => ({ id: m.id, kind: m.variantKind, label: m.label, url: m.url!, status: m.status as ModelStatus })),
      }
    : null;
  const review: EditorialReview | null = row.review
    ? {
        title: row.review.title,
        summary: row.review.summary,
        body: row.review.body,
        pros: row.review.pros,
        cons: row.review.cons,
        verdict: row.review.verdict,
        inspectionNotes: row.review.inspectionNotes,
        modelQualityNote: row.review.modelQualityNote,
        author: row.review.author,
        isSample: row.review.isSample,
        publishedAt: iso(row.review.publishedAt),
      }
    : null;
  return {
    ...summary,
    collection: row.collection,
    description: row.description,
    status: row.status,
    specs: {
      shape: summary.shape,
      weightMinG: specs?.weightMinG ?? null,
      weightMaxG: specs?.weightMaxG ?? null,
      balance: (specs?.balance ?? null) as Balance | null,
      balanceMm: specs?.balanceMm ?? null,
      hardness: (specs?.hardness ?? null) as Hardness | null,
      thicknessMm: specs?.thicknessMm ?? null,
      frameMaterial: specs?.frameMaterial ?? null,
      faceMaterial: specs?.faceMaterial ?? null,
      coreMaterial: specs?.coreMaterial ?? null,
      surfaceFinish: (specs?.surfaceFinish ?? null) as SurfaceFinish | null,
      verification: (specs?.verification ?? "unverified") as Verification,
      sourceNote: specs?.sourceNote ?? null,
      sourceUrl: specs?.sourceUrl ?? null,
    },
    evaluation: ev
      ? {
          power: ev.power,
          control: ev.control,
          maneuverability: ev.maneuverability,
          forgiveness: ev.forgiveness,
          sweetSpot: ev.sweetSpot,
          defense: ev.defense,
          attack: ev.attack,
          overall: overallScore(ev),
          bestFor: ev.bestFor,
          recommendedFor: ev.recommendedFor,
          notIdealFor: ev.notIdealFor,
          methodologyVersion: ev.methodologyVersion,
          isSample: ev.isSample,
        }
      : null,
    model,
    hotspots: row.hotspots.map(
      (h): Hotspot => ({
        id: h.id,
        key: h.key,
        label: h.label,
        body: h.body,
        u: h.u,
        v: h.v,
        w: h.w,
        view: h.view as CameraView,
        specKey: (h.specKey ?? null) as SpecKey | null,
        basis: h.basis as Basis,
      }),
    ),
    annotations: row.annotations.map(
      (a): Annotation => ({ id: a.id, view: a.view as CameraView, title: a.title, body: a.body, basis: a.basis as Basis }),
    ),
    overlays: row.overlays
      .filter((o) => o.enabled)
      .map((o): OverlayConfig => ({ kind: o.kind, basis: o.basis as Basis, note: o.note, params: o.params })),
    offers: visibleOffers(row as unknown as SummaryRow),
    review,
    roundup: (row.roundup ?? null) as ReviewRoundup | null,
    updatedAt: iso(row.updatedAt)!,
    images: row.images.map((i) => ({ url: i.url, alt: i.alt, kind: i.kind })),
  };
}

/** A published racket by slug (cached). */
export function getRacket(slug: string) {
  return unstable_cache(() => loadRacket(slug), ["racket", slug], { tags: [CATALOG_TAG, `racket:${slug}`], revalidate: 3600 })();
}

/** Admin preview: includes drafts, never cached. */
export function getRacketForPreview(slug: string) {
  return loadRacket(slug, true);
}

/** Several rackets for comparison, in the requested order. */
export async function getRacketsBySlugs(slugs: string[]): Promise<Racket[]> {
  const unique = [...new Set(slugs)].slice(0, 4);
  const rows = await Promise.all(unique.map((s) => getRacket(s)));
  return rows.filter((r): r is Racket => r !== null);
}

export async function listPublishedSlugs(): Promise<Array<{ slug: string; updatedAt: string }>> {
  const db = await getDb();
  const rows = await db
    .select({ slug: schema.products.slug, updatedAt: schema.products.updatedAt })
    .from(schema.products)
    .where(eq(schema.products.status, "published"));
  return rows.map((r) => ({ slug: r.slug, updatedAt: iso(r.updatedAt)! }));
}
