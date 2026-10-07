// Isolated entry for the "reveal" scene: node scripts/stills.mjs Dev out/reveal 0-300/30 --entry src/dev/reveal.tsx
import { registerRoot } from "remotion";
import { Reveal } from "../scenes/Reveal";
import { makeDevRoot } from "./SceneDev";

registerRoot(makeDevRoot("reveal", Reveal));
