/**
 * Turns the owner's brand catalogue (brand-catalogue.ts) into seed rackets.
 *
 * Facts (shape, weight, balance, core, face, profile, feel, level) come from
 * the brand listings. Paladex's sample scores and "who is it for" lines are
 * derived from those facts with the fixed rules below, labelled as sample
 * evaluations like every other racket. Nothing is invented: no prices (the
 * catalogue leaves them out on purpose) and no editorial reviews.
 *
 * Rackets that were already in the seed keep their slug, price, scores and
 * review; their specs, description and photos are replaced by the brand data.
 */
import type { Balance, Hardness, PlayerLevel, PlayingStyle, RacketShape, SurfaceFinish } from "@/domain/types";
import { catalogueVisuals } from "../designs/catalogue.generated";
import { brandCatalogue, CATALOGUE_SOURCE_NOTE, type CatalogueRacket } from "./brand-catalogue";
import photos from "./catalogue-photos.generated.json";
import { proPlayersBySlug, proRackets, PRO_SOURCE_NOTE_RETAILER } from "./pro-players";
import type { SeedRacket } from "./rackets";

const BRAND_NAMES: Record<CatalogueRacket["brand"], string> = {
  bullpadel: "Bullpadel",
  head: "Head",
  nox: "Nox",
  babolat: "Babolat",
  adidas: "adidas",
  wilson: "Wilson",
  siux: "Siux",
  lok: "Lok",
  kuikma: "Kuikma",
  "drop-shot": "Drop Shot",
};
const PHOTO_SITES: Record<CatalogueRacket["brand"], string> = {
  bullpadel: "bullpadel.com",
  head: "head.com",
  nox: "noxsport.com",
  babolat: "babolat.com",
  adidas: "adidas.com",
  wilson: "wilson.com",
  siux: "siuxpadel.com",
  lok: "lokpadel.com",
  kuikma: "decathlon.com",
  "drop-shot": "dropshot.es",
};

function shapeOf(r: CatalogueRacket): RacketShape {
  const s = (r.shape ?? "").toLowerCase();
  if (s.includes("round")) return "round";
  if (s.includes("hybrid")) return "hybrid";
  if (s.includes("diamond") || s.includes("geometric")) return "diamond";
  if (s.includes("teardrop") || s.includes("drop")) return "teardrop";
  // Not listed: Babolat names its lines by shape (Viper = diamond, Veron = teardrop).
  if (/viper/i.test(r.name)) return "diamond";
  return "teardrop";
}

function weightOf(r: CatalogueRacket): [number | null, number | null] {
  const w = r.weight ?? "";
  const range = /(\d{3})\s*-\s*(\d{3})/.exec(w);
  if (range) return [Number(range[1]), Number(range[2])];
  const tol = /(\d{3})\s*g\s*\+\/-\s*(\d+)/.exec(w);
  if (tol) return [Number(tol[1]) - Number(tol[2]), Number(tol[1]) + Number(tol[2])];
  const one = /(\d{3})/.exec(w);
  return one ? [Number(one[1]), Number(one[1])] : [null, null];
}

function balanceOf(r: CatalogueRacket): [Balance | null, number | null] {
  const b = (r.balance ?? "").toLowerCase();
  const mm = /(\d{3})\s*mm/.exec(b);
  const cm = /(\d{2}(?:\.\d)?)\s*cm/.exec(b);
  const value = mm ? Number(mm[1]) : cm ? Math.round(Number(cm[1]) * 10) : null;
  if (b.includes("adjustable")) return [null, null];
  if (b.includes("medium-high")) return ["medium-high", value];
  if (b.includes("medium-low")) return ["medium-low", value];
  if (b.includes("high") || b.includes("head heavy")) return ["high", value];
  if (b.includes("low")) return ["low", value];
  if (b.includes("mid") || b.includes("medium") || b.includes("balanced") || b.includes("neutral")) return ["medium", value];
  if (value) {
    // Brand-listed balance point in mm from the butt.
    const level: Balance = value >= 268 ? "high" : value >= 263 ? "medium-high" : value >= 258 ? "medium" : value >= 253 ? "medium-low" : "low";
    return [level, value];
  }
  return [null, null];
}

