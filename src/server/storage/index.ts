/**
 * Asset storage for admin uploads (3D models and images).
 *
 * Every upload is checked before it is stored:
 *  - extension allow-list and size limit per kind
 *  - magic bytes (GLB header "glTF", PNG/JPEG/WebP/AVIF signatures)
 *  - .gltf must be self-contained JSON (no external file references)
 *  - a random, sanitised file name (the original name is never used as a path)
 *
 * ASSET_STORAGE=local  -> data/uploads/* served by /uploads/[...path] (development, or a server with a persistent disk)
 * ASSET_STORAGE=s3     -> any S3-compatible bucket (Cloudflare R2, AWS S3…) via aws4fetch
 */
import "server-only";
import { randomBytes } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { AwsClient } from "aws4fetch";

export type AssetKind = "model" | "image";

/** Where local uploads live (outside public/, served by src/app/uploads/[...path]/route.ts). */
export const LOCAL_UPLOAD_DIR = join(process.cwd(), "data", "uploads");
export const UPLOAD_NAME = /^[a-z0-9-]{1,80}\.(glb|gltf|png|jpg|jpeg|webp|avif)$/;

const LIMITS: Record<AssetKind, { maxBytes: number; ext: string[] }> = {
  model: { maxBytes: 25 * 1024 * 1024, ext: ["glb", "gltf"] },
  image: { maxBytes: 8 * 1024 * 1024, ext: ["png", "jpg", "jpeg", "webp", "avif"] },
};

export const MIME: Record<string, string> = {
  glb: "model/gltf-binary",
  gltf: "model/gltf+json",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  webp: "image/webp",
  avif: "image/avif",
};

export class UploadError extends Error {}

function sniff(ext: string, bytes: Uint8Array): boolean {
  const b = (i: number) => bytes[i];
  const ascii = (from: number, len: number) => String.fromCharCode(...bytes.slice(from, from + len));
  switch (ext) {
    case "glb":
      return ascii(0, 4) === "glTF" && (b(4) === 2 || b(4) === 1);
    case "gltf": {
      try {
        const json = JSON.parse(new TextDecoder().decode(bytes));
        if (json?.asset?.version !== "2.0") return false;
        const external = [...(json.buffers ?? []), ...(json.images ?? [])].some((x: { uri?: string }) => x?.uri && !x.uri.startsWith("data:"));
        if (external) throw new UploadError("This .gltf references external files. Upload a self-contained .glb instead.");
        return true;
      } catch (e) {
        if (e instanceof UploadError) throw e;
        return false;
      }
    }
    case "png":
      return b(0) === 0x89 && ascii(1, 3) === "PNG";
    case "jpg":
    case "jpeg":
      return b(0) === 0xff && b(1) === 0xd8 && b(2) === 0xff;
    case "webp":
      return ascii(0, 4) === "RIFF" && ascii(8, 4) === "WEBP";
    case "avif":
      return ascii(4, 4) === "ftyp" && /avi[fs]/.test(ascii(8, 4));
    default:
      return false;
  }
}

export async function storeUpload(file: File, kind: AssetKind, hint: string): Promise<{ url: string; bytes: number }> {
  const limits = LIMITS[kind];
  const ext = (file.name.split(".").pop() ?? "").toLowerCase();
  if (!limits.ext.includes(ext)) throw new UploadError(`Only ${limits.ext.map((e) => `.${e}`).join(", ")} files are accepted.`);
  if (file.size === 0) throw new UploadError("The file is empty.");
  if (file.size > limits.maxBytes) throw new UploadError(`The file is larger than ${Math.round(limits.maxBytes / 1024 / 1024)} MB.`);
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (!sniff(ext, bytes)) throw new UploadError("The file content doesn't match its extension.");

  const safeHint = hint.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || kind;
  const name = `${safeHint}-${randomBytes(6).toString("hex")}.${ext}`;
  const folder = kind === "model" ? "models" : "images";

  if ((process.env.ASSET_STORAGE ?? "local") === "s3") {
    const { S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_PUBLIC_BASE_URL, S3_REGION } = process.env;
    if (!S3_ENDPOINT || !S3_BUCKET || !S3_ACCESS_KEY_ID || !S3_SECRET_ACCESS_KEY || !S3_PUBLIC_BASE_URL) {
      throw new UploadError("S3 storage is selected but not fully configured (see .env.example).");
    }
    const client = new AwsClient({ accessKeyId: S3_ACCESS_KEY_ID, secretAccessKey: S3_SECRET_ACCESS_KEY, region: S3_REGION || "auto", service: "s3" });
    const key = `uploads/${folder}/${name}`;
    const res = await client.fetch(`${S3_ENDPOINT.replace(/\/+$/, "")}/${S3_BUCKET}/${key}`, {
      method: "PUT",
      body: bytes,
      headers: { "Content-Type": MIME[ext], "Cache-Control": "public, max-age=31536000, immutable" },
    });
    if (!res.ok) throw new UploadError(`Upload to storage failed (${res.status}).`);
    return { url: `${S3_PUBLIC_BASE_URL.replace(/\/+$/, "")}/${key}`, bytes: file.size };
  }

  if (process.env.NODE_ENV === "production" && process.env.ALLOW_LOCAL_UPLOADS !== "true") {
    throw new UploadError("Local uploads are disabled in production. Configure ASSET_STORAGE=s3, or set ALLOW_LOCAL_UPLOADS=true on a server with a persistent disk.");
  }
  const dir = join(LOCAL_UPLOAD_DIR, folder);
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, name), bytes);
  return { url: `/uploads/${folder}/${name}`, bytes: file.size };
}
