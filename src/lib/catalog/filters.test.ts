import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { racket, scores } from "@/test/fixtures";
import { EMPTY_FILTERS, activeFilterCount, applyFilters, parseFilters, searchScore, serializeFilters, type CatalogFilters } from "./filters";

describe("parseFilters / serializeFilters", () => {
  it("round-trips a fully populated filter set", () => {
    const f: CatalogFilters = {
      q: "metalbone",
      brands: ["adidas", "nox"],
      shapes: ["diamond", "hybrid"],
      levels: ["advanced"],
      styles: ["power", "aggressive"],
      balances: ["medium-high"],
      hardness: ["hard"],
      priceMin: 100,
      priceMax: 300,
      weightMin: 355,
      weightMax: null,
      yearMin: 2025,
      minPower: 8,
      minControl: 6.5,
      minManeuverability: 7,
      model: "platform",
      sort: "price-asc",
    };
    assert.deepEqual(parseFilters(new URLSearchParams(serializeFilters(f))), f);
  });

  it("serializes the empty state to an empty query string", () => {
    assert.equal(serializeFilters(EMPTY_FILTERS), "");
    assert.deepEqual(parseFilters(new URLSearchParams("")), EMPTY_FILTERS);
  });

  it("reads Next.js searchParams records, taking the first of repeated keys", () => {
    const f = parseFilters({ brand: ["Bullpadel", "nox"], sort: "newest", price: "-250" });
    assert.deepEqual(f.brands, ["bullpadel"]);
    assert.equal(f.sort, "newest");
    assert.equal(f.priceMin, null);
    assert.equal(f.priceMax, 250);
  });

  it("drops unknown or unsafe values instead of passing them through", () => {
    const f = parseFilters(
      new URLSearchParams({
        shape: "round,square,diamond",
        brand: "nox,<script>,a b",
        sort: "cheapest",
        model: "hologram",
        power: "lots",
        q: "x".repeat(200),
      }),
    );
    assert.deepEqual(f.shapes, ["round", "diamond"]);
    assert.deepEqual(f.brands, ["nox"]);
    assert.equal(f.sort, "popular");
    assert.equal(f.model, "any");
    assert.equal(f.minPower, null);
    assert.equal(f.q.length, 80);
  });

  it("counts a price or weight range as one active filter", () => {
    assert.equal(activeFilterCount(EMPTY_FILTERS), 0);
    assert.equal(activeFilterCount({ ...EMPTY_FILTERS, priceMin: 50, priceMax: 200, brands: ["nox", "head"], q: "ignored" }), 3);
  });
});

describe("searchScore", () => {
  const r = racket({ slug: "nox-at10", name: "AT10 Genius", brand: { id: 2, slug: "nox", name: "Nox" } });

  it("requires every token to match", () => {
    assert.ok(searchScore(r, "nox at10") > 0);
    assert.equal(searchScore(r, "nox metalbone"), 0);
  });

  it("ranks whole words above prefixes and ignores accents and case", () => {
    assert.ok(searchScore(r, "genius") > searchScore(r, "geni"));
    assert.ok(searchScore(r, "GÉNIUS") > 0);
  });

  it("treats an empty query as a match", () => {
    assert.equal(searchScore(r, "   "), 1);
  });
});

describe("applyFilters", () => {
  const cheap = racket({ slug: "cheap", shape: "round", indicativePrice: { amountCents: 6000, currency: "EUR" }, scores: scores({ power: 5 }) });
  const mid = racket({ slug: "mid", shape: "teardrop", indicativePrice: { amountCents: 15000, currency: "EUR" }, scores: scores({ power: 7 }) });
  const pricey = racket({ slug: "pricey", shape: "diamond", indicativePrice: { amountCents: 30000, currency: "EUR" }, scores: scores({ power: 9 }) });
  const unpriced = racket({ slug: "unpriced", indicativePrice: null, modelStatus: "unavailable", scores: null });
  const all = [mid, unpriced, pricey, cheap];
  const slugs = (f: Partial<CatalogFilters>) => applyFilters(all, { ...EMPTY_FILTERS, ...f }).map((r) => r.slug);

  it("filters by shape and price range, excluding rackets with no price", () => {
    assert.deepEqual(slugs({ shapes: ["round", "diamond"] }).sort(), ["cheap", "pricey"]);
    assert.deepEqual(slugs({ priceMin: 100, priceMax: 200 }), ["mid"]);
    assert.ok(!slugs({ priceMax: 1000 }).includes("unpriced"));
  });

  it("sorts by price with unpriced rackets last in both directions", () => {
    assert.deepEqual(slugs({ sort: "price-asc" }), ["cheap", "mid", "pricey", "unpriced"]);
    assert.deepEqual(slugs({ sort: "price-desc" }), ["pricey", "mid", "cheap", "unpriced"]);
  });

  it("applies minimum scores and 3D model filters", () => {
    assert.deepEqual(slugs({ minPower: 7, sort: "power" }), ["pricey", "mid"]);
    assert.deepEqual(slugs({ model: "none" }), ["unpriced"]);
    assert.ok(!slugs({ model: "interactive" }).includes("unpriced"));
  });

  it("uses popularity for the default sort", () => {
    const out = applyFilters(all, EMPTY_FILTERS, { cheap: 10, pricey: 5 }).map((r) => r.slug);
    assert.deepEqual(out.slice(0, 2), ["cheap", "pricey"]);
  });
});
