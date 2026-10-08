/**
 * Black studio styling for the generated share images (opengraph-image.tsx).
 * Mirrors the .stage-sky backdrop and the ink tokens in globals.css; satori
 * can't read CSS variables, so the values are repeated here.
 */
export const OG = {
  ground: "#070809",
  ink: "#eceef1",
  ink2: "#a9aeb8",
  ink3: "#878d98",
  rule: "rgba(236, 238, 241, 0.18)",
  lime: "#dcef4a",
  /** One soft spotlight centred on the racket, as on the site's stage. */
  stage: (x: string) =>
    `radial-gradient(circle at ${x} 52%, rgba(255,255,255,0.16), rgba(255,255,255,0) 40%), radial-gradient(ellipse at 50% 100%, rgba(255,255,255,0.05), rgba(255,255,255,0) 60%)`,
  /** Soft floor shadow under a standing racket. */
  shadow: { width: 220, height: 26, borderRadius: 999, background: "radial-gradient(ellipse at center, rgba(0,0,0,0.85), rgba(0,0,0,0) 70%)" },
} as const;
