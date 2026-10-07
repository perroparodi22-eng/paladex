// Isolated entry for the "turn" scene: node scripts/stills.mjs Dev out/turn 0-300/30 --entry src/dev/turn.tsx
import { registerRoot } from "remotion";
import { Turn } from "../scenes/Turn";
import { makeDevRoot } from "./SceneDev";

registerRoot(makeDevRoot("turn", Turn));
