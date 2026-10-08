"use server";
/**
 * Admin server actions. Every action re-checks the session (requireAdmin),
 * validates its input with zod on the server, and refreshes the public
 * catalog cache after a write so the site shows the change immediately.
 */
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath, updateTag } from "next/cache";
import { z } from "zod";
import { requireAdmin } from "@/server/auth/guard";
import { adminConfigured, createSessionToken, SESSION_COOKIE, sessionCookieOptions } from "@/server/auth/session";
import { verifyPassword } from "@/server/auth/password";
import { rateLimit } from "@/server/rate-limit";
import { CATALOG_TAG } from "@/server/repositories/rackets";
import {
  adminDeleteBrand,
  adminDeleteRacket,
  adminDeleteRetailer,
  adminModelBbox,
  adminSaveBrand,
  adminSaveRacket,
  adminSaveRetailer,
  derivedAnnotations,
  SaveError,
} from "@/server/repositories/admin";
import { brandInputSchema, firstError, racketInputSchema, retailerInputSchema } from "@/server/validation/admin";
import { MODEL_STATUSES } from "@/domain/types";

export type FormState = { ok: boolean; message: string; at: number } | null;

const fail = (message: string): FormState => ({ ok: false, message, at: Date.now() });
const done = (message: string): FormState => ({ ok: true, message, at: Date.now() });

/** Expire cached catalog reads and every rendered page that shows catalog data. */
function refreshCatalog() {
  updateTag(CATALOG_TAG);
  revalidatePath("/", "layout");
}

function saveErrorMessage(e: unknown): string {
  if (e instanceof SaveError) return e.message;
  console.error("[admin] write failed", e);
  return "Saving failed. Nothing was changed. Check the server log for details.";
}

/* ------------------------------------------------------------------ auth */

async function requestKey(): Promise<string> {
  const h = await headers();
  const fwd = h.get("x-forwarded-for");
  return (fwd ? fwd.split(",").map((s) => s.trim()).filter(Boolean).pop() : h.get("x-real-ip")) || "local";
}

export async function login(_prev: FormState, formData: FormData): Promise<FormState> {
  if (!adminConfigured()) {
    return fail("The admin is not configured. Set ADMIN_PASSWORD_HASH and ADMIN_SESSION_SECRET (run npm run setup locally).");
  }
  const key = await requestKey();
  // 5 attempts per 15 minutes per address, 30 overall: slows down guessing.
  if (!rateLimit(`login:${key}`, 5, 15 * 60_000) || !rateLimit("login:all", 30, 15 * 60_000)) {
    return fail("Too many attempts. Wait 15 minutes and try again.");
  }
  const password = formData.get("password");
  if (typeof password !== "string" || password.length < 1 || password.length > 256) return fail("Enter the admin password.");
  const ok = await verifyPassword(password, process.env.ADMIN_PASSWORD_HASH!.trim());
  if (!ok) return fail("That password is not correct.");
  const token = createSessionToken();
  if (!token) return fail("ADMIN_SESSION_SECRET must be at least 32 characters.");
  const jar = await cookies();
  jar.set(SESSION_COOKIE, token, sessionCookieOptions());
  redirect("/admin");
}

export async function logout() {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  redirect("/admin/login");
}

/* --------------------------------------------------------------- rackets */

export async function saveRacket(_prev: FormState, formData: FormData): Promise<FormState> {
  await requireAdmin();
  const raw = formData.get("payload");
  if (typeof raw !== "string" || raw.length > 400_000) return fail("The form data is missing or too large.");
  let json: unknown;
  try {
    json = JSON.parse(raw);
  } catch {
    return fail("The form data could not be read.");
  }
  const parsed = racketInputSchema.safeParse(json);
  if (!parsed.success) return fail(firstError(parsed.error));

  let result: Awaited<ReturnType<typeof adminSaveRacket>>;
  try {
    result = await adminSaveRacket(parsed.data);
  } catch (e) {
    return fail(saveErrorMessage(e));
  }
  refreshCatalog();
  if (!parsed.data.id) redirect(`/admin/rackets/${result.id}?created=1`);
  return done(parsed.data.basics.status === "published" ? "Saved. The public page is updated." : "Saved as a draft. It is not public.");
}

