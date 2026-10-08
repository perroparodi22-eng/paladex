import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { racket, scores } from "@/test/fixtures";
import { WEIGHTS, recommend, type FinderAnswers } from "./engine";

const base: FinderAnswers = {
  level: "intermediate",
  game: "balanced",
  priority: "balance",
  shape: "any",
  weight: "any",
  budget: null,
  armCare: false,
  current: null,
};

const powerDiamond = racket({
  slug: "power-diamond",
  shape: "diamond",
  balance: "high",
  hardness: "hard",
  levels: ["advanced"],
  indicativePrice: { amountCents: 30000, currency: "EUR" },
  scores: scores({ power: 9.5, attack: 9.5, control: 6, defense: 6, forgiveness: 5.5, maneuverability: 6 }),
});
const controlRound = racket({
  slug: "control-round",
  shape: "round",
  balance: "low",
  hardness: "soft",
  levels: ["beginner", "intermediate"],
  indicativePrice: { amountCents: 9000, currency: "EUR" },
  scores: scores({ power: 6, attack: 6, control: 9, defense: 9, forgiveness: 9, maneuverability: 8.5 }),
});
const allRound = racket({
  slug: "all-round",
  shape: "teardrop",
  levels: ["intermediate", "advanced"],
  indicativePrice: { amountCents: 18000, currency: "EUR" },
  scores: scores({ power: 7.8, control: 7.8, attack: 7.8, defense: 7.6 }),
});
const catalog = [powerDiamond, controlRound, allRound];
const top = (a: Partial<FinderAnswers>) => recommend(catalog, { ...base, ...a })[0].racket.slug;

describe("recommend", () => {
  it("has weights that sum to 1", () => {
    const sum = Object.values(WEIGHTS).reduce((a, b) => a + b, 0);
    assert.ok(Math.abs(sum - 1) < 1e-9);
  });

  it("puts an aggressive advanced player on the power diamond", () => {
    assert.equal(top({ level: "advanced", game: "aggressive", priority: "power" }), "power-diamond");
  });

  it("keeps a beginner away from a stiff, head-heavy diamond", () => {
    const recs = recommend(catalog, { ...base, level: "beginner" });
    const diamond = recs.find((r) => r.racket.slug === "power-diamond");
    assert.equal(recs.at(-1), diamond);
    assert.ok(diamond && diamond.factors.level < 0.1);
    assert.ok(diamond?.drawbacks.includes("Aimed at advanced players"));
  });

  it("favours soft, head-light rackets when the arm needs care", () => {
    assert.equal(top({ armCare: true, priority: "control", game: "defensive" }), "control-round");
    const rec = recommend(catalog, { ...base, armCare: true }).find((r) => r.racket.slug === "power-diamond");
    assert.ok(rec?.drawbacks.some((d) => d.includes("sore arm")));
  });

  it("penalises rackets over budget and says by how much", () => {
    const answers: FinderAnswers = { ...base, level: "advanced", game: "aggressive", priority: "power" };
    const match = (budget: number | null) => recommend(catalog, { ...answers, budget }).find((r) => r.racket.slug === "power-diamond");
    const over = match(150);
    assert.equal(over?.factors.budget, 0);
    assert.ok(over?.drawbacks.includes("About €150 over your budget"));
    assert.ok((over?.match ?? 100) < (match(null)?.match ?? 0));
    assert.ok(match(400)?.reasons.some((r) => r.startsWith("Within your budget")));
  });

  it("excludes the current racket and compares against it", () => {
    const recs = recommend(catalog, { ...base, current: "all-round" });
    assert.ok(recs.every((r) => r.racket.slug !== "all-round"));
    const diamond = recs.find((r) => r.racket.slug === "power-diamond");
    assert.ok(diamond?.versusCurrent.includes("+1.7 power"));
    assert.ok(diamond?.versusCurrent.includes("−1.8 control"));
    assert.ok((diamond?.versusCurrent.length ?? 0) <= 4);

    const twin = racket({ slug: "twin", shape: "round", scores: allRound.scores });
    const [rec] = recommend([allRound, twin], { ...base, current: "all-round" });
    assert.deepEqual(rec.versusCurrent, ["Round instead of teardrop"]);
  });

  it("keeps match percentages within 40–98 and sorted, and honours the limit", () => {
    const recs = recommend(catalog, base, 2);
    assert.equal(recs.length, 2);
    for (const r of recs) assert.ok(r.match >= 40 && r.match <= 98, `match ${r.match}`);
    assert.ok(recs[0].match >= recs[1].match);
  });
});
