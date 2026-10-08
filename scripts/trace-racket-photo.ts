/**
 * Traces a front-view racket photo (transparent background) into model
 * geometry: frame outline, throat opening, every hole, grip width and the
 * mapping used to project the photo onto the 3D face as a texture.
 *
 *   npm run models:trace -- --slug adidas-metalbone-3-4 --image assets/reference/adidas-metalbone-3-4/3.webp
 *
 * Options:
 *   --length-mm 455      overall racket length used for scale (butt cap to tip)
 *   --strap 6            opening radius in px used to strip a wrist strap
 *   --rotate <deg>       force a rotation; by default small tilts are measured and removed
 *   --neck-y <px>        override where the frame ends and the handle starts
 *   --face-inset-mm 8.5  width of the frame rim around the face
 *   --smooth 1           outline smoothing radius in points (raise for noisy edges)
 *   --mirror-outline right|left  rebuild the outline from one clean half
 *
 * Writes src/data/designs/<slug>.trace.json and a debug overlay in .tmp/.
 * Photo requirements: straight-on front view, racket vertical, transparent
 * background (holes transparent too). See docs/3D-PIPELINE.md.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import sharp from "sharp";
import { borderConnected, label, marchingSquares, morph, simplifyLoop, smoothLoop, type P } from "./lib/raster";

function arg(name: string, fallback?: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : fallback;
}

/** Decode (optionally rotated) photo and isolate the racket silhouette. */
export async function prepare(image: string, rotateDeg: number, strap: number) {
  let input: Buffer | string = image;
  if (Math.abs(rotateDeg) > 1e-3) {
    input = await sharp(image)
      .ensureAlpha()
      .rotate(rotateDeg, { background: { r: 0, g: 0, b: 0, alpha: 0 } })
      .png()
      .toBuffer();
  }
  const { data, info } = await sharp(input).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const W = info.width;
  const H = info.height;
  const A = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) A[i] = data[i * 4 + 3];
  const mask = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) mask[i] = A[i] > 127 ? 1 : 0;

  // Strip thin attachments (wrist strap): opening, keep the largest blob, restore exact edges.
  const opened = morph(morph(mask, W, H, strap, "erode"), W, H, strap, "dilate");
  const { labels, sizes } = label(opened, W, H, 1);
  let biggest = 1;
  for (let i = 2; i < sizes.length; i++) if (sizes[i] > sizes[biggest]) biggest = i;
  const mainBlob = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) mainBlob[i] = labels[i] === biggest ? 1 : 0;
  const near = morph(mainBlob, W, H, strap + 2, "dilate");
  const keep = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) keep[i] = mask[i] && near[i] ? 1 : 0;

  let top = H;
  let bottom = 0;
  let minX = W;
  let maxX = 0;
  const rowMin = new Int32Array(H).fill(-1);
  const rowMax = new Int32Array(H).fill(-1);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (!keep[y * W + x]) continue;
      if (rowMin[y] < 0) rowMin[y] = x;
      rowMax[y] = x;
      top = Math.min(top, y);
      bottom = Math.max(bottom, y);
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
    }
  }
  return { W, H, A, keep, near, rowMin, rowMax, top, bottom, minX, maxX, len: bottom - top + 1 };
}

/** Tilt of the racket axis, from row midpoints of the head and the grip (degrees, clockwise-positive for sharp). */
function measureTilt(p: Awaited<ReturnType<typeof prepare>>): number {
  const pts: Array<[number, number]> = [];
  const add = (y0: number, y1: number) => {
    for (let y = Math.round(y0); y <= Math.round(y1); y++) {
      if (p.rowMin[y] >= 0) pts.push([y, (p.rowMin[y] + p.rowMax[y]) / 2]);
    }
  };
  add(p.top + 0.08 * p.len, p.top + 0.45 * p.len);
  add(p.bottom - 0.2 * p.len, p.bottom - 0.05 * p.len);
  const n = pts.length;
  const my = pts.reduce((s, q) => s + q[0], 0) / n;
  const mx = pts.reduce((s, q) => s + q[1], 0) / n;
  let num = 0;
  let den = 0;
  for (const [y, x] of pts) {
    num += (y - my) * (x - mx);
    den += (y - my) ** 2;
  }
  const slope = num / den; // dx/dy: positive when the bottom leans right
  return (Math.atan(slope) * 180) / Math.PI;
}

