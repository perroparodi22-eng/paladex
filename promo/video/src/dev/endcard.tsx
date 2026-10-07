// Isolated entry for the "endcard" scene: node scripts/stills.mjs Dev out/endcard 0-300/30 --entry src/dev/endcard.tsx
import { registerRoot } from "remotion";
import { EndCard } from "../scenes/EndCard";
import { makeDevRoot } from "./SceneDev";

registerRoot(makeDevRoot("endcard", EndCard));
