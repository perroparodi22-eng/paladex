/**
 * Research round-up for every racket (checked 7 Oct 2026).
 *
 * For each racket we read the published reviews (Padelful, PadelSpeak, Padel
 * Verdict, padel.fyi, Padelshop's measured data, retailer staff tests and buyer
 * reviews) and the retailer spec listings, then:
 *
 * - `fill`: spec values the catalogue left empty, taken from those listings.
 *   They only fill gaps; a brand-listed value is never overwritten.
 * - `set`: the few cases where the catalogue holds a finish name instead of
 *   the material (e.g. Nox "Dual Spin"); the material is added in front.
 * - `roundup`: what the sources say, summarised in our own words with every
 *   source linked. `ourRead` is Paladex's take drawn from those sources; we
 *   have not play-tested the rackets, and the UI says so.
 *
 * Where sources disagreed (shape, face material, balance) the brand listing
 * was kept and nothing was filled.
 */
import type { ReviewRoundup } from "@/domain/types";
import type { SeedRacket } from "./rackets";

type Specs = SeedRacket["specs"];
type SpecPatch = Partial<Omit<Specs, "verification" | "shape">>;

export interface RacketResearch {
  fill?: SpecPatch;
  set?: SpecPatch;
  roundup: Omit<ReviewRoundup, "checkedOn">;
}

export const RESEARCH_CHECKED_ON = "2026-10-07";

const S = {
  padelful: (path: string) => ({ name: "Padelful", url: `https://www.padelful.com/en/rackets/${path}` }),
  padelshop: (path: string) => ({ name: "Padelshop", url: `https://padelshop.com/${path}` }),
  padelkiwi: (path: string) => ({ name: "Padel Kiwi", url: `https://www.padelkiwi.com/en/products/${path}` }),
  tennisnuts: (path: string) => ({ name: "Tennis Nuts", url: `https://www.tennisnuts.com/${path}` }),
  tw: (path: string) => ({ name: "Tennis Warehouse", url: `https://www.tennis-warehouse.com/${path}` }),
  twe: (path: string) => ({ name: "Tennis Warehouse Europe", url: `https://www.tenniswarehouse-europe.com/${path}` }),
  padelmarket: (path: string) => ({ name: "Padel Market", url: `https://padelmarket.com/en/${path}` }),
  padelproshop: (path: string) => ({ name: "Padel Pro Shop", url: `https://padelproshop.com/en/products/${path}` }),
};

/** The 2027 Bullpadel line: carbon-tube frame and 3D Grain face texture, per Padelshop's listings. */
const BULLPADEL_27_FILL: SpecPatch = { frameMaterial: "Carbon tube" };
const GRAIN: SpecPatch = { surfaceFinish: "3d" };

