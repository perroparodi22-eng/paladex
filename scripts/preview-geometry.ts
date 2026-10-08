/**
 * Dev aid: writes .tmp/geometry-preview.html with every shape × pattern so the
 * shared racket geometry can be checked by eye. Not used by the app.
 *   npx tsx scripts/preview-geometry.ts
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { buildBlueprint, type Vec2 } from "../src/lib/racket-geometry";
import { RACKET_SHAPES, type RacketVisual } from "../src/domain/types";

const X = (x: number) => (x * 1000 + 140).toFixed(2);
const Y = (y: number) => ((0.47 - y) * 1000).toFixed(2);
const path = (poly: Vec2[]) => `M${poly.map(([x, y]) => `${X(x)} ${Y(y)}`).join("L")}Z`;
const circle = (x: number, y: number, r: number) =>
  `M${X(x - r)} ${Y(y)}a${r * 1000} ${r * 1000} 0 1 0 ${r * 2000} 0a${r * 1000} ${r * 1000} 0 1 0 ${-r * 2000} 0Z`;

const patterns: RacketVisual["pattern"][] = ["sweep", "split", "chevron", "ring", "border", "blade"];
let html = `<html><body style="background:#06080b;color:#eee;font-family:sans-serif;display:flex;flex-wrap:wrap;gap:12px">`;
for (const shape of RACKET_SHAPES) {
  patterns.forEach((pattern, i) => {
    const bp = buildBlueprint(shape, { pattern, holes: i % 2 ? "rings" : "hex", bridge: i % 3 === 0 });
    const holes = bp.holes.map((h) => circle(h.x, h.y, h.r)).join("");
    let svg = `<svg viewBox="0 0 280 480" width="160" height="274">`;
    svg += `<path d="${path(bp.frameOuter)}${path(bp.face)}${path(bp.heart)}" fill="#222" fill-rule="evenodd" stroke="#555" stroke-width="0.5"/>`;
    svg += `<path d="${path(bp.face)}${holes}" fill="#2a5db0" fill-rule="evenodd"/>`;
    for (const d of bp.decals) {
      const dh = d.holes.map((idx) => circle(bp.holes[idx].x, bp.holes[idx].y, bp.holes[idx].r)).join("");
      svg += `<path d="${path(d.polygon)}${d.inner ? path(d.inner) : ""}${dh}" fill="${d.tone === "accent" ? "#e8f04a" : "#fff"}" fill-rule="evenodd"/>`;
    }
    if (bp.bridge) svg += `<path d="${path(bp.bridge)}" fill="#222"/>`;
    svg += `<path d="${path(bp.bumper)}" fill="rgba(200,200,200,0.35)"/>`;
    svg += `<rect x="${X(-0.0165)}" y="${Y(0.142)}" width="33" height="${(0.142 - 0.011) * 1000}" fill="#ddd"/>`;
    const ss = bp.sweetSpot;
    svg += `<ellipse cx="${X(ss.x)}" cy="${Y(ss.y)}" rx="${ss.rx * 1000}" ry="${ss.ry * 1000}" fill="none" stroke="#f0f" stroke-width="0.8"/>`;
    svg += `</svg>`;
    html += `<figure style="margin:0">${svg}<figcaption>${shape} · ${pattern} · ${bp.holes.length} holes</figcaption></figure>`;
  });
}
html += `</body></html>`;
mkdirSync(".tmp", { recursive: true });
writeFileSync(".tmp/geometry-preview.html", html);
console.log("wrote .tmp/geometry-preview.html");
