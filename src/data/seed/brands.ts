/**
 * Seed brands. Descriptions are Paladex's own neutral summaries; verify any
 * factual detail (founding year, country) before launch.
 *
 * Logos (public/images/brands, built by scripts/build-brand-logos.ts) come
 * from each brand's own website, or Wikimedia Commons for adidas and Wilson.
 * They identify the brand only. Brands without a logo file show their name.
 */
export interface SeedBrand {
  slug: string;
  name: string;
  country: string;
  websiteUrl: string;
  description: string;
  logoUrl?: string | null;
}

export const seedBrands: SeedBrand[] = [
  {
    slug: "adidas",
    name: "adidas",
    country: "Germany",
    websiteUrl: "https://www.adidas.com",
    description:
      "The German sportswear group's padel line spans entry-level rounds to the Metalbone family of diamond-shaped power rackets, many with adjustable weight systems.",
  },
  {
    slug: "bullpadel",
    name: "Bullpadel",
    country: "Spain",
    websiteUrl: "https://www.bullpadel.com",
    description:
      "One of padel's best-known Spanish brands. Its Proline (Vertex, Hack, Neuron) runs from all-out power diamonds to control-oriented hybrids.",
  },
  {
    slug: "nox",
    name: "Nox",
    country: "Spain",
    websiteUrl: "https://noxsport.com",
    description:
      "A Spanish padel-only brand known for the long-running ML10 control round and the AT10 teardrop line with interchangeable counterweights.",
  },
  {
    slug: "babolat",
    name: "Babolat",
    country: "France",
    websiteUrl: "https://www.babolat.com",
    description:
      "The French racket-sports maker's Viper family covers power diamonds and lighter, more manoeuvrable variants.",
  },
  {
    slug: "head",
    name: "Head",
    country: "Austria",
    websiteUrl: "https://www.head.com",
    description:
      "Head builds padel rackets from beginner rounds to the Speed, Extreme and Delta performance lines, often with foam cores and graphene-reinforced frames.",
  },
  {
    slug: "wilson",
    name: "Wilson",
    country: "United States",
    websiteUrl: "https://www.wilson.com",
    description: "Wilson's padel range is anchored by the Bela line, a heavier frame designed for stability and power.",
  },
  {
    slug: "siux",
    name: "Siux",
    country: "Spain",
    websiteUrl: "https://siuxpadel.com",
    description: "A Spanish brand with an attacking identity. The Electra series balances power with a hybrid shape.",
  },
  {
    slug: "starvie",
    name: "StarVie",
    country: "Spain",
    websiteUrl: "https://www.starvie.com",
    description: "A Spanish manufacturer known for textured carbon faces and offensive teardrop models such as the Triton.",
  },
  {
    slug: "black-crown",
    name: "Black Crown",
    country: "Spain",
    websiteUrl: "https://www.blackcrown.es",
    description: "Black Crown's Piton line is a popular round, soft-feel choice for players who value comfort and control.",
  },
  {
    slug: "lok",
    name: "Lok",
    country: "Spain",
    websiteUrl: "https://www.lokpadel.com",
    description: "A Spanish brand whose Maxx line carries Mike Yanguas's signature diamond rackets.",
  },
  {
    slug: "kuikma",
    name: "Kuikma",
    country: "France",
    websiteUrl: "https://www.decathlon.com",
    description: "Decathlon's padel brand, ranging from beginner rackets to signature models for touring pros.",
  },
  {
    slug: "drop-shot",
    name: "Drop Shot",
    country: "Spain",
    websiteUrl: "https://www.dropshot.es",
    description: "A long-standing Spanish padel brand. Its Axion line is built for attacking players.",
  },
  {
    slug: "tactical",
    name: "Tactical",
    country: "Spain",
    websiteUrl: "https://tacticalpadel.com",
    description: "A young padel brand whose El Jefe line is made with Lucas Bergamini.",
  },
];

const LOGOS = new Set(["adidas", "babolat", "black-crown", "bullpadel", "head", "nox", "siux", "starvie", "tactical", "wilson"]);
for (const b of seedBrands) b.logoUrl = LOGOS.has(b.slug) ? `/images/brands/${b.slug}.png` : null;
