import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // Three.js scene code legitimately mutates objects created by React Three Fiber.
      "react-hooks/immutability": "off",
      // The viewer and dialogs sync React state with browser APIs (WebGL, IntersectionObserver,
      // <dialog>) inside effects. Keep these React Compiler hints visible without failing the build.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
    },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts", "public/**", "data/**", "drizzle/**", ".tmp/**", ".impeccable/**", "promo/**"]),
]);

export default eslintConfig;
