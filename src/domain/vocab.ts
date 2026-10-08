/**
 * Plain-language vocabulary. Every technical term the site shows is paired
 * with what it means for the player ("translate specs into decisions").
 */
import type {
  Balance,
  Basis,
  CameraView,
  Hardness,
  ModelStatus,
  OverlayKind,
  PlayerLevel,
  PlayingStyle,
  RacketShape,
  ScoreKey,
  StockStatus,
  SurfaceFinish,
  Verification,
} from "./types";

export interface TermInfo {
  label: string;
  /** One line: what it is. */
  meaning: string;
  /** One or two lines: what it does for your game. */
  effect: string;
}

export const SHAPE_INFO: Record<RacketShape, TermInfo> = {
  round: {
    label: "Round",
    meaning: "The head is almost circular and widest in the middle, so the sweet spot sits low and central, close to your hand.",
    effect: "The most forgiving and controllable shape. Off-centre hits still go where you aim, but smashes get less free power.",
  },
  teardrop: {
    label: "Teardrop",
    meaning: "Widest a little above the middle, narrowing towards the throat. The sweet spot sits slightly higher than on a round racket.",
    effect: "The middle ground: more reach and punch than round, more forgiveness than diamond. It suits players who attack and defend.",
  },
  hybrid: {
    label: "Hybrid",
    meaning: "Sits between teardrop and diamond. The head is wide high up, but the shoulders are softer than a full diamond.",
    effect: "Usually aims for diamond-like power with a slightly larger, more forgiving sweet spot.",
  },
  diamond: {
    label: "Diamond",
    meaning: "Widest high up near the tip, tapering in straight lines to the throat. The sweet spot sits high on the face.",
    effect: "Maximum leverage for overheads and smashes. The smaller, higher sweet spot punishes off-centre hits, so it rewards good technique.",
  },
};

export const BALANCE_INFO: Record<Balance, TermInfo> = {
  low: {
    label: "Low (head-light)",
    meaning: "More of the weight sits towards the handle.",
    effect: "Quick to move into position for volleys and defence and easy on the arm, but it gives you less free power on smashes.",
  },
  "medium-low": {
    label: "Medium-low",
    meaning: "Slightly towards the handle.",
    effect: "Easy to handle at the net, with a little more stability than a head-light racket.",
  },
  medium: {
    label: "Medium (even)",
    meaning: "Weight is spread evenly between head and handle.",
    effect: "A neutral feel: neither sluggish nor whippy. It suits all-round players.",
  },
  "medium-high": {
    label: "Medium-high",
    meaning: "Slightly towards the head.",
    effect: "Extra weight behind the ball on overheads, while staying manageable in quick exchanges.",
  },
  high: {
    label: "High (head-heavy)",
    meaning: "More of the weight sits towards the tip.",
    effect: "Hits harder on smashes and volleys, but feels slower to swing and is more demanding on the shoulder and elbow.",
  },
};

export const HARDNESS_INFO: Record<Hardness, TermInfo> = {
  soft: {
    label: "Soft",
    meaning: "A soft core that the ball sinks into.",
    effect: "Easy ball exit on slow shots and comfortable on the arm, but less precise when you swing hard.",
  },
  "medium-soft": {
    label: "Medium-soft",
    meaning: "Leans soft.",
    effect: "Comfortable and forgiving, with a bit more control on faster shots than a soft core.",
  },
  medium: {
    label: "Medium",
    meaning: "A balanced core density.",
    effect: "A mix of comfort and precision that suits most intermediate players.",
  },
  "medium-hard": {
    label: "Medium-hard",
    meaning: "Leans firm.",
    effect: "Precise and powerful at higher swing speeds, while still giving some help on slower balls.",
  },
  hard: {
    label: "Hard",
    meaning: "A firm, dense core.",
    effect: "Maximum precision and power when you hit fast. Slow balls need more effort to push, and more vibration reaches the arm.",
  },
};

export const SURFACE_INFO: Record<SurfaceFinish, TermInfo> = {
  smooth: {
    label: "Smooth",
    meaning: "A flat, untextured face.",
    effect: "Clean, predictable contact on flat shots. Less grip on the ball for heavy spin.",
  },
  rough: {
    label: "Rough",
    meaning: "A textured face.",
    effect: "Grips the ball for more spin on slices, kick serves and viboras.",
  },
  sand: {
    label: "Sand-textured",
    meaning: "A fine grit finish on the face.",
    effect: "Adds spin with a softer touch than a raised 3D texture, though the grit can wear down over time.",
  },
  "3d": {
    label: "3D texture",
    meaning: "A raised relief pattern moulded into the face.",
    effect: "The most bite on the ball, for players who rely on spin and effects.",
  },
};

export const LEVEL_INFO: Record<PlayerLevel, { label: string; description: string }> = {
  beginner: { label: "Beginner", description: "Learning the basics. Values forgiveness, comfort and a light feel." },
  intermediate: { label: "Intermediate", description: "Plays regularly with consistent technique, and wants a balance of control and power." },
  advanced: { label: "Advanced", description: "Strong technique and swing speed. Can exploit a demanding racket." },
};

export const STYLE_INFO: Record<PlayingStyle, { label: string; description: string }> = {
  power: { label: "Power", description: "Wins points with hard smashes and fast volleys." },
  control: { label: "Control", description: "Places the ball precisely and builds the point patiently." },
  "all-round": { label: "All-round", description: "Comfortable everywhere on court, attacking and defending." },
  defensive: { label: "Defensive", description: "Plays from the back glass and resets with lobs and soft balls." },
  aggressive: { label: "Aggressive", description: "Takes the net early and finishes points overhead." },
};

