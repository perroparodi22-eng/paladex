/**
 * Turns the brand logos in assets/brand-logos/ (official files; see the source
 * note in src/data/seed/brands.ts) into white silhouettes for the dark brand
 * tiles: public/images/brands/<slug>.png. Logos without transparency (black on
 * white) get their alpha from the ink darkness.
 *
 *   npx tsx scripts/build-brand-logos.ts
 */
import { readdirSync } from "node:fs";
import path from "node:path";
import sharp from "sharp";

async function main() {
  for (const file of readdirSync("assets/brand-logos")) {
    const slug = path.parse(file).name;
    const { data, info } = await sharp(`assets/brand-logos/${file}`, { density: 400 })
      .resize({ width: 520, height: 220, fit: "inside", withoutEnlargement: false })
      .ensureAlpha()
      .raw()
      .toBuffer({ resolveWithObject: true });
    let transparent = 0;
    for (let i = 3; i < data.length; i += 4) if (data[i] < 128) transparent++;
    const opaqueImage = transparent < (data.length / 4) * 0.02;
    const lumAt = (i: number) => 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
    let darkest = 255;
    if (opaqueImage) for (let i = 0; i < data.length; i += 4) darkest = Math.min(darkest, lumAt(i));
    for (let i = 0; i < data.length; i += 4) {
      // Ink coverage, normalised so the logo's own ink colour (often grey) becomes full white.
      if (opaqueImage) data[i + 3] = Math.max(0, Math.min(255, Math.round(((255 - lumAt(i)) / Math.max(1, 255 - darkest)) * 255)));
      data[i] = data[i + 1] = data[i + 2] = 255;
    }
    await sharp(data, { raw: info }).trim({ threshold: 1 }).png({ compressionLevel: 9 }).toFile(`public/images/brands/${slug}.png`);
    console.log(`${slug}.png ${info.width}x${info.height}${opaqueImage ? " (alpha from ink)" : ""}`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
