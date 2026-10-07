/**
 * Writes src/data/designs/catalogue.generated.ts: a PhotoDesign for every
 * catalogue racket that has a traced front photo (assets/reference/<slug>/front.png
 * + src/data/designs/<slug>.trace.json), plus the poster colours for the seed.
 *
 * Art direction that was measured by eye for the Metalbone is derived here:
 * frame and grip colours are sampled from the photo, the face ends 4 mm above
 * the throat opening (as on the Metalbone), and the sweet spot sits by shape.
 *
 *   npx tsx scripts/build-catalogue-designs.ts
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import sharp from "sharp";
import { brandCatalogue, type CatalogueRacket } from "../src/data/seed/brand-catalogue";
import { proRackets } from "../src/data/seed/pro-players";
import type { RacketTrace } from "../src/data/designs/types";

type RGB = [number, number, number];
const hex = ([r, g, b]: RGB) => `#${[r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("")}`;
const lum = ([r, g, b]: RGB) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
const shade = ([r, g, b]: RGB, k: number): RGB => [r * k, g * k, b * k];
const dist = (a: RGB, b: RGB) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

function median(colors: RGB[]): RGB {
  if (!colors.length) return [30, 32, 36];
  const m = (c: 0 | 1 | 2) => colors.map((x) => x[c]).sort((a, b) => a - b)[colors.length >> 1];
  return [m(0), m(1), m(2)];
}

/** Most common colours (4-bit quantised), most frequent first. */
function dominant(colors: RGB[], count: number): RGB[] {
  const bins = new Map<number, { n: number; sum: RGB }>();
  for (const c of colors) {
    const key = ((c[0] >> 4) << 8) | ((c[1] >> 4) << 4) | (c[2] >> 4);
    const b = bins.get(key) ?? { n: 0, sum: [0, 0, 0] };
    b.n++;
    b.sum = [b.sum[0] + c[0], b.sum[1] + c[1], b.sum[2] + c[2]];
    bins.set(key, b);
  }
  const ranked = [...bins.values()].sort((a, b) => b.n - a.n).map((b) => [b.sum[0] / b.n, b.sum[1] / b.n, b.sum[2] / b.n] as RGB);
  const picked: RGB[] = [];
  for (const c of ranked) {
    if (picked.every((p) => dist(p, c) > 70)) picked.push(c);
    if (picked.length === count) break;
  }
  while (picked.length < count) picked.push(picked[picked.length - 1] ?? [40, 40, 40]);
  return picked;
}

const ident = (slug: string) => "t_" + slug.replace(/[^a-z0-9]/g, "_");

/**
 * Details the photo alone can't give, from the catalogue text. The Metalbone HRD+ lists an
 * adjustable weight system; it shares the Metalbone 3.4 frame, so the screws sit where they do there.
 */
const OVERRIDES: Record<string, string> = {
  "adidas-metalbone-hrd-plus-2026": `screws: { y: [0.2445, 0.2585], ring: "#9aa0a6" },`,
};

function sweetSpotFor(r: CatalogueRacket): number {
  const s = (r.shape ?? "").toLowerCase();
  if (s.includes("round")) return 0.62;
  if (s.includes("diamond") || s.includes("geometric")) return 0.72;
  if (s.includes("hybrid")) return 0.68;
  return 0.67; // teardrop / drop
}

