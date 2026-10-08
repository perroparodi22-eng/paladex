// Isolated entry for the "brands" scene: node scripts/stills.mjs Dev out/brands 0-300/30 --entry src/dev/brands.tsx
import { registerRoot } from "remotion";
import { Brands } from "../scenes/Brands";
import { makeDevRoot } from "./SceneDev";

registerRoot(makeDevRoot("brands", Brands));
