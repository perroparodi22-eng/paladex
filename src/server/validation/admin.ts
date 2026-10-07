/**
 * Server-side validation for every admin write. Nothing from the browser is
 * trusted: types, lengths, enums and URLs are all checked here.
 */
import { z } from "zod";
import {
  APPROVAL_STATUSES,
  BALANCES,
  BASES,
  CAMERA_VIEWS,
  HARDNESSES,
  LICENSE_STATUSES,
  MODEL_STATUSES,
  OVERLAY_KINDS,
  PLAYER_LEVELS,
  PLAYING_STYLES,
  PUBLISH_STATUSES,
  RACKET_SHAPES,
  SPEC_KEYS,
  STOCK_STATUSES,
  SURFACE_FINISHES,
  VERIFICATION_STATES,
} from "@/domain/types";
import { AFFILIATE_PLACEHOLDER, isSafeAssetUrl, isSafeHttpsUrl } from "@/lib/urls";

const assetHosts = () =>
  (process.env.ASSET_ORIGINS ?? "")
    .split(",")
    .map((o) => {
      try {
        return new URL(o.trim()).hostname;
      } catch {
        return "";
      }
    })
    .filter(Boolean);

const text = (max: number) => z.string().trim().max(max);
const optText = (max: number) =>
  z
    .string()
    .trim()
    .max(max)
    .nullable()
    .optional()
    .transform((v) => (v ? v : null));
const optInt = (min: number, max: number) =>
  z
    .union([z.number(), z.string(), z.null()])
    .optional()
    .transform((v) => (v === "" || v === null || v === undefined ? null : Number(v)))
    .refine((v) => v === null || (Number.isFinite(v) && v >= min && v <= max), { message: `Must be between ${min} and ${max}` });
const score = z.coerce.number().min(1).max(10);
const assetUrl = z
  .string()
  .trim()
  .max(1000)
  .nullable()
  .optional()
  .transform((v) => (v ? v : null))
  .refine((v) => v === null || isSafeAssetUrl(v, assetHosts()), {
    message: "Use a site path like /models/x.glb or an https URL on a host listed in ASSET_ORIGINS",
  });
