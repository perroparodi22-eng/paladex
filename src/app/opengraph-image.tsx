import { ImageResponse } from "next/og";
import { racketSvgDataUri } from "@/lib/racket-svg";
import { OG } from "@/lib/og";
import { siteConfig } from "@/config/site";

export const alt = `${siteConfig.name}: the 3D padel racket database`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  const a = racketSvgDataUri("diamond", { face: "#16181c", frame: "#0b0b0c", accent: "#dcef4a", accent2: "#eef1ec", grip: "#111214", pattern: "sweep", holes: "hex", bridge: false });
  const b = racketSvgDataUri("round", { face: "#c9cdd1", frame: "#1a1d22", accent: "#8f9bb3", accent2: "#2a2e35", grip: "#111214", pattern: "border", holes: "rings", bridge: false });
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          backgroundColor: OG.ground,
          backgroundImage: OG.stage("78%"),
          color: OG.ink,
          padding: 64,
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
          <div style={{ fontSize: 120, fontWeight: 800, lineHeight: 0.9, letterSpacing: -4 }}>{siteConfig.name}</div>
          <div style={{ fontSize: 40, marginTop: 28, color: OG.ink2 }}>Explore the racket that fits your game.</div>
          <div style={{ fontSize: 28, marginTop: 32, color: OG.ink }}>Every racket in 3D. Find your match.</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <img src={b} width={220} height={377} alt="" style={{ marginRight: -40, opacity: 0.75 }} />
            <img src={a} width={280} height={480} alt="" />
          </div>
          <div style={{ display: "flex", ...OG.shadow, width: 360, marginTop: -8 }} />
        </div>
      </div>
    ),
    size,
  );
}
