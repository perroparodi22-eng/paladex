// Isolated entry for the "cold-open" scene: node scripts/stills.mjs Dev out/cold-open 0-300/30 --entry src/dev/cold-open.tsx
import { registerRoot } from "remotion";
import { ColdOpen } from "../scenes/ColdOpen";
import { makeDevRoot } from "./SceneDev";

registerRoot(makeDevRoot("cold-open", ColdOpen));
