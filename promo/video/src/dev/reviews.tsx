// Isolated entry for the "reviews" scene: node scripts/stills.mjs Dev out/reviews 0-240/12 --entry src/dev/reviews.tsx
import { registerRoot } from "remotion";
import { Reviews } from "../scenes/Reviews";
import { makeDevRoot } from "./SceneDev";

registerRoot(makeDevRoot("reviews", Reviews));