function hardnessOf(r: CatalogueRacket): Hardness | null {
  const f = (r.feel ?? "").toLowerCase();
  if (!f) return null;
  if (f.includes("intermediate / hard")) return "medium-hard";
  if (f.includes("intermediate / soft")) return "medium-soft";
  if (f.includes("hard") || f.includes("firm")) return "hard";
  if (f.includes("soft")) return "soft";
  return "medium";
}

function finishOf(r: CatalogueRacket): SurfaceFinish | null {
  const s = (r.surface ?? "").toLowerCase();
  if (!s) return null;
  if (s.includes("no roughness")) return "smooth";
  if (s.includes("3d")) return "3d";
  if (s.includes("spin") || s.includes("gritt") || s.includes("rough")) return "rough";
  return null;
}

function levelsOf(r: CatalogueRacket): PlayerLevel[] {
  const l = (r.level ?? "").toLowerCase();
  if (l.includes("intermediate")) return ["intermediate", "advanced"];
  if (!l) return ["intermediate", "advanced"];
  return ["advanced"];
}

function stylesOf(r: CatalogueRacket, shape: RacketShape, balance: Balance | null): PlayingStyle[] {
  const g = (r.gameType ?? "").toLowerCase();
  const out = new Set<PlayingStyle>();
  if (g.includes("offensive")) out.add("power").add("aggressive");
  if (g.includes("versatile")) out.add("all-round");
  if (g.includes("tactical") || g.includes("control")) out.add("control");
  if (g.includes("defensive") || g.includes("counter")) out.add("defensive").add("control");
  if (!out.size) {
    // No game type listed: read it from the shape and balance.
    if (shape === "round") out.add("control").add("defensive");
    else if (shape === "diamond" || balance === "high") out.add("power").add("aggressive");
    else out.add("all-round");
  }
  return [...out];
}

const clamp = (v: number) => Math.round(Math.min(9.6, Math.max(4, v)) * 10) / 10;

/** Sample evaluation from the listed specs (same 1–10 scale as the rest of the catalogue). */
function evaluationOf(shape: RacketShape, balance: Balance | null, hardness: Hardness | null, weight: [number | null, number | null]) {
  const base = {
    diamond: { power: 8.4, control: 6.8, maneuverability: 6.6, forgiveness: 6.0, sweetSpot: 6.0, defense: 6.2, attack: 8.8 },
    teardrop: { power: 7.6, control: 7.6, maneuverability: 7.2, forgiveness: 7.0, sweetSpot: 7.0, defense: 7.2, attack: 7.8 },
    hybrid: { power: 7.2, control: 7.8, maneuverability: 7.4, forgiveness: 7.2, sweetSpot: 7.2, defense: 7.4, attack: 7.4 },
    round: { power: 6.6, control: 8.6, maneuverability: 7.8, forgiveness: 8.0, sweetSpot: 8.2, defense: 8.2, attack: 6.6 },
  }[shape];
  const e = { ...base };
  if (balance === "high" || balance === "medium-high") {
    e.power += 0.4;
    e.attack += 0.3;
    e.maneuverability -= 0.3;
  }
  if (balance === "low" || balance === "medium-low") {
    e.power -= 0.3;
    e.maneuverability += 0.3;
    e.control += 0.2;
  }
  if (hardness === "hard" || hardness === "medium-hard") {
    e.power += 0.3;
    e.control += 0.2;
    e.forgiveness -= 0.4;
  }
  if (hardness === "soft" || hardness === "medium-soft") {
    e.power -= 0.2;
    e.forgiveness += 0.4;
  }
  const avg = weight[0] && weight[1] ? (weight[0] + weight[1]) / 2 : null;
  if (avg && avg >= 369) {
    e.power += 0.2;
    e.maneuverability -= 0.3;
  }
  if (avg && avg <= 357) {
    e.power -= 0.2;
    e.maneuverability += 0.4;
  }
  return Object.fromEntries(Object.entries(e).map(([k, v]) => [k, clamp(v)])) as typeof base;
}

