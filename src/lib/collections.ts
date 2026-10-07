/**
 * Curated collections: SEO-friendly landing pages backed by catalog filters.
 */
import type { CatalogFilters, SortKey } from "@/lib/catalog/filters";

export interface Collection {
  slug: string;
  title: string;
  /** Short label for chips and navigation. */
  label: string;
  description: string;
  intro: string;
  filter: Partial<CatalogFilters>;
  sort?: SortKey;
}

export const COLLECTIONS: Collection[] = [
  {
    slug: "power",
    label: "Power",
    title: "Power padel rackets",
    description: "Padel rackets built for smashes and fast volleys, compared in 3D: diamond shapes, high balance and firm cores.",
    intro: "Power rackets put weight high in the head and usually use firmer cores. They hit hardest overhead and ask for good technique. Turn them in 3D to see how far up the widest point sits.",
    filter: { styles: ["power"] },
    sort: "power",
  },
  {
    slug: "control",
    label: "Control",
    title: "Control padel rackets",
    description: "Padel rackets for precise placement: round and teardrop shapes, lower balance and forgiving sweet spots.",
    intro: "Control rackets keep the sweet spot low and central and the weight closer to your hand, so the ball goes where you aim. In the sweet-spot overlay their zone sits lower and wider.",
    filter: { styles: ["control"] },
    sort: "control",
  },
  {
    slug: "all-round",
    label: "All-round",
    title: "All-round padel rackets",
    description: "Versatile padel rackets that attack and defend: mostly teardrop shapes with neutral balance.",
    intro: "All-round rackets suit players who switch between defence and attack within a rally. Most are teardrops with an even balance.",
    filter: { styles: ["all-round"] },
    sort: "rating",
  },
  {
    slug: "defensive",
    label: "Defensive",
    title: "Defensive padel rackets",
    description: "Rackets that make defending from the back glass easier: forgiving, quick and controllable.",
    intro: "Defensive players need a racket that is quick to react and forgives off-centre contact on lobs and blocks.",
    filter: { styles: ["defensive"] },
    sort: "control",
  },
  {
    slug: "aggressive",
    label: "Aggressive",
    title: "Aggressive padel rackets",
    description: "Rackets for players who take the net early and finish points overhead.",
    intro: "Aggressive rackets reward fast swings and confident technique, with head-heavy balance and diamond or hybrid shapes.",
    filter: { styles: ["aggressive"] },
    sort: "power",
  },
  {
    slug: "beginner-friendly",
    label: "Beginner-friendly",
    title: "Best padel rackets for beginners",
    description: "Forgiving, comfortable padel rackets for new players: round shapes, soft cores and big sweet spots.",
    intro: "Beginners progress fastest with a forgiving racket: a round head, a soft core and a weight that does not tire the arm. Every racket here is tagged for beginners by our evaluation.",
    filter: { levels: ["beginner"] },
    sort: "rating",
  },
  {
    slug: "intermediate",
    label: "Intermediate",
    title: "Padel rackets for intermediate players",
    description: "Rackets for regular players with consistent technique who want a step up in power or precision.",
    intro: "Intermediate players can start choosing for their style: more control from a round, more variety from a teardrop.",
    filter: { levels: ["intermediate"] },
    sort: "rating",
  },
  {
    slug: "advanced",
    label: "Advanced",
    title: "Padel rackets for advanced players",
    description: "Demanding, high-performance padel rackets for strong technique and fast swings.",
    intro: "Advanced rackets trade forgiveness for performance. Compare their balance and shape in 3D before you buy.",
    filter: { levels: ["advanced"] },
    sort: "rating",
  },
  {
    slug: "round",
    label: "Round",
    title: "Round padel rackets",
    description: "Round-shaped padel rackets: the most forgiving and controllable shape, explained in 3D.",
    intro: "Round heads centre the sweet spot close to your hand. They are the easiest shape to control.",
    filter: { shapes: ["round"] },
  },
  {
    slug: "teardrop",
    label: "Teardrop",
    title: "Teardrop padel rackets",
    description: "Teardrop-shaped padel rackets: the balanced middle ground between control and power.",
    intro: "Teardrops are widest a little above the middle, so you get extra reach and punch without losing much forgiveness.",
    filter: { shapes: ["teardrop", "hybrid"] },
  },
  {
    slug: "diamond",
    label: "Diamond",
    title: "Diamond padel rackets",
    description: "Diamond-shaped padel rackets for maximum overhead power, with the high sweet spot shown in 3D.",
    intro: "Diamonds are widest near the tip. That gives maximum leverage overhead and a smaller, higher sweet spot.",
    filter: { shapes: ["diamond"] },
    sort: "power",
  },
  {
    slug: "under-200",
    label: "Under €200",
    title: "Padel rackets under €200",
    description: "Good-value padel rackets under €200, compared on shape, balance and platform scores.",
    intro: "You do not need a flagship to play well. These rackets start under €200 (sample prices while the catalog is in development).",
    filter: { priceMax: 200 },
    sort: "value",
  },
];

export function getCollection(slug: string): Collection | undefined {
  return COLLECTIONS.find((c) => c.slug === slug);
}

export const STYLE_COLLECTIONS = ["power", "control", "all-round", "defensive", "aggressive", "beginner-friendly", "intermediate", "advanced"];
