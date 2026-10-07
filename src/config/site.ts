/**
 * Site-wide configuration. Change the brand name here and everything follows:
 * header, footer, metadata, structured data, OG images.
 */
export const siteConfig = {
  name: "Paladex",
  tagline: "The 3D padel racket database",
  description:
    "Explore padel rackets in interactive 3D, brand by brand, and find the one that fits your game.",
  locale: "en",
  currency: "EUR",
  market: "EU",
  contactEmail: "hello@paladex.example",
  /** Methodology version shown next to every platform score. */
  scoreMethodology: "v0.1 (sample)",
  tagline2: "Rackets 3D Showroom",
  nav: [
    { href: "/rackets", label: "Rackets & brands", note: "Pick a brand, then a racket" },
    { href: "/showroom", label: "3D Showroom", note: "Every racket on one stage" },
    { href: "/finder", label: "Find my racket", note: "Eight questions, your best matches" },
    { href: "/pros", label: "Pro players", note: "The rackets the top players use" },
    { href: "/guides", label: "Guides", note: "What the specs mean on court" },
  ],
  footer: [
    {
      title: "Explore",
      links: [
        { href: "/rackets", label: "Rackets & brands" },
        { href: "/showroom", label: "3D Showroom" },
        { href: "/finder", label: "Find my racket" },
        { href: "/pros", label: "Pro players" },
      ],
    },
    {
      title: "Collections",
      links: [
        { href: "/collections/beginner-friendly", label: "Beginner-friendly" },
        { href: "/collections/power", label: "Power rackets" },
        { href: "/collections/control", label: "Control rackets" },
        { href: "/collections/all-round", label: "All-round rackets" },
      ],
    },
    {
      title: "Learn",
      links: [
        { href: "/guides", label: "Guides" },
        { href: "/guides/how-to-choose-a-padel-racket", label: "How to choose a racket" },
        { href: "/guides/round-vs-teardrop-vs-diamond", label: "Racket shapes" },
        { href: "/guides/what-is-racket-balance", label: "What balance means" },
      ],
    },
    {
      title: "Paladex",
      links: [
        { href: "/about", label: "About" },
        { href: "/contact", label: "Contact" },
        { href: "/legal/affiliate-disclosure", label: "Affiliate disclosure" },
        { href: "/legal/3d-assets", label: "3D asset disclaimer" },
        { href: "/legal/privacy", label: "Privacy" },
        { href: "/legal/cookies", label: "Cookies" },
        { href: "/legal/terms", label: "Terms" },
      ],
    },
  ],
} as const;

export function siteUrl(path = "/"): string {
  const base = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/+$/, "");
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

export function indexingAllowed(): boolean {
  return process.env.NEXT_PUBLIC_ALLOW_INDEXING === "true";
}