function whoFor(styles: PlayingStyle[], levels: PlayerLevel[]) {
  const level = levels.includes("intermediate") ? "Intermediate and advanced players" : "Advanced players";
  if (styles.includes("power"))
    return {
      bestFor: `${level} who attack and finish points overhead.`,
      recommendedFor: "Players who live at the net and generate their own racket speed.",
      notIdealFor: "Beginners, or anyone who mostly defends from the back glass.",
    };
  if (styles.includes("defensive"))
    return {
      bestFor: `${level} who defend first and counter-attack.`,
      recommendedFor: "Players who build points from the back and want a forgiving, controllable face.",
      notIdealFor: "Players who want maximum power on smashes.",
    };
  if (styles.includes("control") && !styles.includes("all-round"))
    return {
      bestFor: `${level} who place the ball and build points patiently.`,
      recommendedFor: "Tactical players who value direction and depth over raw pace.",
      notIdealFor: "Players looking for easy power on overheads.",
    };
  return {
    bestFor: `${level} who move between defence and attack.`,
    recommendedFor: "Players who want one racket that handles every situation on court.",
    notIdealFor: "Players after an all-out power or all-out control racket.",
  };
}

function specSentence(r: CatalogueRacket, brand: string): string {
  const bits = [
    r.shape && `a ${r.shape.toLowerCase()} head`,
    r.weight && `a listed weight of ${r.weight.replace("-", "–")}`,
    r.balance && !/adjustable/i.test(r.balance) && `balance ${r.balance.replace(/\s*\(as listed\)/, "")}`,
    r.balance && /adjustable/i.test(r.balance) && "an adjustable weight system",
    r.core && `a ${r.core} core`,
    r.surface && `a ${r.surface} face`,
    r.hittingAreaCm2 && `${r.hittingAreaCm2} cm² of hitting area`,
  ].filter(Boolean) as string[];
  if (!bits.length) return "";
  const list = bits.length > 1 ? `${bits.slice(0, -1).join(", ")} and ${bits[bits.length - 1]}` : bits[0];
  return ` ${brand} lists ${list}.`;
}

function convert(r: CatalogueRacket, existing: SeedRacket | undefined): SeedRacket {
  const brandName = BRAND_NAMES[r.brand];
  const shape = shapeOf(r);
  const weight = weightOf(r);
  const [balance, balanceMm] = balanceOf(r);
  const hardness = hardnessOf(r);
  const levels = levelsOf(r);
  const styles = stylesOf(r, shape, balance);
  const sampled = catalogueVisuals[r.slug];
  const list = (photos as Record<string, Array<{ url: string; view: "front" | "other" }>>)[r.slug] ?? [];
  const images = list.map((p, i) => ({
    url: p.url,
    alt: p.view === "front" ? `${brandName} ${r.name}, front view` : `${brandName} ${r.name}, product photo from another angle`,
    kind: (p.view === "front" ? "front" : i === 1 ? "angle" : "detail") as "front" | "angle" | "detail",
  }));
  const fullSpecs = !!(r.shape && r.weight);

  const specs: SeedRacket["specs"] = {
    shape,
    weightMinG: weight[0],
    weightMaxG: weight[1],
    balance,
    balanceMm,
    hardness,
    thicknessMm: r.profileMm ?? null,
    frameMaterial: null,
    faceMaterial: r.surface ?? null,
    coreMaterial: r.core ?? null,
    surfaceFinish: finishOf(r),
    // Only full specs from the brand's own site count as verified; retailer listings stay unverified.
    verification: fullSpecs && !r.specsFrom ? "verified" : "unverified",
  };
  const source = {
    specSourceNote: r.specsFrom ? PRO_SOURCE_NOTE_RETAILER(r.specsFrom) : CATALOGUE_SOURCE_NOTE,
    specSourceUrl: r.productUrl,
    imageSource: r.photosFrom
      ? `Retailer product photo (${r.photosFrom}), from the owner's catalogue`
      : `Brand product photo (${PHOTO_SITES[r.brand]}), from the owner's catalogue`,
  };
  const description = r.description + specSentence(r, brandName) + (r.caveat ? ` ${r.caveat}` : "");

  if (existing) {
    // Already on the site: keep its price, scores and review; take the brand's facts and photos.
    return {
      ...existing,
      name: r.name,
      collection: r.collection,
      year: r.year,
      shortDescription: r.description,
      description,
      specs: r.shape || r.weight ? specs : existing.specs,
      levels: r.level ? levels : existing.levels,
      images: images.length ? images : existing.images,
      ...(r.shape || r.weight ? source : { imageSource: source.imageSource }),
    };
  }

  return {
    slug: r.slug,
    brand: r.brand,
    name: r.name,
    collection: r.collection,
    year: r.year,
    isNew: (r.year ?? 0) >= 2026,
    shortDescription: r.description,
    description,
    specs,
    levels,
    styles,
    evaluation: { ...evaluationOf(shape, balance, hardness, weight), ...whoFor(styles, levels) },
    indicativePriceEur: null,
    visual: {
      face: sampled?.face ?? "#1d2026",
      frame: sampled?.frame ?? "#111317",
      accent: sampled?.accent ?? "#c9ced3",
      accent2: sampled?.accent2 ?? "#7d838c",
      grip: sampled?.grip ?? "#111214",
      pattern: "sweep",
      holes: "rings",
      bridge: false,
    },
    images: images.length ? images : undefined,
    ...source,
  };
}

