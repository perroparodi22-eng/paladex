/**
 * Serves admin uploads stored on the local disk (ASSET_STORAGE=local).
 * Only files written by storeUpload can match: a known folder and a random,
 * sanitised file name with an allow-listed extension. Names are random and
 * never reused, so responses are cached as immutable.
 */
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { LOCAL_UPLOAD_DIR, MIME, UPLOAD_NAME } from "@/server/storage";

export const runtime = "nodejs";

export async function GET(_req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  if (path.length !== 2) return new Response("Not found", { status: 404 });
  const [folder, name] = path;
  if ((folder !== "models" && folder !== "images") || !UPLOAD_NAME.test(name)) return new Response("Not found", { status: 404 });
  try {
    const bytes = await readFile(join(LOCAL_UPLOAD_DIR, folder, name));
    const ext = name.split(".").pop()!;
    return new Response(new Uint8Array(bytes), {
      headers: {
        "Content-Type": MIME[ext] ?? "application/octet-stream",
        "Content-Length": String(bytes.byteLength),
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
      },
    });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}
