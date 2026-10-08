/**
 * Turns a straight-on product photo into the transparent front image the
 * tracer needs (scripts/trace-racket-photo.ts): removes a plain studio
 * background, opens the through-holes and the throat, and crops to the racket.
 * Photos that already have a transparent background are just cropped.
 *
 *   npx tsx scripts/cutout-racket-photo.ts --in assets/reference/<slug>/a.webp --out assets/reference/<slug>/front.png
 *
 * Options:
 *   --tolerance 16   colour distance that still counts as background
 *   --shadow         also remove a soft grey cast shadow touching the background
 *   --close <px>     fill notches up to this size in the outer outline (pale frames on pale backgrounds)
 *
 * Holes count only when they are background-coloured, enclosed by the racket
 * and roughly round (or, for the throat, sit below the face), so light prints
 * on the face are kept.
 */
import sharp from "sharp";
import { borderConnected, label, morph } from "./lib/raster";

function arg(name: string, fallback?: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : fallback;
}

async function main() {
  const input = arg("in");
  const output = arg("out");
  if (!input || !output) {
    console.error("usage: cutout-racket-photo --in <photo> --out <front.png>");
    process.exit(1);
  }
  const tolerance = Number(arg("tolerance", "16"));
  const shadow = process.argv.includes("--shadow");

  const { data, info } = await sharp(input).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const W = info.width;
  const H = info.height;
  const N = W * H;
  const alpha = new Uint8Array(N);
  let transparentAlready = 0;
  for (let i = 0; i < N; i++) if (data[i * 4 + 3] < 128) transparentAlready++;

  if (transparentAlready > N * 0.05) {
    // Already cut out by the brand: keep its alpha.
    for (let i = 0; i < N; i++) alpha[i] = data[i * 4 + 3];
  } else {
    // Background colour: median of the border pixels.
    const border: number[][] = [];
    for (let x = 0; x < W; x += 2) border.push([x, 0], [x, H - 1]);
    for (let y = 0; y < H; y += 2) border.push([0, y], [W - 1, y]);
    const ch = (c: number) => border.map(([x, y]) => data[(y * W + x) * 4 + c]).sort((a, b) => a - b)[border.length >> 1];
    const bg = [ch(0), ch(1), ch(2)];
    const bgL = (bg[0] + bg[1] + bg[2]) / 3;
    const dist = new Float32Array(N);
    const bgLike = new Uint8Array(N);
    for (let i = 0; i < N; i++) {
      const r = data[i * 4];
      const g = data[i * 4 + 1];
      const b = data[i * 4 + 2];
      dist[i] = Math.hypot(r - bg[0], g - bg[1], b - bg[2]);
      let isBg = dist[i] < tolerance;
      if (!isBg && shadow) {
        // Soft cast shadow: neutral grey, a bit darker than the background.
        const L = (r + g + b) / 3;
        const sat = Math.max(r, g, b) - Math.min(r, g, b);
        isBg = sat < 14 && L > bgL - 75 && L < bgL - 3; // never brighter than the background (keeps white grips)
      }
      bgLike[i] = isBg ? 1 : 0;
    }
    const outside = borderConnected(bgLike, W, H, 1);

    // Racket bounding box (everything not connected to the border).
    let top = H;
    let bottom = 0;
    for (let i = 0; i < N; i++) {
      if (outside[i]) continue;
      const y = (i / W) | 0;
      top = Math.min(top, y);
      bottom = Math.max(bottom, y);
    }
    const len = bottom - top + 1;

    // Enclosed background-coloured regions: through-holes and the throat opening.
    const enclosed = new Uint8Array(N);
    for (let i = 0; i < N; i++) enclosed[i] = bgLike[i] && !outside[i] ? 1 : 0;
    const { labels, sizes } = label(enclosed, W, H, 1);
    const boxes = sizes.map(() => ({ x0: W, y0: H, x1: 0, y1: 0 }));
    for (let i = 0; i < N; i++) {
      const l = labels[i];
      if (!l) continue;
      const x = i % W;
      const y = (i / W) | 0;
      const b = boxes[l];
      if (x < b.x0) b.x0 = x;
      if (x > b.x1) b.x1 = x;
      if (y < b.y0) b.y0 = y;
      if (y > b.y1) b.y1 = y;
    }
    const isHole = sizes.map((size, l) => {
      if (l === 0 || size < 12) return false;
      const b = boxes[l];
      const w = b.x1 - b.x0 + 1;
      const h = b.y1 - b.y0 + 1;
      const fill = size / (w * h);
      const aspect = Math.max(w, h) / Math.min(w, h);
      const relY = (b.y0 - top) / len;
      const holeLike = fill > 0.55 && aspect < 1.9 && size < len * len * 0.004;
      const throatLike = relY > 0.5 && relY < 0.8 && size > len * len * 0.001 && size < len * len * 0.03;
      return holeLike || throatLike;
    });

    // A clean cut is enough: the 3D frame covers the photo's outer edge.
    for (let i = 0; i < N; i++) alpha[i] = outside[i] || (labels[i] && isHole[labels[i]]) ? 0 : 255;
  }

  const close = Number(arg("close", "0"));
  if (close > 0) {
    // Fill the silhouette (holes included), close it, and give back only the outer notches.
    const opaque = new Uint8Array(N);
    for (let i = 0; i < N; i++) opaque[i] = alpha[i] >= 128 ? 1 : 0;
    const outside = borderConnected(opaque, W, H, 0);
    const filled = new Uint8Array(N);
    for (let i = 0; i < N; i++) filled[i] = outside[i] ? 0 : 1;
    const closed = morph(morph(filled, W, H, close, "dilate"), W, H, close, "erode");
    for (let i = 0; i < N; i++) if (closed[i] && outside[i]) alpha[i] = 255;
  }

  if (process.argv.includes("--symmetric")) {
    // A front view is mirror-symmetric; cast shadows and wrist straps are not. Keep only the
    // part of the silhouette (holes filled) that has a mirror twin across the axis of the head.
    const opaque = new Uint8Array(N);
    for (let i = 0; i < N; i++) opaque[i] = alpha[i] >= 128 ? 1 : 0;
    const out = borderConnected(opaque, W, H, 0);
    let top = H;
    let bottom = 0;
    for (let i = 0; i < N; i++) {
      if (out[i]) continue;
      const y = (i / W) | 0;
      if (y < top) top = y;
      if (y > bottom) bottom = y;
    }
    let sum = 0;
    let n = 0;
    for (let y = Math.round(top + 0.1 * (bottom - top)); y <= Math.round(top + 0.4 * (bottom - top)); y++) {
      let x0 = -1;
      let x1 = -1;
      for (let x = 0; x < W; x++) {
        if (out[y * W + x]) continue;
        if (x0 < 0) x0 = x;
        x1 = x;
      }
      if (x0 >= 0) {
        sum += (x0 + x1) / 2;
        n++;
      }
    }
    const axis = sum / Math.max(1, n);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = y * W + x;
        if (out[i]) continue;
        const mx = Math.round(2 * axis - x);
        if (mx < 0 || mx >= W || out[y * W + mx]) alpha[i] = 0;
      }
    }
  }

  // Crop to the racket with a small margin.
  let x0 = W;
  let y0 = H;
  let x1 = 0;
  let y1 = 0;
  for (let i = 0; i < N; i++) {
    if (alpha[i] < 128) continue;
    const x = i % W;
    const y = (i / W) | 0;
    if (x < x0) x0 = x;
    if (x > x1) x1 = x;
    if (y < y0) y0 = y;
    if (y > y1) y1 = y;
  }
  const m = Math.round((y1 - y0) * 0.02);
  x0 = Math.max(0, x0 - m);
  y0 = Math.max(0, y0 - m);
  x1 = Math.min(W - 1, x1 + m);
  y1 = Math.min(H - 1, y1 + m);

  const rgba = Buffer.alloc(N * 4);
  for (let i = 0; i < N; i++) {
    rgba[i * 4] = data[i * 4];
    rgba[i * 4 + 1] = data[i * 4 + 1];
    rgba[i * 4 + 2] = data[i * 4 + 2];
    rgba[i * 4 + 3] = alpha[i];
  }
  await sharp(rgba, { raw: { width: W, height: H, channels: 4 } })
    .extract({ left: x0, top: y0, width: x1 - x0 + 1, height: y1 - y0 + 1 })
    .png()
    .toFile(output);
  console.log(`${output}  ${x1 - x0 + 1}x${y1 - y0 + 1}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