async function main() {
  const designs: string[] = [];
  const imports: string[] = [];
  const visuals: Record<string, unknown> = {};
  for (const r of [...brandCatalogue, ...proRackets]) {
    const front = `assets/reference/${r.slug}/front.png`;
    const tracePath = `src/data/designs/${r.slug}.trace.json`;
    if (!existsSync(front) || !existsSync(tracePath)) continue;
    const t = JSON.parse(readFileSync(tracePath, "utf8")) as RacketTrace;

    let img = sharp(front).ensureAlpha();
    if (Math.abs(t.rotateDeg) > 1e-3) img = img.rotate(t.rotateDeg, { background: { r: 0, g: 0, b: 0, alpha: 0 } });
    const { data, info } = await img.raw().toBuffer({ resolveWithObject: true });
    const W = info.width;
    const at = (xm: number, ym: number): RGB | null => {
      const px = Math.round(t.axisX + xm / t.metresPerPixel);
      const py = Math.round(t.buttY - ym / t.metresPerPixel);
      if (px < 0 || py < 0 || px >= W || py >= info.height) return null;
      const i = (py * W + px) * 4;
      return data[i + 3] > 200 ? [data[i], data[i + 1], data[i + 2]] : null;
    };

    // Frame: just inside the outline, around the head.
    const headTop = Math.max(...t.frameOuter.map((p) => p[1]));
    const headCy = (headTop + t.neckY + 0.1) / 2;
    const frameSamples: RGB[] = [];
    for (const [x, y] of t.frameOuter) {
      if (y < t.neckY + 0.09) continue;
      const len = Math.hypot(x, y - headCy) || 1;
      const c = at(x - (x / len) * 0.003, y - ((y - headCy) / len) * 0.003);
      if (c) frameSamples.push(c);
    }
    const frame = median(frameSamples);

    // Grip: along the axis between the butt and the neck.
    const gripSamples: RGB[] = [];
    for (let y = 0.015; y < t.neckY - 0.02; y += 0.002) for (const x of [-0.006, 0, 0.006]) {
      const c = at(x, y);
      if (c) gripSamples.push(c);
    }
    const grip = median(gripSamples);

    // Face: dominant colours inside the head.
    const faceSamples: RGB[] = [];
    for (let y = t.neckY + 0.11; y < headTop - 0.02; y += 0.004) for (let x = -0.12; x <= 0.12; x += 0.004) {
      const c = at(x, y);
      if (c) faceSamples.push(c);
    }
    const [face, accent, accent2] = dominant(faceSamples, 3);

    const throatTop = t.throat.length ? Math.max(...t.throat.map((p) => p[1])) : t.neckY + 0.06;
    const octagonal = (r.shape ?? "").toLowerCase().includes("octagonal");
    imports.push(`import ${ident(r.slug)} from "./${r.slug}.trace.json";`);
    designs.push(`  "${r.slug}": {
    slug: "${r.slug}",
    frontImage: "${front}",
    trace: ${ident(r.slug)} as unknown as RacketTrace,
    thicknessMm: ${r.profileMm ?? 38},
    faceThicknessMm: ${(r.profileMm ?? 38) - 4},
    faceBottom: { centerY: ${(throatTop + 0.004).toFixed(4)}, slope: 0.24 },
    frameBevelSegments: ${octagonal ? 1 : 3},
    colors: { frame: "${hex(frame)}", faceEdge: "${hex(shade(frame, 0.8))}", core: "#26292e", grip: "${hex(grip)}", gripDots: "${lum(grip) < 110 ? "#c9ced3" : "#2a2c30"}", collar: "${hex(shade(grip, 0.75))}" },
    frameRoughness: 0.3,
    sweetSpotV: ${sweetSpotFor(r)},
    mirrorBack: true,${OVERRIDES[r.slug] ? `
    ${OVERRIDES[r.slug]}` : ""}
  },`);
    visuals[r.slug] = { face: hex(face), frame: hex(frame), accent: hex(accent), accent2: hex(accent2), grip: hex(grip) };
    console.log(`${r.slug.padEnd(52)} frame ${hex(frame)} grip ${hex(grip)} face ${hex(face)} accent ${hex(accent)}`);
  }

  const out = `/**
 * GENERATED by scripts/build-catalogue-designs.ts from the owner's brand
 * catalogue photos (assets/reference/<slug>/front.png). Platform-created
 * designs: geometry traced from the front photo, colours sampled from it.
 * Re-run the script after replacing a photo; edit values here by hand only if
 * you also stop regenerating.
 */
import type { PhotoDesign, RacketTrace } from "./types";
${imports.join("\n")}

export const catalogueDesigns: Record<string, PhotoDesign> = {
${designs.join("\n")}
};

/** Poster colours sampled from the photos (used where a drawing stands in for the photo). */
export const catalogueVisuals: Record<string, { face: string; frame: string; accent: string; accent2: string; grip: string }> = ${JSON.stringify(visuals, null, 2)};
`;
  writeFileSync("src/data/designs/catalogue.generated.ts", out);
  console.log(`wrote ${designs.length} designs`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