const color = z.string().regex(/^#[0-9a-fA-F]{6}$/, "Use a hex colour like #1a2b3c");
const slug = z.string().trim().min(2).max(80).regex(/^[a-z0-9]+(-[a-z0-9]+)*$/, "Lowercase letters, numbers and dashes only");

export const racketInputSchema = z.object({
  id: z.number().int().positive().optional(),
  basics: z.object({
    brandId: z.coerce.number().int().positive(),
    slug,
    name: text(120).min(1),
    collection: optText(80),
    year: optInt(1990, 2100),
    shortDescription: text(300),
    description: text(5000),
    status: z.enum(PUBLISH_STATUSES),
    featured: z.boolean(),
    isNew: z.boolean(),
    levels: z.array(z.enum(PLAYER_LEVELS)).max(3),
    styles: z.array(z.enum(PLAYING_STYLES)).max(5),
    indicativePriceEur: optInt(1, 5000),
    dataStatus: z.enum(VERIFICATION_STATES),
  }),
  specs: z.object({
    shape: z.enum(RACKET_SHAPES),
    weightMinG: optInt(250, 450),
    weightMaxG: optInt(250, 450),
    balance: z.enum(BALANCES).nullable(),
    balanceMm: optInt(200, 320),
    hardness: z.enum(HARDNESSES).nullable(),
    thicknessMm: optInt(20, 40),
    frameMaterial: optText(160),
    faceMaterial: optText(160),
    coreMaterial: optText(160),
    surfaceFinish: z.enum(SURFACE_FINISHES).nullable(),
    verification: z.enum(VERIFICATION_STATES),
    sourceNote: optText(500),
    sourceUrl: z
      .string()
      .trim()
      .max(1000)
      .nullable()
      .optional()
      .transform((v) => (v ? v : null))
      .refine((v) => v === null || isSafeHttpsUrl(v), "Source must be an https URL"),
  }),
  evaluation: z.object({
    power: score,
    control: score,
    maneuverability: score,
    forgiveness: score,
    sweetSpot: score,
    defense: score,
    attack: score,
    bestFor: text(300),
    recommendedFor: text(500),
    notIdealFor: text(300),
    isSample: z.boolean(),
  }),
  visual: z.object({
    face: color,
    frame: color,
    accent: color,
    accent2: color,
    grip: color,
    pattern: z.enum(["sweep", "split", "chevron", "ring", "border", "blade"]),
    holes: z.enum(["hex", "rings"]),
    bridge: z.boolean(),
  }),
  model: z.object({
    status: z.enum(MODEL_STATUSES),
    url: assetUrl,
    previewUrl: assetUrl,
    posterUrl: assetUrl,
    thumbnailUrl: assetUrl,
    explodedUrl: assetUrl,
    version: text(40).min(1),
    supportsExplode: z.boolean(),
    source: optText(300),
    licenseStatus: z.enum(LICENSE_STATUSES),
    attribution: optText(300),
    creator: optText(160),
    usageRestrictions: optText(500),
    approvalStatus: z.enum(APPROVAL_STATUSES),
    notes: optText(1000),
  }),
  hotspots: z
    .array(
      z.object({
        key: slug,
        label: text(80).min(1),
        body: text(800),
        u: z.coerce.number().min(-0.5).max(1.5),
        v: z.coerce.number().min(-0.5).max(1.5),
        w: z.coerce.number().min(-0.5).max(1.5),
        view: z.enum(CAMERA_VIEWS),
        specKey: z.enum(SPEC_KEYS).nullable(),
        basis: z.enum(BASES),
      }),
    )
    .max(20),
  annotations: z.array(z.object({ view: z.enum(CAMERA_VIEWS), title: text(80).min(1), body: text(800), basis: z.enum(BASES) })).max(20),
  overlays: z
    .array(
      z.object({
        kind: z.enum(OVERLAY_KINDS),
        enabled: z.boolean(),
        basis: z.enum(BASES),
        note: optText(400),
        params: z.record(z.string().max(40), z.union([z.number(), z.string().max(80), z.boolean()])),
      }),
    )
    .max(10),
  images: z
    .array(
      z.object({
        url: z.string().trim().refine((v) => isSafeAssetUrl(v, assetHosts()), "Image URL must be a site path or an allowed https host"),
        alt: text(200).min(3),
        kind: z.enum(["front", "angle", "detail", "lifestyle"]),
        source: optText(300),
        licenseStatus: z.enum(LICENSE_STATUSES),
        attribution: optText(300),
        creator: optText(160),
        usageRestrictions: optText(500),
        approvalStatus: z.enum(APPROVAL_STATUSES),
      }),
    )
    .max(20),
  offers: z
    .array(
      z.object({
        id: z.number().int().positive().optional(),
        retailerId: z.coerce.number().int().positive(),
        productUrl: z
          .string()
          .trim()
          .max(1000)
          .nullable()
          .optional()
          .transform((v) => (v ? v : null))
          .refine((v) => v === null || isSafeHttpsUrl(v), "Product URL must be https"),
        affiliateUrl: z
          .string()
          .trim()
          .max(2000)
          .nullable()
          .optional()
          .transform((v) => (v ? v : null))
          .refine((v) => v === null || v === AFFILIATE_PLACEHOLDER || isSafeHttpsUrl(v), `Affiliate URL must be https or ${AFFILIATE_PLACEHOLDER}`),
        priceEur: z.coerce.number().min(0.5).max(5000),
        currency: z.string().trim().length(3).toUpperCase(),
        stockStatus: z.enum(STOCK_STATUSES),
        available: z.boolean(),
        shippingInfo: optText(200),
        isDemo: z.boolean(),
        active: z.boolean(),
      }),
    )
    .max(30),
  review: z
    .object({
      title: text(160).min(1),
      summary: text(600),
      body: text(6000),
      pros: z.array(text(200)).max(10),
      cons: z.array(text(200)).max(10),
      verdict: text(400),
      inspectionNotes: optText(1500),
      modelQualityNote: optText(500),
      isSample: z.boolean(),
    })
    .nullable(),
});

export type RacketInput = z.infer<typeof racketInputSchema>;
export type RacketInputRaw = z.input<typeof racketInputSchema>;

export const brandInputSchema = z.object({
  id: z.coerce.number().int().positive().optional(),
  slug,
  name: text(80).min(1),
  country: optText(80),
  description: text(1500),
  websiteUrl: z
    .string()
    .trim()
    .max(500)
    .nullable()
    .optional()
    .transform((v) => (v ? v : null))
    .refine((v) => v === null || isSafeHttpsUrl(v), "Website must be https"),
  logoUrl: assetUrl,
});

export const retailerInputSchema = z.object({
  id: z.coerce.number().int().positive().optional(),
  slug,
  name: text(80).min(1),
  websiteUrl: z.string().trim().refine(isSafeHttpsUrl, "Website must be https"),
  logoUrl: assetUrl,
  country: text(40).min(2),
  currency: z.string().trim().length(3).toUpperCase(),
  shippingInfo: optText(200),
  affiliateNetwork: optText(120),
  allowedDomains: z
    .string()
    .transform((s) =>
      s
        .split(/[\s,]+/)
        .map((d) => d.trim().toLowerCase())
        .filter(Boolean),
    )
    .pipe(z.array(z.string().regex(/^(\*\.)?[a-z0-9-]+(\.[a-z0-9-]+)+$/, "Use bare domains like shop.example.com")).max(10)),
  isDemo: z.boolean(),
  active: z.boolean(),
});

export function firstError(e: z.ZodError): string {
  const issue = e.issues[0];
  return issue ? `${issue.path.join(" › ")}: ${issue.message}` : "Invalid input";
}
