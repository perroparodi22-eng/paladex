// Isolated entry for the "specs" scene: node scripts/stills.mjs Dev out/specs 0-300/30 --entry src/dev/specs.tsx
import { registerRoot } from "remotion";
import { Specs } from "../scenes/Specs";
import { makeDevRoot } from "./SceneDev";

registerRoot(makeDevRoot("specs", Specs));
