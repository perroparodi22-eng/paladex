/**
 * Small raster toolkit for tracing racket photos: binary morphology, connected
 * components, flood fill and a sub-pixel marching-squares contour extractor.
 * Pure TypeScript, no native dependencies (images are decoded with sharp).
 */

export type P = [number, number];

/** Binary erosion/dilation with a (2r+1)² square, separable, O(n). */
export function morph(src: Uint8Array, W: number, H: number, r: number, op: "erode" | "dilate"): Uint8Array {
  const tmp = new Uint8Array(W * H);
  const out = new Uint8Array(W * H);
  const want = op === "erode" ? 1 : 0;
  const pass = (from: Uint8Array, to: Uint8Array, horizontal: boolean) => {
    const outer = horizontal ? H : W;
    const inner = horizontal ? W : H;
    for (let o = 0; o < outer; o++) {
      // Running count of "want" pixels inside the window.
      let count = 0;
      const at = (i: number) => (horizontal ? o * W + i : i * W + o);
      for (let i = -r; i <= r; i++) if (i >= 0 && i < inner && from[at(i)] === want) count++;
      for (let i = 0; i < inner; i++) {
        const lo = i - r;
        const hi = i + r;
        const windowSize = Math.min(hi, inner - 1) - Math.max(lo, 0) + 1;
        if (op === "erode") to[at(i)] = count === windowSize ? 1 : 0;
        else to[at(i)] = count === windowSize ? 0 : 1;
        // slide
        if (lo >= 0 && from[at(lo)] === want) count--;
        if (hi + 1 < inner && from[at(hi + 1)] === want) count++;
      }
    }
  };
  pass(src, tmp, true);
  pass(tmp, out, false);
  return out;
}

/** 4-connected component labelling of pixels where mask[i] === value. Returns labels (0 = none) and sizes. */
export function label(mask: Uint8Array, W: number, H: number, value = 1): { labels: Int32Array; sizes: number[] } {
  const labels = new Int32Array(W * H);
  const sizes: number[] = [0];
  const queue = new Int32Array(W * H);
  let next = 1;
  for (let i = 0; i < W * H; i++) {
    if (mask[i] !== value || labels[i]) continue;
    let head = 0;
    let tail = 0;
    queue[tail++] = i;
    labels[i] = next;
    let size = 0;
    while (head < tail) {
      const p = queue[head++];
      size++;
      const x = p % W;
      const y = (p - x) / W;
      const nb = [x > 0 ? p - 1 : -1, x < W - 1 ? p + 1 : -1, y > 0 ? p - W : -1, y < H - 1 ? p + W : -1];
      for (const q of nb) {
        if (q >= 0 && mask[q] === value && !labels[q]) {
          labels[q] = next;
          queue[tail++] = q;
        }
      }
    }
    sizes.push(size);
    next++;
  }
  return { labels, sizes };
}

/** Pixels of `value` connected to the image border (4-connected). */
export function borderConnected(mask: Uint8Array, W: number, H: number, value = 0): Uint8Array {
  const seen = new Uint8Array(W * H);
  const queue = new Int32Array(W * H);
  let tail = 0;
  const push = (p: number) => {
    if (mask[p] === value && !seen[p]) {
      seen[p] = 1;
      queue[tail++] = p;
    }
  };
  for (let x = 0; x < W; x++) {
    push(x);
    push((H - 1) * W + x);
  }
  for (let y = 0; y < H; y++) {
    push(y * W);
    push(y * W + W - 1);
  }
  let head = 0;
  while (head < tail) {
    const p = queue[head++];
    const x = p % W;
    const y = (p - x) / W;
    if (x > 0) push(p - 1);
    if (x < W - 1) push(p + 1);
    if (y > 0) push(p - W);
    if (y < H - 1) push(p + W);
  }
  return seen;
}

/**
 * Marching squares on a scalar field. Returns closed loops in pixel
 * coordinates (pixel centres at integer positions), interpolated to the
 * threshold, so contours are sub-pixel accurate on anti-aliased edges.
 */
