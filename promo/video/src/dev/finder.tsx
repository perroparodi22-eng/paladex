// Isolated entry for the "finder" scene: node scripts/stills.mjs Dev out/finder 0-300/30 --entry src/dev/finder.tsx
import { registerRoot } from "remotion";
import { Finder } from "../scenes/Finder";
import { makeDevRoot } from "./SceneDev";

registerRoot(makeDevRoot("finder", Finder));