export const SCORE_INFO: Record<ScoreKey, { label: string; meaning: string }> = {
  power: { label: "Power", meaning: "How much speed the racket adds to the ball on full swings and overheads." },
  control: { label: "Control", meaning: "How precisely the ball goes where you aim, especially on touch shots." },
  maneuverability: { label: "Maneuverability", meaning: "How quickly the racket moves into position at the net and in defence." },
  forgiveness: { label: "Forgiveness", meaning: "How well off-centre hits still turn out." },
  sweetSpot: { label: "Sweet spot", meaning: "How large and accessible the ideal hitting zone feels." },
  defense: { label: "Defence", meaning: "How well it handles lobs, walls and blocking from the back of the court." },
  attack: { label: "Attack", meaning: "How well it finishes points with smashes, bandejas and viboras." },
};

export const SCORE_KEYS: ScoreKey[] = ["power", "control", "maneuverability", "forgiveness", "sweetSpot", "defense", "attack"];

export const MODEL_STATUS_INFO: Record<ModelStatus, { label: string; badge: string; description: string; interactive: boolean }> = {
  official: {
    label: "Official manufacturer model",
    badge: "Interactive 3D available",
    description: "3D model supplied by the manufacturer.",
    interactive: true,
  },
  licensed: {
    label: "Licensed 3D model",
    badge: "Interactive 3D available",
    description: "3D model licensed from a third party.",
    interactive: true,
  },
  platform: {
    label: "Platform-created model",
    badge: "Interactive 3D available",
    description: "3D model built by Paladex to represent this racket. Not supplied by the manufacturer.",
    interactive: true,
  },
  placeholder: {
    label: "Placeholder model",
    badge: "Interactive 3D · placeholder",
    description:
      "A generic racket in this racket's shape class and our own colours. It is not this model's real design and will be replaced when an official or licensed model is available.",
    interactive: true,
  },
  unavailable: {
    label: "No 3D model yet",
    badge: "3D model coming soon",
    description: "There is no 3D model for this racket yet. You are seeing an image preview.",
    interactive: false,
  },
};

export const VERIFICATION_INFO: Record<Verification, { label: string; description: string }> = {
  verified: { label: "Verified", description: "Checked against the manufacturer's published specification." },
  unverified: {
    label: "Unverified",
    description: "Compiled from public listings and not yet checked against the manufacturer. Treat it as indicative.",
  },
  placeholder: { label: "Placeholder", description: "Sample data used while building the catalog. Not real product information." },
};

export const BASIS_INFO: Record<Basis, { label: string; description: string }> = {
  manufacturer: { label: "Manufacturer data", description: "Based on the manufacturer's published specification." },
  platform: { label: "Platform evaluation", description: "Paladex's own assessment. Not a manufacturer measurement." },
  illustrative: {
    label: "Illustration",
    description: "An explanatory visualization of the concept. It is not measured data for this racket.",
  },
};

export const OVERLAY_INFO: Record<OverlayKind, { label: string; description: string }> = {
  "sweet-spot": { label: "Sweet spot", description: "Where clean contact is easiest on this shape class." },
  "impact-zone": { label: "Impact zone", description: "The wider area where hits still feel solid." },
  balance: { label: "Balance point", description: "Where the racket would balance on a finger." },
  dimensions: { label: "Dimensions", description: "Length, width and profile thickness." },
  "weight-distribution": { label: "Weight distribution", description: "Where the mass sits along the racket, head to handle." },
  "material-layers": { label: "Material layers", description: "Face, core, frame and grip, separated." },
};

export const VIEW_INFO: Record<CameraView, { label: string; shortcut: string }> = {
  hero: { label: "Three-quarter", shortcut: "1" },
  front: { label: "Front", shortcut: "F" },
  back: { label: "Back", shortcut: "B" },
  edge: { label: "Edge profile", shortcut: "E" },
  top: { label: "Top edge", shortcut: "T" },
  grip: { label: "Grip & handle", shortcut: "G" },
  detail: { label: "Surface close-up", shortcut: "D" },
};

export const STOCK_INFO: Record<StockStatus, string> = {
  in_stock: "In stock",
  low_stock: "Low stock",
  out_of_stock: "Out of stock",
  preorder: "Pre-order",
  unknown: "Stock unknown",
};

export function weightEffect(min: number | null, max: number | null): string {
  const mid = min && max ? (min + max) / 2 : (min ?? max);
  if (!mid) return "Weight not published yet.";
  if (mid < 355) return "On the light side: easy to swing for long matches and quick at the net, with less mass behind the ball.";
  if (mid <= 368) return "A mid-range weight that most adult players handle comfortably, balancing stability and speed.";
  return "On the heavy side: more stability and punch, but more tiring over long matches and slower in fast exchanges.";
}

export function thicknessEffect(mm: number | null): string {
  if (!mm) return "Profile thickness not published yet.";
  if (mm >= 38) return "A full 38 mm profile (the regulation maximum) gives more stability and power.";
  return "A slimmer profile cuts through the air a little faster and feels more manoeuvrable.";
}

export function levelsLabel(levels: PlayerLevel[]): string {
  if (!levels.length) return "Not specified";
  return levels.map((l) => LEVEL_INFO[l].label).join(" · ");
}

export function stylesLabel(styles: PlayingStyle[]): string {
  if (!styles.length) return "Not specified";
  return styles.map((s) => STYLE_INFO[s].label).join(" · ");
}