/**
 * Rackets from the first sample catalogue whose real photos were found later
 * (RACKETS_WITHOUT_DESIGN.md): the shop each photo set came from.
 */
const SAMPLE_PHOTO_SITES: Record<string, string> = {
  "nox-ml10-pro-cup-rough-surface": "padelproshop.com",
  "bullpadel-vertex-05": "padelmarket.com",
  "bullpadel-neuron-02-2026": "padelkiwi.com",
  "head-extreme-pro-2025": "padelkiwi.com",
  "siux-electra-st4-pro": "padelkiwi.com",
  "starvie-triton-pro-2025": "padelmarket.com",
  "head-vibe-2026": "padelkiwi.com",
  "adidas-drive-black-2026": "padelkiwi.com",
  "head-evo-speed": "padelkiwi.com",
};

/** Real photos and photo-sampled colours for those sample rackets. */
function withSamplePhotos(r: SeedRacket): SeedRacket {
  const site = SAMPLE_PHOTO_SITES[r.slug];
  const list = (photos as Record<string, Array<{ url: string; view: "front" | "other" }>>)[r.slug];
  if (!site || !list?.length) return r;
  const brand = BRAND_NAMES[r.brand as CatalogueRacket["brand"]] ?? ({ starvie: "StarVie" } as Record<string, string>)[r.brand] ?? r.brand;
  const name = `${brand} ${r.name}`;
  const sampled = catalogueVisuals[r.slug];
  return {
    ...r,
    images: list.map((p, i) => ({
      url: p.url,
      alt: p.view === "front" ? `${name}, front view` : `${name}, product photo from another angle`,
      kind: (p.view === "front" ? "front" : i === 1 ? "angle" : "detail") as "front" | "angle" | "detail",
    })),
    imageSource: `Retailer product photo (${site})`,
    visual: sampled ? { ...r.visual, face: sampled.face, frame: sampled.frame, accent: sampled.accent, accent2: sampled.accent2, grip: sampled.grip } : r.visual,
  };
}

/** The base seed with the brand catalogue merged in (existing slugs updated, new ones appended). */
export function withBrandCatalogue(base: SeedRacket[]): SeedRacket[] {
  const catalogue = [...brandCatalogue, ...proRackets];
  const bySlug = new Map(base.map((r) => [r.slug, r]));
  const updated = base.map((r) => {
    const c = catalogue.find((x) => x.slug === r.slug);
    return c ? convert(c, r) : withSamplePhotos(r);
  });
  const added = catalogue.filter((c) => !bySlug.has(c.slug)).map((c) => convert(c, undefined));
  // Touring pros who play each racket.
  return [...updated, ...added].map((r) => (proPlayersBySlug.has(r.slug) ? { ...r, proPlayers: proPlayersBySlug.get(r.slug) } : r));
}
