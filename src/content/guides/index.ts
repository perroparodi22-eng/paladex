/**
 * Guides, as structured blocks (ready to move into a CMS or the database).
 * Blocks can embed interactive elements: a live 3D racket with a camera view
 * and overlays, a shape-overlay comparison, or a list of catalog rackets.
 */
import type { CameraView, OverlayKind, RacketShape } from "@/domain/types";

export type GuideBlock =
  | { type: "p"; text: string }
  | { type: "h2"; text: string }
  | { type: "h3"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "callout"; title: string; text: string }
  | { type: "racket3d"; slug: string; view?: CameraView; overlays?: OverlayKind[]; caption: string }
  | { type: "shapes"; a: RacketShape; b: RacketShape; caption: string }
  | { type: "rackets"; collection: string; limit: number; caption: string }
  | { type: "links"; items: Array<{ href: string; label: string }> };

export interface Guide {
  slug: string;
  title: string;
  description: string;
  minutes: number;
  updated: string;
  topic: "Choosing" | "Specs explained" | "3D";
  blocks: GuideBlock[];
}

export const GUIDES: Guide[] = [
  {
    slug: "how-to-choose-a-padel-racket",
    title: "How to choose a padel racket",
    description: "Level, shape, balance, weight and feel. The five decisions that narrow hundreds of rackets down to a handful, in plain language.",
    minutes: 7,
    updated: "2026-10-05",
    topic: "Choosing",
    blocks: [
      { type: "p", text: "Every padel racket looks similar from a distance: a perforated face, a solid frame and a short handle. Up close, a handful of design choices decide whether a racket helps your game or fights it. Make these five decisions in order and the shortlist almost writes itself." },
      { type: "h2", text: "1. Be honest about your level" },
      { type: "p", text: "Your level matters more than any spec. Beginners benefit from rackets that forgive off-centre hits and are easy to swing. Advanced players can exploit rackets that punish mistakes but reward clean, fast contact. A demanding racket will not make a developing player better. It makes every mishit worse." },
      { type: "ul", items: ["Beginner: round shape, soft or medium-soft core, lighter weight.", "Intermediate: round or teardrop, medium core, choose for your style.", "Advanced: any shape, often firmer cores and more head weight."] },
      { type: "h2", text: "2. Pick a shape for how you win points" },
      { type: "p", text: "Shape moves the sweet spot. Round rackets keep it low and central, close to your hand, which makes control easy. Diamonds push it up towards the tip for maximum leverage on smashes, at the cost of a smaller, less forgiving zone. Teardrops sit in between." },
      { type: "shapes", a: "round", b: "diamond", caption: "Round (solid) vs diamond (dashed), aligned at the butt cap. The diamond's width, and its sweet spot, sit much higher." },
      { type: "h2", text: "3. Decide how head-heavy you want it" },
      { type: "p", text: "Balance describes where the weight sits. A head-heavy (high balance) racket adds momentum to overheads but feels slower in fast exchanges and loads the shoulder and elbow more. A head-light racket is quick at the net and in defence." },
      { type: "h2", text: "4. Choose a weight you can swing for two hours" },
      { type: "p", text: "Most adult rackets weigh 355–375 g. Heavier rackets feel more stable and solid. Lighter ones are faster and less tiring. If you play long matches or have arm issues, err on the lighter side and add an overgrip or a weight strip later if you want more mass." },
      { type: "h2", text: "5. Match the core to your swing speed" },
      { type: "p", text: "Soft cores let the ball sink in and come off easily on slow shots, and they are kinder to the arm. Hard cores feel precise and powerful when you swing fast, but slow balls need more effort. Most players are best served by medium or medium-soft." },
      { type: "callout", title: "Shortcut", text: "The Racket Finder asks these questions for you and explains every match, including what you would give up." },
      { type: "links", items: [{ href: "/finder", label: "Take the Racket Finder" }, { href: "/collections/beginner-friendly", label: "Beginner-friendly rackets" }, { href: "/guides/round-vs-teardrop-vs-diamond", label: "Racket shapes explained" }] },
    ],
  },
  {
    slug: "round-vs-teardrop-vs-diamond",
    title: "Round vs teardrop vs diamond: racket shapes explained",
    description: "How the shape of the head moves the sweet spot and the weight, and which shape suits defenders, all-rounders and attackers.",
    minutes: 6,
    updated: "2026-10-05",
    topic: "Specs explained",
    blocks: [
      { type: "p", text: "The outline of a padel racket's head is the single most visible design decision, and it has real consequences. It decides where the sweet spot sits and, together with the frame, where the weight sits." },
      { type: "h2", text: "Round" },
      { type: "p", text: "Round heads are widest in the middle, so the sweet spot is low, central and large. Off-centre contact is forgiven, and the racket feels easy to place. Smashes get less free power because the hitting zone is closer to your hand. Round rackets suit beginners, defensive players and anyone who values control." },
      { type: "h2", text: "Teardrop" },
      { type: "p", text: "Teardrops widen a little above the middle and narrow towards the throat. The sweet spot rises slightly, giving more reach and punch while keeping much of a round racket's forgiveness. They suit all-round players who attack and defend within the same rally." },
      { type: "h2", text: "Diamond" },
      { type: "p", text: "Diamonds are widest near the tip and taper in straight lines to the throat. The sweet spot sits high and is more compact, and mass moves towards the head. That is ideal for smashes, bandejas and viboras, but less forgiving on blocks and lobs. Diamonds reward strong technique and fast swings." },
      { type: "shapes", a: "teardrop", b: "diamond", caption: "Teardrop (solid) and diamond (dashed) overlaid at the butt cap." },
      { type: "h2", text: "Hybrid" },
      { type: "p", text: "Some brands sell hybrid shapes between teardrop and diamond. They usually aim for most of a diamond's power with a slightly larger, more forgiving hitting zone." },
      { type: "racket3d", slug: "adidas-metalbone-3-4", view: "front", overlays: ["sweet-spot"], caption: "A diamond in 3D, with the illustrative sweet spot switched on. Drag to turn it." },
      { type: "links", items: [{ href: "/collections/round", label: "Round rackets" }, { href: "/collections/teardrop", label: "Teardrop rackets" }, { href: "/collections/diamond", label: "Diamond rackets" }] },
    ],
  },
  {
    slug: "soft-vs-hard-padel-rackets",
    title: "Soft vs hard padel rackets",
    description: "What core hardness changes in feel, power and comfort, and how to choose it for your swing speed and your arm.",
    minutes: 5,
    updated: "2026-10-05",
    topic: "Specs explained",
    blocks: [
      { type: "p", text: "Under the carbon or fibreglass skin, every padel racket has a foam or rubber core. How firm that core is changes how the ball leaves the face more than almost anything else." },
      { type: "h2", text: "Soft cores" },
      { type: "p", text: "A soft core lets the ball sink in a little before it springs back. Slow shots come off easily, there is more feel on touch shots, and less vibration reaches your arm. On very fast swings a soft core can feel less precise because it deforms more." },
      { type: "h2", text: "Hard cores" },
      { type: "p", text: "A hard core deforms less. Fast swings turn into precise, powerful shots, which is why many advanced attackers prefer it. Slow balls need more effort to push deep, and the racket feels firmer on the arm." },
      { type: "h2", text: "Medium: the sensible default" },
      { type: "p", text: "Medium and medium-soft cores suit most club players. If you are unsure, start there and move firmer only if you find the racket too lively at high speed." },
      { type: "callout", title: "Arm discomfort?", text: "Softer cores and head-light balance reduce the load on elbow and shoulder. The Racket Finder has an arm-comfort option that prioritises both." },
      { type: "links", items: [{ href: "/rackets?hardness=soft,medium-soft", label: "Softer rackets" }, { href: "/rackets?hardness=hard,medium-hard", label: "Firmer rackets" }] },
    ],
  },
  {
    slug: "what-is-racket-balance",
    title: "What does racket balance mean?",
    description: "Balance is where a racket would balance on your finger. Here's what high, medium and low balance do to your game, shown on a 3D model.",
    minutes: 5,
    updated: "2026-10-05",
    topic: "Specs explained",
    blocks: [
      { type: "p", text: "Balance is the point along the racket where it would balance on a finger, usually given in millimetres from the butt cap or as a category (low, medium, high). Two rackets of the same weight can feel completely different because of it." },
      { type: "racket3d", slug: "adidas-metalbone-3-4", view: "edge", overlays: ["balance", "weight-distribution"], caption: "Balance point and weight distribution on a head-heavy diamond. The marker is estimated from the published balance category." },
      { type: "h2", text: "High balance (head-heavy)" },
      { type: "p", text: "More of the mass sits towards the tip. The racket swings with more momentum, so smashes and volleys come off harder. The trade-off is reaction speed: the head takes longer to bring around, and it loads the shoulder and elbow more." },
      { type: "h2", text: "Low balance (head-light)" },
      { type: "p", text: "Mass sits closer to your hand. The racket feels quick and easy to position, which helps in fast exchanges at the net and when defending. You give up some free power on overheads." },
      { type: "h2", text: "Medium balance" },
      { type: "p", text: "An even balance is a neutral starting point that suits all-round players. Many modern rackets add screw-in or slot-in weights so you can shift the balance yourself." },
      { type: "links", items: [{ href: "/rackets?balance=high,medium-high", label: "Head-heavy rackets" }, { href: "/rackets?balance=low,medium-low", label: "Head-light rackets" }] },
    ],
  },
  {
    slug: "how-much-should-a-padel-racket-weigh",
    title: "How much should a padel racket weigh?",
    description: "Typical padel racket weights, what extra grams change, and how to pick a weight you can swing for a whole match.",
    minutes: 4,
    updated: "2026-10-05",
    topic: "Choosing",
    blocks: [
      { type: "p", text: "Most adult padel rackets weigh between 355 and 375 grams. Within that narrow range, small differences are surprisingly noticeable, especially together with balance." },
      { type: "ul", items: ["Under ~355 g: quick and easy on the arm, popular with beginners, juniors and players with arm issues.", "355–368 g: the middle ground most adults handle comfortably.", "Over ~368 g: more stability and punch, more tiring over a long match."] },
      { type: "p", text: "Weight and balance work together. A light racket with a high balance can feel heavier in the hand than a heavier, head-light one. If possible, judge both together." },
      { type: "callout", title: "Small adjustments", text: "An overgrip adds a few grams near the handle and lowers the balance slightly. Weight strips at the head do the opposite. Some rackets include adjustable weight systems." },
      { type: "links", items: [{ href: "/rackets?weight=-358", label: "Lighter rackets" }, { href: "/finder", label: "Get a recommendation" }] },
    ],
  },
  {
    slug: "how-to-inspect-a-padel-racket-in-3d",
    title: "How to inspect a padel racket in 3D",
    description: "A quick tour of the 3D viewer: views, hotspots, overlays and what to look for in a racket's profile.",
    minutes: 4,
    updated: "2026-10-05",
    topic: "3D",
    blocks: [
      { type: "p", text: "Photos show a racket from the front. In 3D you can check the things that decide how it plays. Here is what to look at, view by view." },
      { type: "racket3d", slug: "adidas-metalbone-3-4", view: "hero", caption: "Try it: drag to rotate, pinch or scroll to zoom, or use the view buttons." },
      { type: "h3", text: "Front view: shape and sweet spot" },
      { type: "p", text: "Look at where the head is widest. Turn on the sweet-spot overlay to see the illustrative hitting zone for that shape." },
      { type: "h3", text: "Edge view: profile and balance" },
      { type: "p", text: "From the side you can judge the frame's thickness (38 mm is the regulation maximum) and, with the balance overlay, where the mass sits." },
      { type: "h3", text: "Grip view: handle and throat" },
      { type: "p", text: "Check how the throat joins the handle. A wide, stiff junction adds stability, and a slimmer one feels quicker in the hand." },
      { type: "h3", text: "Hotspots and labels" },
      { type: "p", text: "Numbered hotspots explain each part. Every explanation is labelled as manufacturer data, a platform evaluation or an illustration, so you always know what is measured and what is interpretation." },
      { type: "links", items: [{ href: "/showroom", label: "Open the 3D showroom" }, { href: "/legal/3d-assets", label: "About our 3D models" }] },
    ],
  },
  {
    slug: "best-padel-rackets-for-beginners",
    title: "Best padel rackets for beginners",
    description: "What makes a racket beginner-friendly, and the forgiving, comfortable rackets in our database that fit the brief.",
    minutes: 4,
    updated: "2026-10-05",
    topic: "Choosing",
    blocks: [
      { type: "p", text: "A good first racket does three things: it forgives off-centre hits, it is comfortable on the arm, and it is light enough to swing for a whole session. Price matters less than those three." },
      { type: "ul", items: ["Round shape for a large, central sweet spot.", "Soft or medium-soft core for easy ball exit and comfort.", "Around 345–365 g, with low or medium balance."] },
      { type: "rackets", collection: "beginner-friendly", limit: 4, caption: "Rackets our evaluation tags as beginner-friendly (sample data)." },
      { type: "callout", title: "Upgrade later", text: "Once your technique is consistent (usually after a few months of regular play) a teardrop or a firmer core can add power without losing much control." },
      { type: "links", items: [{ href: "/collections/beginner-friendly", label: "All beginner-friendly rackets" }, { href: "/finder?level=beginner", label: "Racket Finder for beginners" }] },
    ],
  },
];

export function getGuide(slug: string): Guide | undefined {
  return GUIDES.find((g) => g.slug === slug);
}
