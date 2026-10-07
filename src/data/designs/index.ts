/**
 * Registry of platform-created designs. Add a racket here after tracing its
 * photos; scripts/generate-models.ts then builds a real model for it instead
 * of a placeholder.
 */
import type { PhotoDesign } from "./types";
import { metalbone34 } from "./adidas-metalbone-3-4";
import { catalogueDesigns } from "./catalogue.generated";

export const photoDesigns: Record<string, PhotoDesign> = {
  [metalbone34.slug]: metalbone34,
  // Rackets from the owner's brand catalogue (scripts/build-catalogue-designs.ts).
  ...catalogueDesigns,
};