export const racketResearch: Record<string, RacketResearch> = {
  /* ------------------------------------------------------------ original catalogue */
  "adidas-metalbone-3-4": {
    roundup: {
      status: "reviewed",
      summary:
        "Reviewers treat the 3.4 as a finisher's racket. The 2025 update adds a longer handle, a faceted frame and a stiffening groove in the rail, and testers say overheads and attacking volleys come off with real sting and a direct, crisp response.",
      liked: ["Punch on smashes and attacking volleys", "Direct, responsive feel", "Longer handle adds leverage on overheads"],
      watchOuts: ["Off-centre hits feel harsh", "Less manoeuvrable than a teardrop", "More shock to the arm than softer control rackets"],
      suits: "Experienced attacking players, often on the left side, who finish points overhead.",
      ourRead:
        "A specialist. If you mostly finish points it rewards you; if you spend long rallies defending from the glass, a softer teardrop will be kinder to your arm and your error count.",
      facts: [
        { label: "Handle", value: "Extended Power Extra Grip" },
        { label: "Frame", value: "Low Poly faceted design with Power Groove rail" },
        { label: "Weights", value: "Adjustable screws in the frame" },
      ],
      sources: [S.padelful("adidas-metalbone-3-4-2025-ale-galan")],
    },
  },
  "bullpadel-vertex-05": {
    roundup: {
      status: "reviewed",
      summary:
        "Juan Tello's racket. PadelSpeak scores it 8.5/10 and finds it stiffer and more head-heavy than the 2025 Vertex 04. Overheads are explosive, contact is crisp with plenty of feedback, and it is steady at the net, yet it moves more easily than the 04.",
      liked: ["Explosive smashes and finishing shots", "Crisp feel with lots of feedback", "Stable in fast net exchanges", "Easier to move than the Vertex 04"],
      watchOuts: ["Limited sweet spot that punishes off-centre hits", "Average comfort; avoid with tennis elbow", "Not built for defensive play"],
      suits: "Attacking left-side players at level 5 and above.",
      ourRead:
        "One of the most committed attacking rackets here. Buy it for the smash, and only if your contact is consistent; it gives very little back on mishits.",
      facts: [{ label: "PadelSpeak score", value: "8.5 / 10" }],
      sources: [
        { name: "PadelSpeak", url: "https://padelspeak.com/en/?p=52124" },
        S.padelful("bullpadel-vertex-05-2026-juan-tello"),
      ],
    },
  },
  "nox-at10-luxury-genius-18k-alum": {
    fill: { frameMaterial: "100% carbon fibre", surfaceFinish: "rough" },
    set: { faceMaterial: "Carbon fibre 18K Alum, Dual Spin finish" },
    roundup: {
      status: "reviewed",
      summary:
        "Agustín Tapia's 2026 racket on a new mould. Buyers rate it highly for attack and comfort together. The aluminised 18K face gives a solid, even feel that stays consistent as the temperature changes, and the sweet spot is wider than its power suggests.",
      liked: ["Strong in attack without feeling harsh", "Wide sweet spot for its class", "Weight and balance adjustable with 2 g and 4 g pieces", "Rubber strips in the frame damp vibration"],
      watchOuts: ["Professional-level racket: asks for good technique", "Premium price"],
      suits: "Advanced players who want an attacking teardrop they can tune.",
      ourRead:
        "The most rounded of the AT10 family: Tapia's power with a teardrop's margin. The counterweights make it worth a look if you like to fine-tune your racket.",
      facts: [
        { label: "Weight system", value: "Weight Balance, 2 g and 4 g counterweights" },
        { label: "Grip", value: "Extended 30 mm handle" },
        { label: "Damping", value: "Pulse rubber strips" },
        { label: "Paint", value: "Photochromic, changes tone in sunlight" },
      ],
      sources: [S.padelkiwi("nox-at10-luxury-genius-18k-alum-2026-agustin-tapia"), { name: "Padelgids", url: "https://padelgids.nl/padelgear/padel-rackets/nox-at10-genius-18k-alum-2026/" }],
    },
  },
  "nox-ml10-pro-cup-rough-surface": {
    fill: { balanceMm: 260 },
    roundup: {
      status: "reviewed",
      summary:
        "A long-running classic. Reviewers and buyers describe a stable, precise round racket with a big sweet spot and a comfortable feel. The silica-sand face adds bite for spin.",
      liked: ["Control and shot precision", "Large, forgiving sweet spot", "Comfortable on the arm", "Rough face helps spin"],
      watchOuts: ["Not much free power on smashes"],
      suits: "Control players from intermediate upwards, and anyone moving up from a beginner racket.",
      ourRead:
        "One of the safest buys in padel: it helps more than it demands. Power players will want more, but for building points it is hard to fault at its price.",
      facts: [{ label: "Balance point", value: "about 260 mm (even)" }],
      sources: [S.padelful("nox-ml10-pro-cup-rough-surface-edition-2025"), S.tennisnuts("nox-ml10-pro-cup-rough-surface-miguel-lamperti-padel-racket-2025-1745695.html")],
    },
  },
  "babolat-technical-viper-2026": {
    fill: { balanceMm: 270, hardness: "hard" },
    roundup: {
      status: "reviewed",
      summary:
        "Padel Verdict calls it a hard-edged diamond. Clean contact brings explosive pace, heavy spin and authority at the net, but the sweet spot is not generous and off-centre shots lose quality quickly.",
      liked: ["Explosive pace on clean contact", "Heavy spin", "Authority at the net"],
      watchOuts: ["Small sweet spot", "Head-heavy setup tires the arm over long matches", "Not for defensive players"],
      suits: "Advanced, competitive attackers with sound technique.",
      ourRead:
        "Babolat's most uncompromising Viper. Only choose it if you already hit the ball cleanly and play to finish; the Technical Viper Soft or the Veron give more back.",
      facts: [{ label: "Balance point", value: "about 270 mm" }],
      sources: [{ name: "Padel Verdict", url: "https://padelverdict.com/?p=913" }, S.tennisnuts("babolat-technical-viper-3-0-padel-racket-2026-1755265.html")],
    },
  },
  "bullpadel-neuron-02-2026": {
    roundup: {
      status: "reviewed",
      summary:
        "Fede Chingotto's racket. Reviewers praise very precise placement, a big sweet spot in defence and clean, stable net exchanges. The frame is triangulated to stop it twisting.",
      liked: ["Very precise placement", "Big sweet spot when defending", "Stable at the net", "Adjustable weight"],
      watchOuts: ["Little free ball exit", "Limited finishing power on smashes"],
      suits: "Advanced players who build points and defend well.",
      ourRead:
        "A thinking player's racket. You trade some smash power for consistency, and for most club players that is a good trade.",
      facts: [
        { label: "Hitting area", value: "525 cm²" },
        { label: "Frame", value: "PrismLock triangulated structure" },
        { label: "Weight system", value: "Custom Weight" },
      ],
      sources: [S.padelful("bullpadel-neuron-02-2026-fede-chingotto"), S.padelkiwi("pala-bullpadel-neuron-02-2026-pala-fede-chingotto-padel-racket")],
    },
  },
  "head-speed-pro-2025": {
    fill: { frameMaterial: "Carbon fibre", hardness: "medium" },
    roundup: {
      status: "reviewed",
      summary:
        "Padelful scores it 8.4 for power, 8.6 for control, 8.7 for manoeuvrability and 8.4 for sweet spot. Reviewers like its generous sweet spot and a medium feel that is comfortable but still gives feedback.",
      liked: ["Generous sweet spot", "Comfortable medium feel with good feedback", "Equally at home attacking and defending"],
      watchOuts: ["The high 270 mm balance needs technique and strength"],
      suits: "Advanced all-court players who want a pro feel without a harsh diamond.",
      ourRead:
        "A strong all-rounder. Unless you want a pure specialist it covers most of what a club player needs, and the damping is a bonus.",
      facts: [
        { label: "Padelful scores", value: "Power 8.4 · Control 8.6 · Sweet spot 8.4" },
        { label: "Damping", value: "Damp Plus and Soft Butt Cap 2.0" },
      ],
      sources: [S.padelful("head-speed-pro-2025"), S.padelshop("blogs/padel-tips/head-speed-pro-2025-review")],
    },
  },
  "head-extreme-pro-2025": {
    roundup: {
      status: "reviewed",
      summary:
        "The heaviest and most powerful Extreme. Listings and reviews describe explosive power and high stability. A unidirectional carbon layer and a new hole pattern aim to widen the sweet spot.",
      liked: ["Explosive power", "Very stable at impact", "Rough 3D face for spin"],
      watchOuts: ["Takes effort to move quickly", "Needs strength and solid technique"],
      suits: "Advanced, attack-first players who want to finish points fast.",
      ourRead:
        "A heavyweight's diamond. Choose it for raw power; if you value quick hands at the net, the Extreme Motion is the friendlier sibling.",
      facts: [{ label: "Tech", value: "Auxetic 2.0, UD carbon layer, new hole pattern" }],
      sources: [{ name: "HEAD", url: "https://www.head.com/en/product/extreme-pro-2025-223125" }, { name: "Racketpedia", url: "https://www.racketpedia.com/en-GB/padel-racket/head-extreme-pro-2025" }],
    },
  },
  "wilson-bela-pro-v3": {
    roundup: {
      status: "reviewed",
      summary:
        "Belasteguín's racket pairs a 24K carbon face with a Power Foam core. Retail reviewers describe power and precision together, but say the stiff face and high balance need well-developed technique.",
      liked: ["Power with precision", "Solid, rigid feel", "Textured face for spin"],
      watchOuts: ["Demanding for intermediate players", "Stiff 24K face is less forgiving"],
      suits: "Advanced and professional players.",
      ourRead:
        "A refined, demanding racket. Intermediate players will get more from a softer, lower-balance model.",
      facts: [{ label: "Texture", value: "Spin² face texture" }],
      sources: [S.padelkiwi("padel-racket-wilson-bela-pro-v3"), S.padelshop("products/wilson-bela-pro-v3-2025-padel-racket")],
    },
  },
  "bullpadel-hack-04-2026": {
    fill: { thicknessMm: 38 },
    set: { faceMaterial: "TriCarbon 18K, 3D Grain finish" },
    roundup: {
      status: "reviewed",
      summary:
        "Paquito Navarro's Hack. Reviewers describe an attack-first racket with a hard edge and a crisp, premium response. It is explosive and stable when you accelerate, and far less friendly when your timing is late.",
      liked: ["Explosive on overheads", "Crisp, premium response", "Stable when accelerating"],
      watchOuts: ["Unforgiving with late or lazy timing", "Asks for clean technique"],
      suits: "Advanced attackers who hit with intent.",
      ourRead:
        "It gives a lot and asks a lot. If the Hack's power appeals but the harshness worries you, the Hack 04 Comfort is the version to try.",
      facts: [
        { label: "Hitting area", value: "522 cm²" },
        { label: "Weight system", value: "CustomWeight: up to four 3 g weights, about 1 cm of balance" },
      ],
      sources: [S.padelful("bullpadel-hack-04-2026-paquito-navarro"), S.padelkiwi("pala-bullpadel-hack-04-2026-pala-paquito-navarro-padel-racket")],
    },
  },
  "siux-electra-st4-pro": {
    roundup: {
      status: "reviewed",
      summary:
        "Franco Stupaczuk's racket. Reviews find it powerful without losing agility in fast exchanges. The hard EVA core responds quickly, and the medium-high balance keeps it stable.",
      liked: ["Power without losing speed of hand", "Quick, direct response", "Stable on every shot"],
      watchOuts: ["Hard core is less comfortable on slow balls"],
      suits: "Advanced, aggressive players who still want control.",
      ourRead:
        "A fast-handed attacking racket. It is a good middle ground if a diamond feels too clumsy but a round racket feels too tame.",
      facts: [],
      sources: [S.padelful("siux-electra-st4-pro-stupa-2025"), S.padelshop("nl/blogs/padel-tips/siux-electra-st4-pro-2025-review")],
    },
  },
  "starvie-triton-pro-2025": {
    roundup: {
      status: "reviewed",
      summary:
        "Expert reviewers on padel.fyi (scored on the 2024 Triton Pro, 7.5/10) call it one of the most powerful rackets on the market, with a lovely feel on the ball. The 2025 update raises the balance slightly, to about 27 cm.",
      liked: ["Huge power", "Great feel on the ball"],
      watchOuts: ["Smallest sweet spot of the Triton range; dead off-centre", "Low ball output: you must swing through", "Physically demanding"],
      suits: "Strong, technically sound advanced players.",
      ourRead:
        "For the player who wants maximum hitting power and has the physique for it. Most club players will be happier with a more forgiving Triton.",
      facts: [{ label: "padel.fyi score (2024 version)", value: "7.5 / 10 from 4 experts" }],
      sources: [S.padelful("star-vie-triton-pro-2025"), { name: "padel.fyi", url: "https://www.padel.fyi/rackets/triton-pro-2024/" }],
    },
  },
  "black-crown-piton-5": {
    roundup: {
      status: "reviewed",
      summary:
        "A control-first round racket. Retailer reviews highlight its elasticity, a big contact zone and a soft Black EVA core that works from any position, with an 80% carbon build.",
      liked: ["Control and placement", "Soft, elastic feel", "Big contact area", "Easy on the joints"],
      watchOuts: ["Modest power on smashes"],
      suits: "Control players, and improvers who want to progress without a harsh racket.",
      ourRead:
        "A comfortable, honest control racket. It is a sensible choice if you have arm trouble or are still building technique.",
      facts: [{ label: "Construction", value: "80% carbon fibre in frame and faces" }],
      sources: [{ name: "Padel Nuestro", url: "https://www.padelnuestro.com/uk/black-crown-piton-5-0-8294-p" }],
    },
  },
  "head-vibe-2026": {
    roundup: {
      status: "reviewed",
      summary:
        "Retail reviews describe a forgiving, comfortable racket for starters. The all-fibreglass build gives a soft, cushioned response, and the large sweet spot makes centring the ball easy.",
      liked: ["Very forgiving", "Comfortable, soft response", "Easy power", "Light and easy to handle"],
      watchOuts: ["Outgrown once you need precision at speed"],
      suits: "Beginners and early-intermediate club players.",
      ourRead: "A good first racket: it helps on every shot and never punishes you. Expect to upgrade after a season or two of regular play.",
      facts: [{ label: "Build", value: "Fibreglass frame and faces, Power Foam core" }],
      sources: [S.tennisnuts("shop/padel/rackets/head/head-recreational-padel-rackets/head-vibe-padel-racket-2026-green-orange-1755130.html"), S.padelmarket("products/head-vibe-green-orange-2026-racket")],
    },
  },
  "adidas-drive-black-2026": {
    fill: { frameMaterial: "Fibreglass" },
    roundup: {
      status: "reviewed",
      summary:
        "A control-oriented racket for beginners and occasional players. Reviewers find it comfortable, light and forgiving, with good ball output from the soft EVA core.",
      liked: ["Comfortable and forgiving", "Easy ball output", "Reinforced against twisting"],
      watchOuts: ["Little raw power; smashes take effort"],
      suits: "Beginners up to intermediate players.",
      ourRead: "A dependable starter racket from a big brand. Spend more only once you know your style.",
      facts: [{ label: "Tech", value: "Structural Reinforcement, Smart Holes Lineal pattern" }],
      sources: [S.padelful("adidas-drive-black-2026"), S.padelkiwi("adidas-drive-black-2026")],
    },
  },
  "head-evo-speed": {
    roundup: {
      status: "reviewed",
      summary:
        "HEAD's entry racket is lighter and more comfortable than the Speed range. Its soft foam and fibreglass face give easy power and a large sweet spot, with a smooth, direct feel.",
      liked: ["Light and easy to swing", "Comfortable, soft feel", "Large sweet spot"],
      watchOuts: ["Fibreglass gives less pace on fast shots"],
      suits: "New and improving players.",
      ourRead: "A low-risk first racket. Pick it over a heavier model if comfort matters more than pace.",
      facts: [],
      sources: [{ name: "HEAD", url: "https://www.head.com/en_GB/product/evo-speed-2025-226405" }],
    },
  },

  /* ------------------------------------------------------------ Bullpadel 2027 */
  "bullpadel-xplo-27": {
    fill: { ...BULLPADEL_27_FILL, ...GRAIN },
    roundup: {
      status: "early",
      summary:
        "Martín Di Nenno's 2027 racket is out, but full reviews are still in progress. Padel Verdict's comparison shows three changes from the 2026 model. The balance rises from 264 mm to 270 mm, the face changes from 12K to 3K carbon, and the core gains a third EVA density.",
      liked: ["More head weight for the smash than the 2026", "Geometric head: Bullpadel says about 23% more sweet spot than a classic diamond", "3D Grain texture for spin"],
      watchOuts: ["Very high balance: demanding at the net and in defence", "No independent on-court review yet"],
      suits: "Professional and advanced attackers.",
      ourRead:
        "On paper the most aggressive Xplo yet. Wait for the first full reviews before buying, or try the Xplo Comfort if your arm is sensitive.",
      facts: [{ label: "Change from 2026", value: "Balance 264 → 270 mm, 12K → 3K face, 2 → 3 EVA densities" }],
      sources: [{ name: "Padel Verdict", url: "https://padelverdict.com/rackets/bullpadel-xplo-27/" }, S.tennisnuts("bullpadel-xplo-padel-racket-27-1770879.html")],
    },
  },
  "bullpadel-xplo-comfort-27": {
    fill: { ...BULLPADEL_27_FILL, ...GRAIN },
    roundup: {
      status: "early",
      summary:
        "The softer Xplo trades the carbon face for Fibrix, a glass and carbon hybrid. Padelshop measures it on the soft side (63/75) with a neutral swingweight of 167, and describes a cushioned impact that keeps the Xplo's acceleration.",
      liked: ["Much softer impact than the Xplo", "Keeps the attacking character", "Ball sinks in and comes back smoothly"],
      watchOuts: ["Still high-balanced (about 26.5 cm)", "No full independent review yet"],
      suits: "Advanced attackers who want the Xplo's power with more comfort.",
      ourRead: "The Xplo most players should consider first. You give up a little crispness and gain a lot of arm-friendliness.",
      facts: [
        { label: "Padelshop hardness", value: "63 / 75 (soft)" },
        { label: "Padelshop swingweight", value: "167 (neutral)" },
      ],
      sources: [S.padelshop("products/bullpadel-xplo-comfort-2027"), S.padelproshop("bullpadel-padel-racket-xplo-cmf-2027")],
    },
  },
  "bullpadel-wonder-27": {
    fill: { ...BULLPADEL_27_FILL, ...GRAIN },
    roundup: {
      status: "early",
      summary:
        "Claudia Fernández's racket: light (350–360 g) with a low swingweight of 154, so it is quick to move. Fibrix faces over a triple-density core give easy ball output, and the frame is stiffened against twisting.",
      liked: ["Very manoeuvrable", "Excellent ball output", "Vibration damping in the handle", "Weight can be tuned with 3 g plates"],
      watchOuts: ["Light weight means less mass behind the smash", "No full independent review yet"],
      suits: "Advanced players, especially women, who move a lot and play every role.",
      ourRead: "A quick, forgiving all-rounder. It is also a smart pick for lighter players of any level who find 370 g rackets tiring.",
      facts: [
        { label: "Padelshop swingweight", value: "154 (manoeuvrable)" },
        { label: "Tech", value: "ExoFrame, Air React Channel, Vibradrive, CustomWeight" },
      ],
      sources: [S.padelmarket("products/bullpadel-wonder-2027-claudia-fernandez-padel-racket"), S.padelshop("collections/racket-teardrop-shape/products/bullpadel-wonder-2027")],
    },
  },
  "bullpadel-elite-02-27": {
    fill: { ...BULLPADEL_27_FILL, ...GRAIN },
    roundup: {
      status: "early",
      summary:
        "Gemma Triay's racket continues one of Bullpadel's most versatile lines. Retailers describe an all-terrain hybrid with a stable Elite Core heart, a 537 cm² face and a manoeuvrable swingweight of 159.",
      liked: ["Works in defence and attack", "Comfortable and controllable", "Large hitting area", "Quick at the net"],
      watchOuts: ["Not a pure power racket", "No full independent review yet"],
      suits: "Advanced all-court players who want a classic, reliable racket.",
      ourRead: "Hard to dislike. If you can't decide what kind of player you are, this is the kind of racket that suits you.",
      facts: [
        { label: "Hitting area", value: "537 cm²" },
        { label: "Padelshop swingweight", value: "159 (manoeuvrable)" },
        { label: "Tech", value: "Elite Core, Total Channel aerodynamics" },
      ],
      sources: [S.padelmarket("products/bullpadel-elite-02-2027-gemma-triay-padel-racket"), S.padelshop("collections/racket-teardrop-shape/products/bullpadel-elite-02-2027")],
    },
  },
  "bullpadel-flow-27": {
    fill: { ...BULLPADEL_27_FILL, ...GRAIN },
    roundup: {
      status: "early",
      summary:
        "Delfi Brea's light diamond. Padelshop measures it as very soft (60) and manoeuvrable (155): forgiving on off-centre hits, with little vibration, while the diamond head still gives leverage overhead.",
      liked: ["Very soft and forgiving", "Low vibration", "Attacking leverage in a light racket"],
      watchOuts: ["Soft faces give less crisp feedback", "No full independent review yet"],
      suits: "Advanced attacking players who want a lighter, comfortable diamond.",
      ourRead: "An unusual and appealing mix: a diamond that forgives. It is worth a try if heavier diamonds tire your arm.",
      facts: [
        { label: "Hitting area", value: "523 cm²" },
        { label: "Padelshop hardness / swingweight", value: "60 (very soft) / 155" },
        { label: "Tech", value: "FlowCore heart, VibraDrive" },
      ],
      sources: [S.padelshop("collections/rackets-diamond-shape/products/bullpadel-flow-2027"), S.padelproshop("bullpadel-padel-racket-flow-2027")],
    },
  },
  "bullpadel-icon-27": {
    fill: { ...BULLPADEL_27_FILL, ...GRAIN },
    roundup: {
      status: "early",
      summary:
        "Juan Martín Díaz's signature racket. The biaxial 12K carbon face gives a crisp, powerful response, and twin damping systems protect the joints. The listings describe an attacking racket that stays quick to handle.",
      liked: ["Crisp, powerful response", "Vibration damping (VibraDrive and EasyVibe)", "Adjustable balance", "Large 534 cm² face for a diamond"],
      watchOuts: ["High balance (about 26.3 cm)", "No full independent review yet"],
      suits: "Advanced and professional attackers.",
      ourRead: "A more comfortable route into attacking padel than the Vertex. Worth shortlisting once the first reviews land.",
      facts: [{ label: "Hitting area", value: "534 cm²" }],
      sources: [S.padelshop("collections/rackets-diamond-shape/products/bullpadel-icon-2027"), { name: "Tennisshopen", url: "https://tennisshopen.se/en/padel/bullpadel-icon-padelracket-2027/" }],
    },
  },
  "bullpadel-neuron-02-comfort-27": {
    fill: BULLPADEL_27_FILL,
    roundup: {
      status: "early",
      summary:
        "The Neuron's dry, controlled HardEVA feel behind a softer Fibrix face. Four small dampers in the face can be moved to other holes to shift the feel. Bullpadel says they absorb up to 49% of vibration. Padelshop measures a swingweight of 158.",
      liked: ["Classic Neuron precision with less vibration", "Tunable dampers", "Manoeuvrable at the net"],
      watchOuts: ["You supply the power: the face returns energy less readily", "No full independent review yet"],
      suits: "Players who like the Neuron's control but want an easier ride on the arm.",
      ourRead: "A clever idea. For players with sensitive elbows it's the Neuron to choose.",
      facts: [
        { label: "Padelshop hardness / swingweight", value: "64 / 158" },
        { label: "Damping", value: "Ease Vibe, four movable face dampers" },
      ],
      sources: [S.padelshop("products/bullpadel-neuron-02-comfort-2027")],
    },
  },
  "bullpadel-neuron-02-edge-27": {
    fill: { ...BULLPADEL_27_FILL, ...GRAIN },
    roundup: {
      status: "early",
      summary:
        "Chingotto's geometric Neuron: a diamond with wider shoulders. Bullpadel says that gives about 23% more sweet spot than a classic diamond. The 3K carbon face feels firm and dry, and Padelshop measures a manoeuvrable swingweight of 156.",
      liked: ["Diamond reach with more margin", "Firm, solid contact", "Manoeuvrable for its shape"],
      watchOuts: ["Firm feel won't suit everyone", "No full independent review yet"],
      suits: "Players who hit high on the face and want more forgiveness than a pure diamond.",
      ourRead: "A good stepping stone towards a diamond, without the usual tiny sweet spot.",
      facts: [
        { label: "Padelshop swingweight", value: "156 (manoeuvrable)" },
        { label: "Tech", value: "PrismLock frame, inverted-pentagon NeuronCore" },
      ],
      sources: [{ name: "Padel Deals", url: "https://padeldeals.co.za/products/2027-bullpadel-neuron-02-edge" }, S.padelshop("collections/diamond-padel-racket/products/bullpadel-neuron-02-edge-2027")],
    },
  },
  "bullpadel-neuron-27": {
    fill: BULLPADEL_27_FILL,
    roundup: {
      status: "early",
      summary:
        "The hybrid Neuron uses HardEVA: firmer rubber outside, softer inside. The result is a drier, control-focused racket for players who value precision over power. Padelshop measures a neutral swingweight of 160.",
      liked: ["Precise and controllable", "Central, larger sweet spot than a diamond", "Works high or mid face"],
      watchOuts: ["Not built for raw power", "No full independent review yet"],
      suits: "Control and touch players.",
      ourRead: "Precision first. Pair it with good footwork and it rewards patience.",
      facts: [{ label: "Padelshop hardness / swingweight", value: "61 / 160 (neutral)" }],
      sources: [S.padelshop("collections/bullpadel-padel-rackets/products/bullpadel-neuron-2027")],
    },
  },
  "bullpadel-vertex-05-27": {
    fill: { ...BULLPADEL_27_FILL, ...GRAIN },
    roundup: {
      status: "early",
      summary:
        "On paper it matches the 2026 Vertex 05. Padelshop's measurements show the real change: swingweight drops from 162 to 157, which takes it from neutral to manoeuvrable. It accelerates more easily and reacts faster at the net.",
      liked: ["Quicker through the air than the 2026 model", "Triangular Vertex Core resists twisting", "Weight plates to tune balance"],
      watchOuts: ["Still a demanding diamond", "No full independent review yet"],
      suits: "Advanced and professional attackers.",
      ourRead: "If you liked the 2026 Vertex 05 but found it heavy at the net, this is a real improvement, not just new paint.",
      facts: [
        { label: "Padelshop hardness", value: "64 (2026: 65)" },
        { label: "Padelshop swingweight", value: "157 (2026: 162)" },
      ],
      sources: [
        { ...S.padelshop("blogs/padel-tips/bullpadel-vertex-05-2027-vs-2026"), name: "Padelshop: 2027 vs 2026" },
        { ...S.padelshop("collections/rackets-diamond-shape/products/bullpadel-vertex-05-2027"), name: "Padelshop: listing" },
      ],
    },
  },
  "bullpadel-vertex-05-comfort-27": {
    fill: BULLPADEL_27_FILL,
    roundup: {
      status: "early",
      summary:
        "The Vertex with a Fibrix face (glass fibre woven with carbon in an elastic resin) for a softer, more forgiving response. Padelshop measures a swingweight of 157, light-handed for a high-balanced diamond.",
      liked: ["Vertex power with a softer response", "More forgiving contact", "Manoeuvrable for its balance"],
      watchOuts: ["Diamond sweet spot sits high", "No full independent review yet"],
      suits: "Advanced attackers who want the Vertex's character with more comfort.",
      ourRead: "The sensible Vertex for most club attackers.",
      facts: [{ label: "Padelshop hardness / swingweight", value: "64 / 157" }],
      sources: [S.tennisnuts("bullpadel-vertex-05-comfort-padel-racket-27-1770874.html"), { ...S.padelshop("blogs/padel-tips/bullpadel-vertex-05-2027-vs-2026"), name: "Padelshop: Vertex 05 2027 vs 2026" }],
    },
  },
  "bullpadel-vertex-05-geo-27": {
    fill: { ...BULLPADEL_27_FILL, ...GRAIN },
    roundup: {
      status: "early",
      summary:
        "A geometric Vertex: a diamond with wider shoulders and about 23% more sweet spot, according to Bullpadel. Padelshop measures it soft (62) with a neutral swingweight of 161. It plays as a diamond with more margin.",
      liked: ["Diamond character with more margin", "Soft, forgiving contact", "Rough face for spin"],
      watchOuts: ["Retailers list different face materials", "No full independent review yet"],
      suits: "Players moving towards a diamond, or who want a diamond that forgives more.",
      ourRead: "A good bridge model, and worth trying before committing to the full Vertex 05.",
      facts: [{ label: "Padelshop hardness / swingweight", value: "62 (soft) / 161 (neutral)" }],
      sources: [S.padelshop("products/bullpadel-vertex-05-geo-2027")],
    },
  },
  "bullpadel-vertex-05-hybrid-27": {
    fill: BULLPADEL_27_FILL,
    roundup: {
      status: "early",
      summary:
        "The most versatile Vertex. The hybrid head moves the sweet spot lower and makes it bigger. Padelshop measures it soft (63) and manoeuvrable (155), so it works for attack and for control.",
      liked: ["Bigger, more central sweet spot", "Manoeuvrable", "Comfortable contact"],
      watchOuts: ["Less smash leverage than the diamond Vertex", "No full independent review yet"],
      suits: "Versatile advanced players who switch between attack and defence.",
      ourRead: "The Vertex for players who don't live at the net.",
      facts: [{ label: "Padelshop hardness / swingweight", value: "63 / 155" }],
      sources: [S.padelshop("products/bullpadel-vertex-05-hybrid-2027")],
    },
  },
  "bullpadel-vertex-05-w-27": {
    fill: BULLPADEL_27_FILL,
    roundup: {
      status: "early",
      summary:
        "Delfi Brea's lighter Vertex (350–360 g). Retailers describe an all-round racket that reacts quickly through every phase of the point, with a Fibrix face that flexes more than full carbon.",
      liked: ["Light and fast to react", "All-round balance of power and control", "Tunable weight"],
      watchOuts: ["Less mass behind the smash than the standard Vertex", "No full independent review yet"],
      suits: "Advanced players, especially women, who want an all-round diamond.",
      ourRead: "A lighter, friendlier Vertex. Good for anyone who finds 370 g tiring, not only women players.",
      facts: [
        { label: "Hitting area", value: "530 cm²" },
        { label: "Tech", value: "Curv:Aktiv, Air Power, CustomWeight" },
      ],
      sources: [S.padelmarket("products/bullpadel-vertex-05-w-2027-delfi-brea-racket"), S.padelproshop("bullpadel-padel-racket-vertex-05-w-2027")],
    },
  },
  "bullpadel-hack-05-comfort-27": {
    fill: { ...BULLPADEL_27_FILL, ...GRAIN },
    roundup: {
      status: "early",
      summary:
        "The Hack 05 with Fibrix faces in place of TriCarbon, a more flexible fibre that softens impact. It is slightly lighter (360–370 g) and keeps an offensive balance of about 26.5 cm.",
      liked: ["Hack power with less arm strain", "Slightly lighter and easier to handle", "Damping and adjustable weight"],
      watchOuts: ["Still an attacking diamond", "No full independent review yet"],
      suits: "Advanced attackers who want the Hack with a more comfortable feel.",
      ourRead: "Most players drawn to the Hack should start here.",
      facts: [
        { label: "Hitting area", value: "522 cm²" },
        { label: "Tech", value: "ExoAir, Air Power, Hack Core³, EasyVibe, CustomWeight" },
      ],
      sources: [S.padelmarket("products/bullpadel-hack-05-comfort-2027-paquito-navarro-racket"), S.padelproshop("bullpadel-padel-racket-hack-05-cmf-2027")],
    },
  },
  "bullpadel-hack-05-hybrid-27": {
    fill: BULLPADEL_27_FILL,
    roundup: {
      status: "early",
      summary:
        "The versatile Hack. The A/18K face mixes 18K carbon with aluminium fibres for more flex and absorption; Bullpadel says up to 49% of vibration. The hybrid head and 25 cm balance favour handling.",
      liked: ["Control from every zone", "Enough power for viboras and smashes", "Comfortable, vibration-absorbing face"],
      watchOuts: ["Less outright power than the other Hacks", "No full independent review yet"],
      suits: "Technically skilled players who build points.",
      ourRead: "A Hack for thinkers rather than bangers.",
      facts: [{ label: "Hitting area", value: "529 cm²" }],
      sources: [S.tennisnuts("bullpadel-hack-05-hybrid-padel-racket-27-1770863.html"), S.padelshop("collections/rackets-200/products/bullpadel-hack-05-hybrid-2027")],
    },
  },

  /* ------------------------------------------------------------ HEAD */
  "head-speed-one-x-2025": {
    fill: { frameMaterial: "Carbon" },
    roundup: {
      status: "reviewed",
      summary:
        "Tennis Warehouse's write-up highlights the ONE construction, a single large opening instead of drilled holes, for extra durability. The high 270 mm balance tilts this teardrop towards power, and the damping keeps it comfortable.",
      liked: ["Durable single-hole construction", "Power for a teardrop", "Comfortable, spin-friendly face"],
      watchOuts: ["365 g with a high balance: needs some strength"],
      suits: "Advanced players who want power with control.",
      ourRead: "A distinctive racket that should last. Its durability is a real plus for frequent players.",
      facts: [{ label: "Tech", value: "ONE single-hole face, Auxetic 2.0, Damp Plus, Soft Butt Cap 2.0" }],
      sources: [S.tw("Head_Speed_One_X_2025_Padel_Racket/descpage-HPSPONX25.html"), S.tennisnuts("shop/padel/rackets/head-speed-one-x-padel-racket-2025-1680920.html")],
    },
  },
  "head-speed-one-2025": {
    fill: { frameMaterial: "Carbon with graphene" },
    roundup: {
      status: "reviewed",
      summary:
        "The lightest Speed (345 g) with the single-hole ONE face. Reviewers note that the light weight makes the high 270 mm balance manageable for intermediate players, and that the construction is very durable.",
      liked: ["Light and quick", "Durable", "Power from the high balance without the weight"],
      watchOuts: ["Less mass for blocking hard hitters"],
      suits: "Intermediate and advanced players who want a light, powerful teardrop.",
      ourRead: "A good way into a pro-style racket without the 370 g weight.",
      facts: [{ label: "Face", value: "2D-layered carbon, single hole" }],
      sources: [S.tw("Head_Speed_One_2025_Padel_Racket/descpageRCHEAD-HPSPON25.html"), { name: "Racketpedia", url: "https://www.racketpedia.com/en-GB/padel-racket/head-speed-one-2025" }],
    },
  },
  "head-speed-motion-2025": {
    fill: { surfaceFinish: "smooth" },
    roundup: {
      status: "reviewed",
      summary:
        "PadelSpeak gives Ari Sánchez's racket 8/10. It is a well-built, no-surprises all-rounder at a competitive price, with a generous sweet spot and a lively response at the net.",
      liked: ["Generous, forgiving sweet spot", "Lively at the net", "Good on overheads", "Competitive price"],
      watchOuts: ["Too light to block big hitters", "Smooth face can let the ball slip on serves", "Won't satisfy pure power or spin seekers"],
      suits: "Intermediate to advanced all-round players.",
      ourRead: "Good value and few weaknesses; it is a racket you'll get along with from day one.",
      facts: [{ label: "PadelSpeak score", value: "8 / 10" }],
      sources: [{ name: "PadelSpeak", url: "https://padelspeak.com/en/head-speed-motion-2025-review/" }, S.tw("Head_Speed_Motion_2025_Padel_Racket/descpage-HPSPMOT25.html")],
    },
  },
  "head-speed-team-2025": {
    fill: { frameMaterial: "Carbon fibre" },
    roundup: {
      status: "reviewed",
      summary:
        "The softest and most forgiving Speed. Reviewers praise its fibreglass face for a soft, comfortable touch and easy ball exit, with enough mass for some power.",
      liked: ["Soft, comfortable feel", "Easy ball exit", "Forgiving"],
      watchOuts: ["Less precise at high pace than the carbon Speeds"],
      suits: "Intermediate players with an all-round game.",
      ourRead: "A comfortable step up from a beginner racket.",
      facts: [],
      sources: [S.tw("Head_Speed_Team_2025_Padel_Racket/descpageRCHEAD-HPSPTEA25.html"), S.padelful("head-speed-team-2025")],
    },
  },
  "head-radical-pro-2026": {
    roundup: {
      status: "reviewed",
      summary:
        "A firm, precise teardrop. Professional reviews collected by Padelful rate it about 9.5 for control and 8.3 for manoeuvrability. It places the ball exactly and is stable on blocks and volleys.",
      liked: ["Exact placement", "Stable blocks and volleys", "Agile at the net", "Control Foam widens the sweet spot"],
      watchOuts: ["The heaviest Radical (370 g)", "Rewards clean technique more than it helps"],
      suits: "Tactical tournament players.",
      ourRead: "A precision tool. Its pace is composed rather than explosive, and the right player will love that.",
      facts: [],
      sources: [{ name: "HEAD", url: "https://www.head.com/en/product/radical-pro-2026-222036" }, S.padelful("head-radical-pro-2026")],
    },
  },
  "head-radical-motion-2026": {
    fill: { frameMaterial: "Carbon fibre" },
    roundup: {
      status: "reviewed",
      summary:
        "A user-friendly teardrop at 355 g and 260 mm balance. Testers say the 2026 update is more manoeuvrable and more stable at contact. It is control-oriented with an offensive streak: firm, sharp and reliable.",
      liked: ["Easy to handle", "Firm, sharp contact", "Reliable for building points", "Swappable cap cord"],
      watchOuts: ["Less pace than heavier Radicals"],
      suits: "Advanced tactical players who control the rhythm.",
      ourRead: "The Radical most players will get along with.",
      facts: [{ label: "Tech", value: "Auxetic 2.0, Soft Cap+ with exchangeable cord" }],
      sources: [S.tw("Head_Radical_Motion_2026_Padel_Racket/descpageRCHEAD-HPRRADMO26.html"), S.padelful("head-radical-motion-2026")],
    },
  },
  "head-radical-team-2026": {
    fill: { frameMaterial: "Carbon fibre" },
    roundup: {
      status: "reviewed",
      summary:
        "Fibreglass faces on a carbon frame. Reviewers find it solid, predictable and very forgiving; one rates its control 9.3/10. The low 255 mm balance keeps it easy to move.",
      liked: ["Very forgiving", "Comfortable, easy ball exit", "Predictable control", "Carbon frame resists twisting"],
      watchOuts: ["Not a power racket"],
      suits: "Beginners to intermediates with a tactical game.",
      ourRead: "An excellent control racket for improving players.",
      facts: [],
      sources: [S.tw("Head_Radical_Team_2026_Padel_Racket/descpageRCHEAD-HPRRADTE26.html"), S.padelful("head-radical-team-2026")],
    },
  },
  "head-coello-pro-2026": {
    roundup: {
      status: "reviewed",
      summary:
        "Arturo Coello's racket is one of the heaviest and most head-heavy in the catalogue, at 272 mm and about 370 g. PadelSpeed's review calls it a match-finishing weapon that loads smashes and viboras with leverage.",
      liked: ["Serious pace and spin overhead", "Maximum stability at the net", "Rough 3D face"],
      watchOuts: ["Demands full offensive technique", "Not a racket to develop with"],
      suits: "Expert left-side attackers.",
      ourRead: "Exactly what it says: a pro's weapon. Club players should look at the Coello Motion or Team versions.",
      facts: [],
      sources: [{ name: "PadelSpeed", url: "https://padelspeed.com/blogs/news/head-coello-pro-2026-padel-racket-review-pure-power-for-advanced-attacking-players" }, S.tennisnuts("head-coello-pro-padel-racket-2026-1757271.html")],
    },
  },
  "head-extreme-motion-2026": {
    fill: { hardness: "medium-hard" },
    set: { faceMaterial: "Carbon, Extreme Spin rough finish" },
    roundup: {
      status: "reviewed",
      summary:
        "padel.fyi's expert review (7.9/10) calls it the best Motion HEAD has made. The full carbon face adds the feel and control earlier Motions lacked, and the contained weight (about 358 g measured) keeps it easy to move for a diamond.",
      liked: ["Precise bandejas, viboras and volleys", "Very manoeuvrable for a diamond", "Good value"],
      watchOuts: ["Moderate ball output on slow balls", "Needs more arm in passive defence"],
      suits: "Players who take the net and play with intent.",
      ourRead: "A diamond for players who don't want a heavy diamond. A strong pick.",
      facts: [{ label: "padel.fyi score", value: "7.9 / 10" }],
      sources: [{ name: "padel.fyi", url: "https://www.padel.fyi/rackets/extreme-motion-2026/" }, S.padelkiwi("head-extreme-motion-2026")],
    },
  },

  /* ------------------------------------------------------------ Nox */
  "nox-at10-luxury-genius-12k-alum-xtrem-2026": {
    fill: { frameMaterial: "Carbon fibre", thicknessMm: 38, hardness: "medium-hard", surfaceFinish: "rough" },
    set: { faceMaterial: "Carbon 12K Alum Xtrem, Dual Spin finish" },
    roundup: {
      status: "reviewed",
      summary:
        "Tapia's teardrop with Nox's new 12K Alum Xtrem carbon. Nox says it halves the fibre waviness for a more uniform, rigid face. The aluminised finish keeps the feel steady in heat and cold, and a high-density core adds power on smashes without losing control.",
      liked: ["Power and control in balance", "Uniform, rigid face", "Spin from the Dual Spin texture", "Adjustable counterweights"],
      watchOuts: ["Medium-hard touch", "Professional-level price"],
      suits: "Advanced aggressive players who still want control.",
      ourRead: "The AT10 for players who like a firmer, more direct feel than the 18K version.",
      facts: [
        { label: "Weight system", value: "Weight Balance, 2 g and 4 g counterweights" },
        { label: "Face", value: "12K Alum Xtrem: 50% less fibre waviness (Nox)" },
      ],
      sources: [{ name: "Padel Deals", url: "https://padeldeals.co.za/products/at10-luxury-genius-12k-alum-xtrem-2026-by-agustin-tapia" }],
    },
  },
  "nox-at10-luxury-genius-attack-12k-alum-xtrem-2026": {
    fill: { frameMaterial: "Carbon fibre", surfaceFinish: "rough" },
    set: { faceMaterial: "Carbon 12K Alum Xtrem, Dual Spin finish" },
    roundup: {
      status: "reviewed",
      summary:
        "The diamond AT10, with a high balance and a longer grip. Padelshop's comparison with the 2025 model describes explosive ball output from the high-memory core. In defence it needs good footwork and early preparation, and it doesn't hide mistakes.",
      liked: ["Explosive smashes", "Sharp spin", "Solid, firm feel"],
      watchOuts: ["Unforgiving in defence", "Exposes late preparation"],
      suits: "Professional and advanced attackers who dictate from the net.",
      ourRead: "Pure Tapia attack. Only for players whose game is built around the net.",
      facts: [],
      sources: [S.padelshop("blogs/padel-tips/nox-at10-attack-12k-2026-vs-2025"), { name: "Padelgids", url: "https://padelgids.nl/padelgear/padel-rackets/nox-at10-genius-attack-12k-alum-xtreme-2026/" }],
    },
  },
  "nox-at10-luxury-genius-attack-18k-alum-2026": {
    fill: { frameMaterial: "Carbon fibre", surfaceFinish: "rough" },
    set: { faceMaterial: "Carbon 18K Alum, Dual Spin finish" },
    roundup: {
      status: "reviewed",
      summary:
        "Padelful scores it 9.6 for power and 9.1 for control: an attacking diamond with sharp control and fast hands that doesn't feel unruly. Padelshop finds the 2026 model firmer, more stable and better balanced than the 2025, with more spin.",
      liked: ["Strong net presence and volleys", "Easy spin on the bandeja", "Explosive, weighty smash"],
      watchOuts: ["Blocks need early set-up", "Off-centre hits feel unforgiving", "Late preparation is punished"],
      suits: "Attackers who want a sharp tool that stays controllable.",
      ourRead: "Too demanding if you need help from the back of the court, and excellent if you don't.",
      facts: [{ label: "Padelful scores", value: "Power 9.6 · Control 9.1 · Sweet spot 8.2" }],
      sources: [S.padelful("nox-at10-genius-attack-18k-alum-2026"), { name: "Padelgids", url: "https://padelgids.nl/padelgear/padel-rackets/nox-at10-genius-attack-18k-alum-2026/" }],
    },
  },
  "nox-at10-luxury-genius-12k-alum-xtrem-lite-2026": {
    fill: { balance: "medium", frameMaterial: "Carbon fibre", surfaceFinish: "rough" },
    set: { faceMaterial: "Carbon 12K Alum Xtrem, Dual Spin finish" },
    roundup: {
      status: "reviewed",
      summary:
        "The lighter AT10 (355–365 g) with a softer white EVA core. It keeps the 12K face's directness but is more manoeuvrable and accessible. Buyers mention good control, a wide sweet spot and comfort.",
      liked: ["Light and agile", "Wide sweet spot", "Comfortable"],
      watchOuts: ["Less power than the full-weight AT10", "Expensive for a lighter racket"],
      suits: "Players who want the AT10 feel at a lighter weight.",
      ourRead: "The best AT10 for most club players.",
      facts: [{ label: "Weight system", value: "2 g and 4 g handle counterweights, no tools needed" }],
      sources: [S.twe("Nox_AT10_Genius_12K_Xtreme_Lite_Tapia_Padel_Racket_/descpageRCNOXPAD-NXG12KAGTL-EN.html"), S.padelful("nox-at10-genius-12k-alum-xtrem-lite-2026")],
    },
  },
  "nox-ml10-ventus-control-3k-2026": {
    fill: { frameMaterial: "Carbon fibre", surfaceFinish: "rough" },
    set: { faceMaterial: "Soft 3K carbon, Dual Spin finish" },
    roundup: {
      status: "reviewed",
      summary:
        "Miguel Lamperti's control racket. PadelSpeed reports that the Spanish test site Testea Padel named it the best control racket in its category two years running. The round head, low balance and soft core put less stress on the elbow and wrist.",
      liked: ["Precise placement", "Forgiving", "Easy on elbow and wrist"],
      watchOuts: ["Power comes from your swing, not the racket"],
      suits: "Tactical players who build from the back.",
      ourRead: "A control specialist with a strong reputation. A top pick for patient players and anyone with arm trouble.",
      facts: [],
      sources: [{ name: "PadelSpeed", url: "https://padelspeed.com/pt/blogs/news/spotlight-on-nox-ml10-ventus-control-3k-miguel-lamperti-2026" }, S.padelmarket("products/nox-ml10-ventus-control-3k-2026-by-miguel-lamperti-racket-1")],
    },
  },
  "nox-ea10-ventus-attack-12k-xtrem-2026": {
    fill: { frameMaterial: "Carbon fibre", surfaceFinish: "rough" },
    set: { faceMaterial: "Carbon 12K Xtrem, Dual Spin finish" },
    roundup: {
      status: "reviewed",
      summary:
        "Edu Alonso's diamond. Padelful scores it 9.7 for power, 9 for control, 8 for manoeuvrability and 7.9 for sweet spot. It thrives in fast exchanges at the net and on overheads, and asks more of you in defence.",
      liked: ["Huge power", "Spin and control in attack", "Great in fast net exchanges"],
      watchOuts: ["Smaller sweet spot", "Demanding in defence"],
      suits: "Advanced, committed attackers.",
      ourRead: "A cheaper route to AT10-style attack.",
      facts: [{ label: "Padelful scores", value: "Power 9.7 · Control 9 · Sweet spot 7.9" }],
      sources: [S.padelful("nox-ea10-ventus-attack-12k-xtrem-2026"), { name: "Padelgids", url: "https://padelgids.nl/padelgear/padel-rackets/nox-ea10-ventus-attack-12k-xtreme-2026/" }],
    },
  },
  "nox-ea10-ventus-hybrid-12k-xtrem-2026": {
    fill: { thicknessMm: 38, frameMaterial: "Carbon fibre", surfaceFinish: "rough" },
    set: { faceMaterial: "Carbon 12K Xtrem, Dual Spin finish" },
    roundup: {
      status: "early",
      summary:
        "We found product descriptions but no independent review yet. Nox and retailers describe a balanced teardrop whose MLD core gives control on slow balls and power on fast ones.",
      liked: ["Versatile attack and defence (per listings)", "Adaptive multilayer core"],
      watchOuts: ["No independent review found yet"],
      suits: "Advanced players who want an all-court teardrop.",
      ourRead: "Promising on paper. We'll update this when a proper test is published.",
      facts: [],
      sources: [S.padelshop("products/nox-ea10-ventus-hybrid-12k-xtreme-2026")],
    },
  },

  /* ------------------------------------------------------------ Babolat */
  "babolat-counter-viper-2-6-2026": {
    fill: { balanceMm: 270 },
    roundup: {
      status: "reviewed",
      summary:
        "Tennis Nuts' staff review finds it exceptionally stable at impact. It handles incoming pace well, with excellent control from the back, and power is there when needed but never at the cost of accuracy.",
      liked: ["Very stable", "Absorbs pace well", "Control from the back of the court"],
      watchOuts: ["Retailers disagree on balance (listed head-heavy and even)"],
      suits: "Advanced players who win through consistency and placement.",
      ourRead: "A counter-puncher's Viper: calm, accurate and dependable.",
      facts: [{ label: "Core", value: "Multi-layer X-EVA" }],
      sources: [S.tennisnuts("babolat-counter-viper-2-6-padel-racket-2026-1755270.html"), S.tw("Babolat_Counter_Viper_26_Padel_Racket/descpage-BPRCTRVI26.html")],
    },
  },
  "babolat-technical-viper-soft-3-0-2026": {
    fill: { balance: "high", frameMaterial: "100% carbon", coreMaterial: "Black EVA" },
    roundup: {
      status: "reviewed",
      summary:
        "Padelful finds it firmer than the word Soft suggests, but noticeably less harsh than the Technical Viper. Ball exit is easy for an attacking racket, though clean contact still matters.",
      liked: ["Easy power on smashes and volleys", "Smoother, less tiring impact", "Attacking diamond that isn't brutal"],
      watchOuts: ["Doesn't rescue sloppy preparation", "Off-centre hits are obvious", "Head-heavy setup can tire the arm"],
      suits: "Advanced attackers who want more comfort than the standard Viper.",
      ourRead: "The Viper most attackers should actually buy.",
      facts: [],
      sources: [S.padelful("babolat-technical-viper-soft-3-0-2026"), S.tennisnuts("babolat-technical-viper-soft-3-0-padel-racket-2026-1755273.html")],
    },
  },
  "babolat-technical-veron-3-0-2026": {
    fill: { balance: "high", thicknessMm: 38, coreMaterial: "Black EVA" },
    roundup: {
      status: "reviewed",
      summary:
        "Padel Verdict describes confidence-boosting power that doesn't feel overly demanding. It is solid at impact and balances explosiveness and control, especially on volleys and overheads, and is more forgiving than the Viper.",
      liked: ["Accessible power", "Solid feel", "More forgiving than the Viper", "Manageable over long matches"],
      watchOuts: ["Still a head-heavy attacking racket"],
      suits: "Intermediate to advanced players who want to attack.",
      ourRead: "A friendly way into attacking padel.",
      facts: [{ label: "Face", value: "Carbon Flex: carbon and fibreglass" }],
      sources: [{ name: "Padel Verdict", url: "https://padelverdict.com/?p=1127" }, S.tennisnuts("babolat-technical-veron-3-0-padel-racket-2026-1755304.html")],
    },
  },
  "babolat-viper-juan-lebron-3-0-2026": {
    roundup: {
      status: "reviewed",
      summary:
        "Padelful calls it a hard, attack-minded diamond with crisp volleying, and composed enough to keep a point alive in defence. Like Lebrón, it wants to finish points, not build them.",
      liked: ["Strong ball exit on volleys", "Clean bandejas and viboras", "Stable, direct at the net"],
      watchOuts: ["Defence demands active footwork", "Hard on late baseline shots", "Too stiff for some"],
      suits: "Advanced and professional attackers.",
      ourRead: "A real pro racket. Pick the Viper Soft unless you want the full stiffness.",
      facts: [],
      sources: [S.padelful("babolat-viper-3-0-2026-juan-lebron"), { name: "PadelSpeed", url: "https://padelspeed.com/blogs/news/spotlight-on-babolat-viper-juan-lebron-3-0-padel-racket" }],
    },
  },

  /* ------------------------------------------------------------ adidas */
  "adidas-metalbone-team-2026": {
    fill: { thicknessMm: 38 },
    roundup: {
      status: "reviewed",
      summary:
        "The Tennis Nuts write-up finds real punch on overheads from the head-heavy balance, while the soft EVA keeps it forgiving in long rallies. It is a confident, well-rounded racket for competitive club players.",
      liked: ["Punch on overheads", "Forgiving in long rallies", "Octagonal frame resists twisting"],
      watchOuts: ["Fibreglass faces are less crisp than carbon"],
      suits: "Competitive club players who want controllable power.",
      ourRead: "The Metalbone for players who aren't pros, and it's a good one.",
      facts: [
        { label: "Hitting area", value: "485 cm²" },
        { label: "Tech", value: "Octagonal Structure, Low Poly frame, Spin Blade Gritt" },
      ],
      sources: [S.tennisnuts("adidas-metalbone-team-padel-racket-2026-1750285.html")],
    },
  },
  "adidas-metalbone-hrd-plus-2026": {
    fill: { faceMaterial: "16K aluminised carbon", surfaceFinish: "3d" },
    roundup: {
      status: "reviewed",
      summary:
        "Padel Market compared it with the standard Metalbone. The denser High Memory EVA makes it firmer but still reactive, and gives more control, better response when you accelerate and maximum smash power with good technique. Their tester preferred the HRD+.",
      liked: ["Firmer, more controllable", "Responds well at high swing speed", "Maximum smash power"],
      watchOuts: ["Medium-hard feel", "Needs good technique"],
      suits: "Advanced attackers with a fast swing.",
      ourRead: "For strong hitters. If you're unsure, the standard Metalbone is the safer pick.",
      facts: [{ label: "Core", value: "High Memory EVA (denser, for high swing speeds)" }],
      sources: [S.padelmarket("blogs/blog/adidas-metalbone-vs-metalbone-hrd"), S.twe("descpageRC-APRMETHRD26-EN.html")],
    },
  },
  "adidas-arrow-hit-pro-edt-2026": {
    fill: { weightMinG: 360, weightMaxG: 375, balance: "high", thicknessMm: 38, coreMaterial: "EVA Soft Performance", faceMaterial: "Carbon", surfaceFinish: "3d" },
    roundup: {
      status: "early",
      summary:
        "Ari Sánchez's limited edition. Retail listings describe a power diamond for dominating at the net, with a soft core for good ball output and more tolerance on off-centre hits. We found no independent test yet.",
      liked: ["Power at the net (per listings)", "Soft core gives tolerance off-centre", "Adjustable balance"],
      watchOuts: ["No independent review found yet", "Limited edition"],
      suits: "Advanced power players.",
      ourRead: "Promising, and not yet proven by an independent test.",
      facts: [{ label: "Balance", value: "Intelligent Balance System (adjustable)" }],
      sources: [S.twe("adidas_Arrow_Hit_Pro_EDT_2026_Padel_Racket/descpageRC-APRAROHTEDT-EN.html"), { name: "Zona de Padel", url: "https://www.zonadepadel.com/adidas-padel/15513-adidas-arrow-hit-pro-edt-2026.html" }],
    },
  },

  /* ------------------------------------------------------------ others */
  "siux-electra-pro-shadow-red-2026": {
    fill: { weightMinG: 360, weightMaxG: 375, thicknessMm: 38, coreMaterial: "EVA Hard", hardness: "medium-hard" },
    roundup: {
      status: "reviewed",
      summary:
        "Padelful scores it 9.1 for power, 9.1 for control and 9 for manoeuvrability. The hard EVA core means the ball doesn't jump off on slow shots but leaves fast as your swing speeds up. The matte, sandpaper-like finish helps spin.",
      liked: ["Power and control in balance", "Quick handling", "Grippy finish for spin", "Easy strap change"],
      watchOuts: ["Little free power on soft shots"],
      suits: "Aggressive, precise advanced players.",
      ourRead: "A well-rounded attacking racket that rewards a full swing.",
      facts: [{ label: "Padelful scores", value: "Power 9.1 · Control 9.1 · Manoeuvrability 9" }],
      sources: [S.padelful("siux-electra-pro-shadow-red-2026-franco-stupackzuk"), S.padelshop("products/siux-trilogy-pro-2026-shadow-red")],
    },
  },
  "siux-fenix-pro-2026": {
    fill: { weightMinG: 360, weightMaxG: 375, thicknessMm: 38, frameMaterial: "Carbon" },
    roundup: {
      status: "reviewed",
      summary:
        "A power diamond with a high balance and a firm EVA core. Reviews describe it as especially strong on smashes, volleys and overhead winners.",
      liked: ["Strong overheads", "Rigid yet light carbon build", "Good at finishing points at the net"],
      watchOuts: ["Hard feel", "Retailers list different carbon grades"],
      suits: "Advanced players and strong intermediate attackers.",
      ourRead: "A direct, no-nonsense attacking racket.",
      facts: [],
      sources: [S.twe("descpageRCSIUXPAD-SXPRFP26B-EN.html"), { name: "PadelSpeed", url: "https://padelspeed.com/products/padel-racket-siux-fenix-pro-black-2026" }],
    },
  },
  "lok-maxx-hype-gen-2-yanguas-2026": {
    roundup: {
      status: "reviewed",
      summary:
        "Mike Yanguas's oversize diamond. A retailer's expert ratings give 9 for performance, control and impact, 8 for comfort and 6 for manoeuvrability: maximum power and direct feedback, but not quick in the hand.",
      liked: ["Maximum power", "Direct feedback", "Control at full intensity"],
      watchOuts: ["Low manoeuvrability", "High-density core feels firm"],
      suits: "Advanced, offensive players.",
      ourRead: "A big-hitting racket for big hitters. Fast-hands net players should look elsewhere.",
      facts: [
        { label: "Retailer ratings", value: "Control 9 · Comfort 8 · Manoeuvrability 6" },
        { label: "Tech", value: "3D Spin Lines, Dynamic Holes System, Vibration Groove, Gradual Face" },
      ],
      sources: [{ name: "Padel Reference", url: "https://www.padelreference.com/de/padelschlager/p/lok-maxx-hype-gen-2-mike-yanguas-2026" }, { name: "Zona de Padel", url: "https://www.zonadepadel.com/lok/13833-lok-maxx-hype-gen-2-limited-edition-2026.html" }],
    },
  },
  "kuikma-hybrid-pro-coki-nieto": {
    roundup: {
      status: "reviewed",
      summary:
        "Decathlon's pro racket has more than 100 buyer reviews, about three quarters of them 5 stars. Buyers say it is firm and easy in defence, has very good feel on lobs, and works well overhead without being excessively powerful.",
      liked: ["Firm and easy in defence", "Good feel on lobs", "Fluid transitions from defence to attack", "Strong value"],
      watchOuts: ["Not a pure power racket"],
      suits: "Strategic players who control the rhythm from anywhere.",
      ourRead: "Excellent value, and a lot of racket for the money.",
      facts: [{ label: "Buyer reviews", value: "108 on Decathlon, about 76% five-star" }],
      sources: [{ name: "Decathlon (buyer reviews)", url: "https://www.decathlon.es/es/r/pala-de-padel-kuikma-hybrid-pro-coki-nieto/338036/c236m8993121" }, { name: "Decathlon", url: "https://www.decathlon.ie/p/338036-586244-padel-racket-hybrid-pro-coki-nieto.html" }],
    },
  },
  "drop-shot-axion-attack-1-5-2025": {
    fill: { weightMinG: 365, weightMaxG: 385, frameMaterial: "Carbon, reinforced", hardness: "medium-hard" },
    set: { faceMaterial: "12K carbon, textured 3D finish" },
    roundup: {
      status: "reviewed",
      summary:
        "Jon Sanz's racket. Padelful scores it 8.9 for power, 8.6 for control and 8.8 for manoeuvrability: clearly offensive, with heavy volleys and decisive smashes, but precise enough from the back glass.",
      liked: ["Speed and heavy volleys", "Decisive smashes", "Decent precision from the back"],
      watchOuts: ["Sweet spot smaller than average (7.9)", "Heavier than most (365–385 g)"],
      suits: "Aggressive players on either side.",
      ourRead: "An attacking racket with real control. Worth a look outside the big brands.",
      facts: [{ label: "Padelful scores", value: "Power 8.9 · Control 8.6 · Sweet spot 7.9" }],
      sources: [S.padelful("drop-shot-axion-attack-1-5-jon-sanz-2025"), { name: "Ipon Tennis", url: "https://www.ipontennis.com/en/padel-rackets/padel-racket-drop-shot-jon-sanz-axion-attack-15-2025" }],
    },
  },
  "wilson-endure-pro-v1-2026": {
    fill: { hardness: "medium" },
    roundup: {
      status: "reviewed",
      summary:
        "A round, low-balanced control racket. Retail reviews praise the precise placement and easy handling, and a good balance of control and power for its type.",
      liked: ["Precise placement", "Easy to handle", "Double-density foam for a soft, precise response"],
      watchOuts: ["Limited power overhead"],
      suits: "Advanced control players.",
      ourRead: "A refined control racket. The non-Pro Endure is softer and more forgiving for intermediates.",
      facts: [],
      sources: [S.padelshop("en-it/products/wilson-endure-pro-v1-2026"), { name: "Padel USA", url: "https://padelusa.com/es/products/wilson-endure-v1-2026-padel-racket" }],
    },
  },
  "wilson-defy-pro-v1": {
    roundup: {
      status: "reviewed",
      summary:
        "Tennis Warehouse's testers call it Wilson's heaviest and most powerful racket. It ends points with devastating pace, and has surprisingly good touch and spin, so lobs and volleys are very doable.",
      liked: ["Devastating pace", "Surprising touch and spin", "Handles well for its weight", "Suits more styles than expected"],
      watchOuts: ["Heavy (about 370 g)"],
      suits: "Aggressive advanced players, and defenders who want more punch.",
      ourRead: "A power racket with manners. One of the more versatile heavy diamonds.",
      facts: [],
      sources: [S.tw("Wilson_Defy_Pro_v1_Padel_Racket/descpage-WPRDEFPV1.html"), S.padelshop("en-fr/products/wilson-defy-pro-v1-padel-racket")],
    },
  },
};

