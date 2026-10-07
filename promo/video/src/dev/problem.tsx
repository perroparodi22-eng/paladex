// Isolated entry for the "problem" scene: node scripts/stills.mjs Dev out/problem 0-300/30 --entry src/dev/problem.tsx
import { registerRoot } from "remotion";
import { Problem } from "../scenes/Problem";
import { makeDevRoot } from "./SceneDev";

registerRoot(makeDevRoot("problem", Problem));