async function main() {
  const slug = arg("slug");
  const image = arg("image");
  if (!slug || !image) {
    console.error("usage: trace-racket-photo --slug <slug> --image <file>");
    process.exit(1);
  }
  const lengthM = Number(arg("length-mm", "455")) / 1000;
  const strap = Number(arg("strap", "6"));
  const faceInsetMm = Number(arg("face-inset-mm", "8.5"));

  let rotateDeg = arg("rotate") !== undefined ? Number(arg("rotate")) : 0;
  let p = await prepare(image, rotateDeg, strap);
  if (arg("rotate") === undefined) {
    const tilt = measureTilt(p);
    if (Math.abs(tilt) > 0.05) {
      rotateDeg = +tilt.toFixed(3);
      p = await prepare(image, rotateDeg, strap);
      console.log(`  removed a ${tilt.toFixed(2)}° tilt (residual ${measureTilt(p).toFixed(3)}°)`);
    }
  }
  const { W, H, A, keep, near, rowMin, rowMax, top, bottom, minX, maxX, len } = p;

  const width = (y: number) => (rowMin[y] < 0 ? 0 : rowMax[y] - rowMin[y] + 1);
  const gripRows: number[] = [];
  for (let y = Math.round(bottom - 0.2 * len); y <= Math.round(bottom - 0.04 * len); y++) gripRows.push(width(y));
  gripRows.sort((a, b) => a - b);
  const gripW = gripRows[Math.floor(gripRows.length / 2)];
  let neckY = Number(arg("neck-y", "0"));
  if (!neckY) {
    // Walk up from the grip until the silhouette flares into the throat.
    for (let y = Math.round(bottom - 0.12 * len); y > top; y--) {
      if (width(y) > gripW * 1.3) {
        neckY = y + 6;
        break;
      }
    }
  }
  let axisSum = 0;
  let axisN = 0;
  for (let y = Math.round(bottom - 0.2 * len); y <= Math.round(bottom - 0.04 * len); y++) {
    axisSum += (rowMin[y] + rowMax[y]) / 2;
    axisN++;
  }
  const gripAxis = axisSum / axisN;
  const headAxis = (minX + maxX) / 2;
  const axisX = headAxis;

  // Interior transparent regions: holes and the throat opening.
  const exterior = borderConnected(keep, W, H, 0);
  const interior = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) interior[i] = !keep[i] && !exterior[i] ? 1 : 0;
  const comps = label(interior, W, H, 1);
  const stats = new Map<number, { n: number; x0: number; y0: number; x1: number; y1: number }>();
  for (let i = 0; i < W * H; i++) {
    const l = comps.labels[i];
    if (!l) continue;
    const x = i % W;
    const y = (i - x) / W;
    const s = stats.get(l) ?? { n: 0, x0: x, y0: y, x1: x, y1: y };
    s.n++;
    s.x0 = Math.min(s.x0, x);
    s.y0 = Math.min(s.y0, y);
    s.x1 = Math.max(s.x1, x);
    s.y1 = Math.max(s.y1, y);
    stats.set(l, s);
  }
  const ordered = [...stats.entries()].sort((a, b) => b[1].n - a[1].n);
  // Size threshold scales with the photo (about 2000 px on a 1100 px tall racket).
  const throat = ordered.find(([, s]) => s.y0 > top + 0.45 * len && s.n > Math.max(400, 0.0015 * len * len));
  const holeCandidates = ordered.filter(([l, s]) => {
    if (throat && l === throat[0]) return false;
    const w = s.x1 - s.x0 + 1;
    const h = s.y1 - s.y0 + 1;
    const roundness = s.n / (Math.PI * (Math.max(w, h) / 2) ** 2);
    return s.n > 60 && roundness > 0.6 && Math.abs(w - h) <= Math.max(3, 0.25 * Math.max(w, h));
  });
  const holesPx = holeCandidates.map(([, s]) => {
    // Sub-pixel area and centroid from the alpha channel around the hole.
    let area = 0;
    let cx = 0;
    let cy = 0;
    for (let y = s.y0 - 2; y <= s.y1 + 2; y++) {
      for (let x = s.x0 - 2; x <= s.x1 + 2; x++) {
        const t = (255 - A[y * W + x]) / 255;
        area += t;
        cx += t * x;
        cy += t * y;
      }
    }
    return { x: cx / area, y: cy / area, r: Math.sqrt(area / Math.PI) };
  });

  // Outer frame contour: holes and throat filled, everything below the neck removed.
  const field = new Float32Array(W * H);
  for (let i = 0; i < W * H; i++) {
    const y = Math.floor(i / W);
    if (y > neckY) field[i] = 0;
    else if (interior[i]) field[i] = 255;
    else field[i] = near[i] ? A[i] : 0;
  }
  const outerLoops = marchingSquares(field, W, H, 127.5, { x0: minX - 3, y0: top - 3, x1: maxX + 3, y1: neckY + 3 });
  // --smooth: heavier smoothing for noisy outlines (pale frames on pale backgrounds); spikes would make the face polygon self-intersect.
  let outerPx = smoothLoop(simplifyLoop(outerLoops[0], 0.35), Number(arg("smooth", "1")));
  // --mirror-outline right|left: rebuild the outline from its clean half (photos taken slightly off-axis).
  const mirrorSide = arg("mirror-outline");
  if (mirrorSide === "right" || mirrorSide === "left") {
    const keep = (p: P) => (mirrorSide === "right" ? p[0] >= headAxis : p[0] <= headAxis);
    const n = outerPx.length;
    const start = outerPx.findIndex((p, i) => keep(p) && !keep(outerPx[(i - 1 + n) % n]));
    const arc: P[] = [];
    for (let k = 0; k < n; k++) {
      const p = outerPx[(start + k) % n];
      if (!keep(p)) break;
      arc.push(p);
    }
    outerPx = [...arc, ...arc.slice().reverse().map(([x, y]) => [2 * headAxis - x, y] as P)];
  }

  let throatPx: P[] = [];
  if (throat) {
    const s = throat[1];
    const tf = new Float32Array(W * H).fill(255);
    for (let y = s.y0 - 3; y <= s.y1 + 3; y++) {
      for (let x = s.x0 - 3; x <= s.x1 + 3; x++) {
        const i = y * W + x;
        // Other interior regions (holes) are filled solid so only the throat yields a contour.
        tf[i] = interior[i] && comps.labels[i] !== throat[0] ? 255 : A[i];
      }
    }
    const loops = marchingSquares(tf, W, H, 127.5, { x0: s.x0 - 3, y0: s.y0 - 3, x1: s.x1 + 3, y1: s.y1 + 3 });
    throatPx = smoothLoop(simplifyLoop(loops[0], 0.35), 1);
  }

  // Pixel -> model space (metres; +Y from butt to tip, +X right, origin at the butt on the axis).
  const s = lengthM / len;
  const buttY = bottom + 0.5;
  const toM = ([x, y]: P): P => [+((x - axisX) * s).toFixed(5), +((buttY - y) * s).toFixed(5)];
  const ensureCCW = (poly: P[]) => {
    let a = 0;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) a += (poly[j][0] - poly[i][0]) * (poly[j][1] + poly[i][1]);
    return a < 0 ? poly.slice().reverse() : poly;
  };

  const trace = {
    slug,
    source: image.replace(/\\/g, "/"),
    rotateDeg,
    imageSize: [W, H],
    metresPerPixel: +s.toFixed(8),
    axisX: +axisX.toFixed(2),
    buttY,
    topY: top,
    gripAxisOffsetM: +((gripAxis - headAxis) * s).toFixed(5),
    frameOuter: ensureCCW(outerPx.map(toM)),
    throat: throatPx.length ? ensureCCW(throatPx.map(toM)) : [],
    holes: holesPx
      // Holes are only ever in the head; perforated overgrips can look like holes in a cutout.
      .filter((h) => h.y < neckY - 0.04 / s)
      .map((h) => ({ x: +((h.x - axisX) * s).toFixed(5), y: +((buttY - h.y) * s).toFixed(5), r: +(h.r * s).toFixed(5) }))
      .sort((a, b) => b.y - a.y || a.x - b.x),
    neckY: +((buttY - neckY) * s).toFixed(5),
    faceInsetM: faceInsetMm / 1000,
    grip: { halfWidth: +((gripW / 2) * s).toFixed(5) },
    headWidthM: +((maxX - minX + 1) * s).toFixed(4),
  };

  const out = `src/data/designs/${slug}.trace.json`;
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, JSON.stringify(trace, null, 1));

  // Debug overlay on the (rotated) photo.
  const path = (pts: P[]) => `M${pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join("L")}Z`;
  const circles = holesPx.map((h) => `<circle cx="${h.x}" cy="${h.y}" r="${h.r}" fill="none" stroke="#00e0ff" stroke-width="1.5"/>`).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}">
    <path d="${path(outerPx)}" fill="none" stroke="#ff2d55" stroke-width="2"/>
    ${throatPx.length ? `<path d="${path(throatPx)}" fill="none" stroke="#ffd60a" stroke-width="2"/>` : ""}
    ${circles}
    <line x1="0" x2="${W}" y1="${neckY}" y2="${neckY}" stroke="#30d158" stroke-width="1.5"/>
    <line x1="${axisX}" x2="${axisX}" y1="0" y2="${H}" stroke="#ffffff" stroke-width="1" stroke-dasharray="6 6"/>
  </svg>`;
  mkdirSync(".tmp", { recursive: true });
  let base = sharp(image).ensureAlpha();
  if (Math.abs(rotateDeg) > 1e-3) base = sharp(await base.rotate(rotateDeg, { background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toBuffer());
  await base
    .flatten({ background: "#7a7f86" })
    .composite([{ input: Buffer.from(svg), top: 0, left: 0 }])
    .png()
    .toFile(`.tmp/trace-${slug}.png`);

  console.log(`traced ${slug}: ${trace.holes.length} holes, outline ${trace.frameOuter.length} pts, throat ${trace.throat.length} pts`);
  console.log(`  scale ${(s * 1000).toFixed(4)} mm/px, head width ${(trace.headWidthM * 1000).toFixed(1)} mm, grip ${(gripW * s * 1000).toFixed(1)} mm`);
  console.log(`  neck at ${(trace.neckY * 1000).toFixed(1)} mm, grip axis offset ${(trace.gripAxisOffsetM * 1000).toFixed(2)} mm`);
  console.log(`  wrote ${out} and .tmp/trace-${slug}.png`);
}

if (process.argv[1]?.includes("trace-racket-photo")) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