/** Fills spec gaps and attaches the round-up. Never overwrites a brand-listed value (except `set`). */
export function withResearch(rackets: SeedRacket[], defaultSourceNote: string): SeedRacket[] {
  return rackets.map((r) => {
    const x = racketResearch[r.slug];
    if (!x) return r;
    const specs = { ...r.specs };
    const filled: string[] = [];
    for (const [k, v] of Object.entries(x.fill ?? {}) as Array<[keyof SpecPatch, never]>) {
      if (specs[k] === null || specs[k] === undefined) {
        specs[k] = v;
        filled.push(k);
      }
    }
    for (const [k, v] of Object.entries(x.set ?? {}) as Array<[keyof SpecPatch, never]>) {
      specs[k] = v;
      filled.push(k);
    }
    const fields = [...new Set(filled.map((k) => FIELD_NAMES[k]))];
    const note = fields.length
      ? ` ${fields.join(", ")} added from retailer and review listings (${x.roundup.sources.map((s) => s.name).join(", ")}), 7 Oct 2026; not checked against the brand.`
      : "";
    return {
      ...r,
      specs,
      specSourceNote: (r.specSourceNote ?? defaultSourceNote) + note,
      roundup: { ...x.roundup, checkedOn: RESEARCH_CHECKED_ON },
    };
  });
}

const FIELD_NAMES: Record<string, string> = {
  weightMinG: "Weight",
  weightMaxG: "Weight",
  balance: "Balance",
  balanceMm: "Balance point",
  hardness: "Hardness",
  thicknessMm: "Thickness",
  frameMaterial: "Frame material",
  faceMaterial: "Face material",
  coreMaterial: "Core",
  surfaceFinish: "Surface finish",
};