export function marchingSquares(
  field: Float32Array,
  W: number,
  H: number,
  t: number,
  box?: { x0: number; y0: number; x1: number; y1: number },
): P[][] {
  const x0 = Math.max(0, box?.x0 ?? 0);
  const y0 = Math.max(0, box?.y0 ?? 0);
  const x1 = Math.min(W - 1, box?.x1 ?? W - 1);
  const y1 = Math.min(H - 1, box?.y1 ?? H - 1);
  const v = (x: number, y: number) => field[y * W + x];
  const hId = (x: number, y: number) => y * W + x;
  const vId = (x: number, y: number) => W * H + y * W + x;
  const point = new Map<number, P>();
  const edgePoint = (id: number, ax: number, ay: number, bx: number, by: number): number => {
    if (!point.has(id)) {
      const va = v(ax, ay);
      const vb = v(bx, by);
      const f = va === vb ? 0.5 : (t - va) / (vb - va);
      point.set(id, [ax + (bx - ax) * f, ay + (by - ay) * f]);
    }
    return id;
  };
  const links = new Map<number, number[]>();
  const link = (a: number, b: number) => {
    (links.get(a) ?? links.set(a, []).get(a)!).push(b);
    (links.get(b) ?? links.set(b, []).get(b)!).push(a);
  };
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const tl = v(x, y) > t ? 8 : 0;
      const tr = v(x + 1, y) > t ? 4 : 0;
      const br = v(x + 1, y + 1) > t ? 2 : 0;
      const bl = v(x, y + 1) > t ? 1 : 0;
      const c = tl | tr | br | bl;
      if (c === 0 || c === 15) continue;
      const top = () => edgePoint(hId(x, y), x, y, x + 1, y);
      const bottom = () => edgePoint(hId(x, y + 1), x, y + 1, x + 1, y + 1);
      const left = () => edgePoint(vId(x, y), x, y, x, y + 1);
      const right = () => edgePoint(vId(x + 1, y), x + 1, y, x + 1, y + 1);
      const centre = (v(x, y) + v(x + 1, y) + v(x + 1, y + 1) + v(x, y + 1)) / 4 > t;
      switch (c) {
        case 1: case 14: link(left(), bottom()); break;
        case 2: case 13: link(bottom(), right()); break;
        case 3: case 12: link(left(), right()); break;
        case 4: case 11: link(top(), right()); break;
        case 6: case 9: link(top(), bottom()); break;
        case 7: case 8: link(left(), top()); break;
        case 5:
          if (centre) { link(left(), top()); link(bottom(), right()); }
          else { link(left(), bottom()); link(top(), right()); }
          break;
        case 10:
          if (centre) { link(top(), right()); link(left(), bottom()); }
          else { link(left(), top()); link(bottom(), right()); }
          break;
      }
    }
  }
  const loops: P[][] = [];
  const used = new Set<number>();
  for (const start of links.keys()) {
    if (used.has(start)) continue;
    const loop: P[] = [];
    let prev = -1;
    let cur = start;
    while (cur !== undefined && !used.has(cur)) {
      used.add(cur);
      loop.push(point.get(cur)!);
      const nbs = links.get(cur) ?? [];
      const nxt = nbs.find((n) => n !== prev && !used.has(n));
      prev = cur;
      if (nxt === undefined) break;
      cur = nxt;
    }
    if (loop.length > 8) loops.push(loop);
  }
  return loops.sort((a, b) => b.length - a.length);
}

/** Ramer–Douglas–Peucker simplification for an open polyline. */
export function simplify(points: P[], tolerance: number): P[] {
  if (points.length < 3) return points;
  const sqTol = tolerance * tolerance;
  const keep = new Uint8Array(points.length);
  keep[0] = keep[points.length - 1] = 1;
  const stack: Array<[number, number]> = [[0, points.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop()!;
    let maxD = 0;
    let idx = -1;
    const [ax, ay] = points[a];
    const [bx, by] = points[b];
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy || 1e-12;
    for (let i = a + 1; i < b; i++) {
      const [px, py] = points[i];
      const tt = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
      const ex = ax + tt * dx - px;
      const ey = ay + tt * dy - py;
      const d = ex * ex + ey * ey;
      if (d > maxD) {
        maxD = d;
        idx = i;
      }
    }
    if (maxD > sqTol && idx > 0) {
      keep[idx] = 1;
      stack.push([a, idx], [idx, b]);
    }
  }
  return points.filter((_, i) => keep[i]);
}

/** Simplify a closed loop: split at the farthest pair so both halves keep their shape. */
export function simplifyLoop(loop: P[], tolerance: number): P[] {
  if (loop.length < 8) return loop;
  let far = 0;
  let best = 0;
  for (let i = 0; i < loop.length; i++) {
    const d = (loop[i][0] - loop[0][0]) ** 2 + (loop[i][1] - loop[0][1]) ** 2;
    if (d > best) {
      best = d;
      far = i;
    }
  }
  const a = simplify(loop.slice(0, far + 1), tolerance);
  const b = simplify([...loop.slice(far), loop[0]], tolerance);
  return [...a.slice(0, -1), ...b.slice(0, -1)];
}

/** Light smoothing (moving average over a closed loop). */
export function smoothLoop(loop: P[], radius: number): P[] {
  if (radius <= 0) return loop;
  const n = loop.length;
  return loop.map((_, i) => {
    let sx = 0;
    let sy = 0;
    for (let k = -radius; k <= radius; k++) {
      const q = loop[(i + k + n) % n];
      sx += q[0];
      sy += q[1];
    }
    const c = 2 * radius + 1;
    return [sx / c, sy / c] as P;
  });
}
