// "Black studio" tokens, copied from the site (src/app/globals.css) so the ad and the product match.
export const C = {
  ground: "#0a0b0d",
  studio: "#070809",
  surface: "#131519",
  surface2: "#1a1d22",
  surface3: "#23272d",
  ink: "#eceef1",
  ink2: "#a9aeb8",
  ink3: "#878d98",
  court: "#eceef1", // action colour (off-white pills)
  onCourt: "#0a0b0d",
  mist: "#3b4049",
  ball: "#d9f04a", // only for the sweet spot / match highlights
  warn: "#f2c26b",
  ok: "#5fd6a4",
  danger: "#ff7b6e",
} as const;

export const FONT = '"Google Sans Flex", "Segoe UI", system-ui, sans-serif';

/** The site's `.display` style: upright, wide, semibold. */
export const display = {
  fontFamily: FONT,
  fontWeight: 620,
  fontVariationSettings: '"wdth" 112',
  letterSpacing: "-0.035em",
  lineHeight: 0.98,
  color: C.ink,
} as const;

export const body = {
  fontFamily: FONT,
  fontWeight: 450,
  color: C.ink2,
} as const;