export async function deleteRacket(formData: FormData) {
  await requireAdmin();
  const id = z.coerce.number().int().positive().safeParse(formData.get("id"));
  if (!id.success) redirect("/admin/rackets");
  const slug = await adminDeleteRacket(id.data);
  refreshCatalog();
  redirect(`/admin/rackets?deleted=${encodeURIComponent(slug ?? "")}`);
}

const deriveSchema = z.object({
  id: z.number().int().positive().optional(),
  slug: z.string().max(80),
  sweetSpot: z.coerce.number().min(1).max(10),
  modelStatus: z.enum(MODEL_STATUSES),
  modelUrl: z.string().max(1000).nullable(),
  specs: racketInputSchema.shape.specs,
});

/**
 * Regenerate hotspots, 3D notes and overlays from the current (unsaved) specs.
 * Returns data only; nothing is written until the form is saved.
 */
export async function deriveAnnotations(input: unknown) {
  await requireAdmin();
  const parsed = deriveSchema.safeParse(input);
  if (!parsed.success) return { ok: false as const, message: firstError(parsed.error) };
  const d = parsed.data;
  const stored = d.id ? await adminModelBbox(d.id) : null;
  // Stored bounds only apply while the model file is unchanged.
  const bbox = stored && stored.url === d.modelUrl ? stored.bbox : null;
  return {
    ok: true as const,
    ...derivedAnnotations({ slug: d.slug, specs: d.specs, sweetSpotScore: d.sweetSpot, modelStatus: d.modelStatus, bbox }),
  };
}

/* ---------------------------------------------------------------- brands */

const bool = (v: FormDataEntryValue | null) => v === "on" || v === "true";

export async function saveBrand(_prev: FormState, formData: FormData): Promise<FormState> {
  await requireAdmin();
  const parsed = brandInputSchema.safeParse({
    id: formData.get("id") || undefined,
    slug: formData.get("slug"),
    name: formData.get("name"),
    country: formData.get("country"),
    description: formData.get("description") ?? "",
    websiteUrl: formData.get("websiteUrl"),
    logoUrl: formData.get("logoUrl"),
  });
  if (!parsed.success) return fail(firstError(parsed.error));
  try {
    await adminSaveBrand(parsed.data);
  } catch (e) {
    return fail(saveErrorMessage(e));
  }
  refreshCatalog();
  return done(parsed.data.id ? `Saved ${parsed.data.name}.` : `Added ${parsed.data.name}.`);
}

export async function deleteBrand(_prev: FormState, formData: FormData): Promise<FormState> {
  await requireAdmin();
  const id = z.coerce.number().int().positive().safeParse(formData.get("id"));
  if (!id.success) return fail("Unknown brand.");
  try {
    await adminDeleteBrand(id.data);
  } catch (e) {
    return fail(saveErrorMessage(e));
  }
  refreshCatalog();
  return done("Brand deleted.");
}

/* ------------------------------------------------------------- retailers */

export async function saveRetailer(_prev: FormState, formData: FormData): Promise<FormState> {
  await requireAdmin();
  const parsed = retailerInputSchema.safeParse({
    id: formData.get("id") || undefined,
    slug: formData.get("slug"),
    name: formData.get("name"),
    websiteUrl: formData.get("websiteUrl"),
    logoUrl: formData.get("logoUrl"),
    country: formData.get("country"),
    currency: formData.get("currency"),
    shippingInfo: formData.get("shippingInfo"),
    affiliateNetwork: formData.get("affiliateNetwork"),
    allowedDomains: formData.get("allowedDomains") ?? "",
    isDemo: bool(formData.get("isDemo")),
    active: bool(formData.get("active")),
  });
  if (!parsed.success) return fail(firstError(parsed.error));
  try {
    await adminSaveRetailer(parsed.data);
  } catch (e) {
    return fail(saveErrorMessage(e));
  }
  refreshCatalog();
  return done(parsed.data.id ? `Saved ${parsed.data.name}.` : `Added ${parsed.data.name}.`);
}

export async function deleteRetailer(_prev: FormState, formData: FormData): Promise<FormState> {
  await requireAdmin();
  const id = z.coerce.number().int().positive().safeParse(formData.get("id"));
  if (!id.success) return fail("Unknown retailer.");
  try {
    await adminDeleteRetailer(id.data);
  } catch (e) {
    return fail(saveErrorMessage(e));
  }
  refreshCatalog();
  return done("Retailer and its offers deleted.");
}
