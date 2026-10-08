// Google Sans Flex (variable: weight 400–700, width 100–115%), the site's only face.
import { continueRender, delayRender, staticFile } from "remotion";

let loaded = false;
export const loadFonts = () => {
  if (loaded || typeof document === "undefined") return;
  loaded = true;
  const handle = delayRender("Loading Google Sans Flex");
  const face = new FontFace("Google Sans Flex", `url(${staticFile("fonts/google-sans-flex-v23-latin.woff2")}) format("woff2")`, {
    weight: "400 700",
    stretch: "100% 115%",
    style: "normal",
  });
  face
    .load()
    .then((f) => {
      document.fonts.add(f);
      continueRender(handle);
    })
    .catch((err) => {
      console.error(err);
      continueRender(handle);
    });
};
