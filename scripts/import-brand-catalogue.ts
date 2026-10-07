/**
 * Downloads the product photos listed in src/data/seed/brand-catalogue.ts into
 * assets/reference/<slug>/ as a.<ext>, b.<ext>, … (catalogue order A, B, C, D).
 * Existing files are kept, so the script can be re-run safely.
 *
 *   npx tsx scripts/import-brand-catalogue.ts [--only <slug>]
 */
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { brandCatalogue } from "../src/data/seed/brand-catalogue";
import { proRackets } from "../src/data/seed/pro-players";

const only = process.argv.includes("--only") ? process.argv[process.argv.indexOf("--only") + 1] : null;
const letters = "abcdefgh";

function extOf(url: string, contentType: string | null): string {
  if (contentType?.includes("png")) return "png";
  if (contentType?.includes("webp")) return "webp";
  if (contentType?.includes("jpeg") || contentType?.includes("jpg")) return "jpg";
  if (contentType?.includes("avif")) return "avif";
  return path.extname(new URL(url).pathname).slice(1) || "img";
}

async function main() {
  let ok = 0;
  let failed = 0;
  for (const r of [...brandCatalogue, ...proRackets]) {
    if (only && r.slug !== only) continue;
    const dir = path.join("assets", "reference", r.slug);
    mkdirSync(dir, { recursive: true });
    for (const [i, url] of r.images.entries()) {
      const stem = path.join(dir, letters[i]);
      if (["png", "jpg", "webp", "avif"].some((e) => existsSync(`${stem}.${e}`))) continue;
      try {
        const res = await fetch(url, {
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
            Accept: "image/png,image/webp,image/jpeg,image/*",
          },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const buf = Buffer.from(await res.arrayBuffer());
        const file = `${stem}.${extOf(url, res.headers.get("content-type"))}`;
        writeFileSync(file, buf);
        ok++;
        console.log(`${r.id} ${letters[i].toUpperCase()}  ${(buf.length / 1024).toFixed(0)} KB  ${file}`);
      } catch (e) {
        failed++;
        console.log(`${r.id} ${letters[i].toUpperCase()}  FAILED (${(e as Error).message})  ${url}`);
      }
    }
  }
  console.log(`downloaded ${ok}, failed ${failed}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
