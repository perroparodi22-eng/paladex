/** Small factories for unit tests. Only fields the code under test reads matter. */
import type { RacketSummary } from "@/domain/types";

type Scores = NonNullable<RacketSummary["scores"]>;

export function scores(over: Partial<Scores> = {}): Scores {
  return { power: 7, control: 7, maneuverability: 7, forgiveness: 7, sweetSpot: 7, defense: 7, attack: 7, overall: 7, ...over };
}

export function racket(over: Partial<RacketSummary> & { slug: string }): RacketSummary {
  const brand = over.brand ?? { id: 1, slug: "test-brand", name: "Test Brand" };
  const name = over.name ?? over.slug;
  return {
    id: 1,
    name,
    fullName: `${brand.name} ${name}`,
    brand,
    year: 2026,
    shortDescription: "",
    shape: "teardrop",
    weightMinG: 355,
    weightMaxG: 370,
    balance: "medium",
    hardness: "medium",
    surfaceFinish: null,
    levels: ["intermediate"],
    styles: ["all-round"],
    scores: scores(),
    priceFrom: null,
    indicativePrice: { amountCents: 20000, currency: "EUR" },
    offerCount: 0,
    modelStatus: "platform",
    modelPreviewUrl: null,
    modelUrl: null,
    imageUrl: null,
    imageAlt: "",
    visual: { face: "#000", frame: "#000", accent: "#fff", accent2: "#fff", grip: "#000", pattern: "sweep", holes: "hex", bridge: false },
    featured: false,
    isNew: false,
    dataStatus: "unverified",
    userRating: null,
    createdAt: "2026-10-01T00:00:00.000Z",
    proPlayers: [],
    ...over,
  };
}
