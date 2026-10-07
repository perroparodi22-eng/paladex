/**
 * Admin asset upload (GLB/GLTF models and images).
 *
 * A route handler rather than a server action so the session and the declared
 * size are checked before the body is read, and so large models are not
 * subject to the server-action body limit. Files are validated again in
 * storeUpload (extension, size, magic bytes, self-contained glTF).
 *
 * Hosting note: serverless platforms cap request bodies (Vercel: 4.5 MB). For
 * bigger models in production, upload them to the bucket directly and paste
 * the URL into the racket form (its host must be listed in ASSET_ORIGINS).
 */
import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, verifySessionToken } from "@/server/auth/session";
import { storeUpload, UploadError } from "@/server/storage";
import { clientKey, rateLimit } from "@/server/rate-limit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BODY = 26 * 1024 * 1024;

function sameOrigin(req: NextRequest): boolean {
  const origin = req.headers.get("origin");
  if (!origin) return false;
  try {
    const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host");
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export async function POST(req: NextRequest) {
  if (!verifySessionToken(req.cookies.get(SESSION_COOKIE)?.value)) {
    return NextResponse.json({ error: "Your admin session has expired. Sign in again." }, { status: 401 });
  }
  if (!sameOrigin(req)) return NextResponse.json({ error: "Cross-site upload refused." }, { status: 403 });
  if (!rateLimit(`upload:${clientKey(req)}`, 30, 10 * 60_000)) {
    return NextResponse.json({ error: "Too many uploads. Wait a few minutes." }, { status: 429 });
  }
  const declared = Number(req.headers.get("content-length") ?? "0");
  if (!declared || declared > MAX_BODY) {
    return NextResponse.json({ error: "The upload is empty or larger than 25 MB." }, { status: 413 });
  }

  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return NextResponse.json({ error: "The upload could not be read." }, { status: 400 });
  }
  const file = form.get("file");
  const kind = form.get("kind");
  const hint = form.get("hint");
  if (!(file instanceof File)) return NextResponse.json({ error: "Choose a file to upload." }, { status: 400 });
  if (kind !== "model" && kind !== "image") return NextResponse.json({ error: "Unknown upload type." }, { status: 400 });

  try {
    const stored = await storeUpload(file, kind, typeof hint === "string" ? hint : kind);
    return NextResponse.json(stored, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (e) {
    if (e instanceof UploadError) return NextResponse.json({ error: e.message }, { status: 422 });
    console.error("[admin] upload failed", e);
    return NextResponse.json({ error: "The upload failed on the server." }, { status: 500 });
  }
}
