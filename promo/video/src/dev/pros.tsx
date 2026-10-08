// Isolated entry for the "pros" scene: node scripts/stills.mjs Dev out/pros 0-240/12 --entry src/dev/pros.tsx
import { registerRoot } from "remotion";
import { Pros } from "../scenes/Pros";
import { makeDevRoot } from "./SceneDev";

registerRoot(makeDevRoot("pros", Pros));
